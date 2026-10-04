"""The adjudication app: serves the circuit pages and saves each verdict
click (Part 5.1 step 4).

This is what runs on the adjudicator's computer, so it uses Python's standard
library and nothing else. On Windows 11, Smart App Control blocks unsigned
programs, with no per-app exception, and that includes uv and the Python
it downloads. Python from python.org is signed and allowed, and needs no
packages to run this file (docs/decisions.md 2026-10-04, "The package runs
on Python alone").

`crrt.adjudication_viewer build` copies this file into the pages folder with
`manifest.json`, which holds the settings it needs from config/config.yaml,
and the launchers. `crrt.adjudication_viewer export` zips that folder for the
adjudicator, who runs it by double-clicking Adjudicate:

  python adjudication_app.py           serve the folder this file is in
  python -m crrt.adjudication_app DIR  serve DIR

It serves the pages on 127.0.0.1 and opens the browser. Each verdict button
saves to the sheet at once, so a revisited page shows its verdict. Once every
circuit has one, the file to send is written: review_order and verdict
only. The notes column stays on this machine, because a note can quote a
charted value. A page opened from disk cannot write a file, which is why
this is a server.
"""

from __future__ import annotations  # Annotations stay unevaluated on a Mac's Python 3.9.

import csv
import io
import json
import os
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MANIFEST = "manifest.json"
SHEET = "verdicts.csv"
PRACTICE_SHEET = "practice_verdicts.csv"
# Page kind: (sheet, its key column).
SHEETS = {"sample": (SHEET, "review_order"), "practice": (PRACTICE_SHEET, "practice_order")}
# What /api/ping answers, so a second double-click can tell this app from
# another program on the port.
APP = "crrt-adjudication"
PING_SECONDS = 2
# Path parts that mean a folder is synced to a cloud, matched without case.
CLOUD_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud",
                 "cloudstorage", "mobile documents")


def synced(path: Path) -> bool:
    """Whether `path` is inside a cloud-synced folder."""
    return any(m in part.lower() for part in path.parts for m in CLOUD_MARKERS)


def settings(out: Path) -> dict[str, Any]:
    """The manifest `crrt.adjudication_viewer build` wrote from the config:
    sample_sha256, sample_size, practice_size, verdicts, port."""
    return json.loads((out / MANIFEST).read_text(encoding="utf-8"))


def read_sheet(path: Path) -> dict[int, list[str]]:
    """{order: [verdict, note]}. Empty if the sheet does not exist yet."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r[0]): [r[1], r[2]] for r in list(csv.reader(f))[1:]}


def sheet_text(key: str, rows: dict[int, list[str]]) -> str:
    text = io.StringIO()
    w = csv.writer(text)
    w.writerow([key, "verdict", "note"])
    w.writerows([n, verdict, note] for n, (verdict, note) in sorted(rows.items()))
    return text.getvalue()


def write_sheet(path: Path, key: str, rows: dict[int, list[str]]) -> None:
    """Write the whole sheet to a temporary file, then swap it in, so a
    crash never leaves half a sheet."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:  # write_text() has no newline= before 3.10.
        f.write(sheet_text(key, rows))
    os.replace(tmp, path)


def ensure_sheets(s: dict[str, Any], out: Path) -> None:
    """Create any verdict sheet that is missing, empty. An exported package
    carries none, so unzipping a newer package over the folder never
    touches the answers."""
    sizes = {"sample": s["sample_size"], "practice": s["practice_size"]}
    for kind, (sheet, key) in SHEETS.items():
        if not (out / sheet).exists():
            write_sheet(out / sheet, key, {n: ["", ""] for n in range(1, sizes[kind] + 1)})


def send_file(s: dict[str, Any], out: Path) -> Path:
    """The one file that goes back to the team."""
    return out / f"verdicts_send_{s['sample_sha256'][:12]}.csv"


def check(s: dict[str, Any], out: Path) -> Path | None:
    """Validate the sheet. Returns the file to send once it is complete."""
    n_expected, allowed = s["sample_size"], set(s["verdicts"])
    with (out / SHEET).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    orders = [r["review_order"] for r in rows]
    expected = [str(k) for k in range(1, n_expected + 1)]
    if sorted(orders, key=int) != expected:
        raise ValueError(f"{SHEET} must have review_order 1 to {n_expected}, each once")
    bad = [r["review_order"] for r in rows if r["verdict"].strip() and r["verdict"].strip() not in allowed]
    if bad:
        raise ValueError(f"not one of {sorted(allowed)} at review_order {', '.join(bad)}")
    done = sum(bool(r["verdict"].strip()) for r in rows)
    print(f"{done} of {n_expected} circuits have a verdict")
    if done < n_expected:
        return None
    send = send_file(s, out)
    with send.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_order", "verdict"])
        w.writerows(sorted(((int(r["review_order"]), r["verdict"].strip()) for r in rows)))
    print(f"wrote {send}: review_order and verdict only, no notes")
    return send


def reveal(path: Path) -> None:
    """Show `path` in the file manager, selected where the platform can."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


class Handler(SimpleHTTPRequestHandler):
    """Serves the pages under `out` and saves verdicts to the sheets.

    The server listens on 127.0.0.1, so nothing outside this computer can
    reach it. A web page open in another tab still could, so a request
    naming any other host (DNS rebinding, which would let it read pages) is
    refused, and so is a POST from any other origin or not sent as JSON
    (which would let it change verdicts)."""

    def __init__(self, *args: Any, s: dict[str, Any], out: Path, **kwargs: Any):
        self.s, self.out = s, out
        super().__init__(*args, directory=str(out), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # The launcher window is for the adjudicator, not a request log.

    def local(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def reply(self, status: HTTPStatus, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_head(self):  # Every static GET and HEAD passes through here.
        if self.headers.get("Host") not in self.local():
            self.send_error(HTTPStatus.FORBIDDEN)
            return None
        return super().send_head()

    def do_GET(self) -> None:
        if not self.path.startswith("/api/"):
            return super().do_GET()
        if self.headers.get("Host") not in self.local():
            return self.reply(HTTPStatus.FORBIDDEN, {"error": "refused"})
        if self.path == "/api/ping":
            return self.reply(HTTPStatus.OK, {"app": APP})
        if self.path == "/api/verdicts":
            body: dict[str, Any] = {
                kind: {str(n): {"verdict": v, "note": note} for n, (v, note) in read_sheet(self.out / sheet).items()}
                for kind, (sheet, _) in SHEETS.items()}
            send = send_file(self.s, self.out)
            body["send"] = send.name if send.exists() else None
            return self.reply(HTTPStatus.OK, body)
        self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        local = self.local()
        if (self.headers.get("Host") not in local
                or self.headers.get("Origin") not in {f"http://{h}" for h in local}
                or self.headers.get_content_type() != "application/json"):
            return self.reply(HTTPStatus.FORBIDDEN, {"error": "refused"})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self.reply(HTTPStatus.BAD_REQUEST, {"error": "the request could not be read"})
        if self.path == "/api/verdict":
            return self.save(data)
        if self.path == "/api/reveal":
            send = send_file(self.s, self.out)
            reveal(send if send.exists() else self.out)
            return self.reply(HTTPStatus.OK, {})
        self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def save(self, data: Any) -> None:
        """Set the verdict and/or note of one circuit, from {kind, n,
        verdict?, note?}, and rewrite its sheet."""
        if not isinstance(data, dict) or data.get("kind") not in SHEETS:
            return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that page was not recognised"})
        sheet, key = SHEETS[data["kind"]]
        with self.server.lock:
            rows = read_sheet(self.out / sheet)
            n = data.get("n")
            if type(n) is not int or n not in rows:
                return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that circuit was not recognised"})
            if "verdict" in data and data["verdict"] not in self.s["verdicts"]:
                return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that answer was not recognised"})
            if "note" in data and not isinstance(data["note"], str):
                return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that note was not recognised"})
            rows[n] = [data.get("verdict", rows[n][0]), data.get("note", rows[n][1])]
            try:
                write_sheet(self.out / sheet, key, rows)
            except PermissionError:
                return self.reply(HTTPStatus.CONFLICT, {
                    "error": f"{sheet} is open in another program, probably Excel. Close it, then click again"})
            if data["kind"] == "sample":
                check(self.s, self.out)
        self.reply(HTTPStatus.OK, {})


class LocalServer(ThreadingHTTPServer):
    """Threads, not one request at a time: browsers open spare connections
    that a single-threaded server would wait on. Writes take `lock`."""

    # On Windows SO_REUSEADDR lets a second server bind a port that is in
    # use, so a second double-click would start a second server instead of
    # finding the first.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port: int, handler: Any):
        super().__init__(("127.0.0.1", port), handler)
        self.lock = threading.Lock()


def make_server(s: dict[str, Any], out: Path, port: int) -> LocalServer:
    ensure_sheets(s, out)
    return LocalServer(port, partial(Handler, s=s, out=out))


def running(port: int) -> bool:
    """Whether this app already answers on `port`."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=PING_SECONDS) as r:
            return json.load(r).get("app") == APP
    except (OSError, ValueError):
        return False


def serve(out: Path) -> None:
    if synced(out):
        raise SystemExit(f"This folder is inside a cloud-synced folder:\n  {out}\n"
                         "The pages must never be synced to a cloud (PhysioNet DUA). Move the folder "
                         f"somewhere that is not synced, such as {Path.home() / 'Adjudication'}, then try again.")
    if not (out / "index.html").exists():
        raise SystemExit(f"No circuit pages in {out}. Tell the study team.")
    s = settings(out)
    url = f"http://127.0.0.1:{s['port']}/index.html"
    try:
        server = make_server(s, out, s["port"])
    except OSError:
        if not running(s["port"]):
            raise SystemExit(f"Another program is using port {s['port']}, so adjudication cannot start. "
                             "Tell the study team.")
        print("Adjudication is already open. Opening it in your browser again.")
        webbrowser.open(url)
        return
    print("Adjudication is open in your web browser.\n\n"
          "Keep this window open while you work.\n"
          "Close it when you stop: every click is already saved.\n\n"
          f"If the browser did not open, go to {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent)
