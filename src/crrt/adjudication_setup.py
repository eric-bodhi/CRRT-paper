"""Set up the adjudication app on the adjudicator's own computer (Part 5.1
step 4), on Windows, Mac or Linux. Read docs/adjudication_guide.md first.

  adjudicate.bat (Windows) or ./adjudicate.sh (Mac, Linux), which run
  uv run python -m crrt.adjudication_setup

The person setting up runs it once. After that the adjudicator only
double-clicks the Adjudicate launcher this puts on the desktop. In order:

1. Stops if this folder is inside a cloud-synced folder (OneDrive, Dropbox,
   iCloud, Google Drive). Syncing MIMIC-IV to a cloud breaks the DUA, and
   Windows often puts Desktop and Documents in OneDrive.
2. Gets the pages, in one of two ways:
   - **From the package** (docs/decisions.md 2026-10-04, "Hand the pages to
     a credentialed adjudicator"). This is the usual way.
     `crrt.adjudication_viewer export` writes the package on a team member's
     machine, and it is copied into this folder. Setup unpacks it into
     `paths.adjudication_dir`, keeping any verdict sheet already there, so
     a newer package never loses answers. No MIMIC-IV download and no
     database.
   - **Built here**, asked for only when there is no package and no pages.
     Setup downloads from `paths.mimic_url` the MIMIC-IV files
     crrt.build_db reads, and no others, with the adjudicator's own
     login, read hidden and never stored. A file keeps its real name only
     after its SHA-256 matches PhysioNet's SHA256SUMS.txt; a stopped
     download carries on from its `.part` file. Setup then runs the stages
     the sample needs: the database (only if there is none), circuits,
     cohort, the frozen sample, then the pages, which refuse a sample
     whose fingerprint is not the frozen one.
3. Writes the launcher, which runs `crrt.adjudication_viewer serve`.
"""

import base64
import getpass
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from http import HTTPStatus
from pathlib import Path

from crrt import build_db, config
from crrt.adjudication_viewer import SHEETS, package_name

SUMS = "SHA256SUMS.txt"
# Path parts that mean a folder is synced to a cloud, matched without case.
CLOUD_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud",
                 "cloudstorage", "mobile documents")
CHUNK_BYTES = 1 << 20
TIMEOUT_SECONDS = 60
# PhysioNet asks for a login only from wget, its documented download tool:
# on 2026-10-04 it answered 401 with a Basic challenge to "Wget/1.21.4", and
# 403 to Python's and curl's default agents, with or without a login. So the
# download names itself as wget, and says what it really is in the comment.
USER_AGENT = "Wget/1.21.4 (crrt-adjudication-setup)"


def synced(path: Path) -> bool:
    """Whether `path` is inside a cloud-synced folder."""
    return any(m in part.lower() for part in path.parts for m in CLOUD_MARKERS)


def needed() -> list[str]:
    """The MIMIC-IV files crrt.build_db reads, as paths under mimic_dir."""
    return [f"{t}.csv.gz" for t in [*build_db.PARQUET_TABLES, *build_db.CSV_TABLES]]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


def sums(path: Path) -> dict[str, str]:
    """{file: sha256} from a SHA256SUMS.txt."""
    return {name.strip(): digest for digest, name in
            (line.split(maxsplit=1) for line in path.read_text().splitlines() if line.strip())}


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def fetch(url: str, dest: Path, auth: str, expected: str | None) -> None:
    """Download `url` to `dest`, carrying on from `dest.part` if a previous
    run stopped. `dest` appears only once its SHA-256 equals `expected`."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    headers = {"Authorization": auth, "User-Agent": USER_AGENT} | ({"Range": f"bytes={have}-"} if have else {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SECONDS) as r:
            if r.status != HTTPStatus.PARTIAL_CONTENT:
                have = 0  # The server sent the whole file: start again.
            total = have + int(r.headers.get("Content-Length", 0))
            with part.open("ab" if have else "wb") as f:
                while chunk := r.read(CHUNK_BYTES):
                    f.write(chunk)
                    have += len(chunk)
                    print(f"\r  {dest.name}: {have / 1e6:,.0f} of {total / 1e6:,.0f} MB", end="", flush=True)
            print()
    except urllib.error.HTTPError as e:
        if e.code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise SystemExit("PhysioNet did not accept that username and password, or this account has "
                             "not signed the MIMIC-IV data use agreement. Check both, then run setup again.")
        # The .part file was already whole when the last run stopped.
        if e.code != HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE:
            raise SystemExit(f"PhysioNet answered {e.code} for {url}. Tell the study team.")
    except OSError as e:
        raise SystemExit(f"\nThe download stopped ({e}). Run setup again: it carries on where it stopped.")
    if expected and sha256(part) != expected:
        part.unlink()
        raise SystemExit(f"{dest.name} arrived damaged and was deleted. Run setup again to download it again.")
    part.replace(dest)


def download(cfg: dict) -> None:
    mimic_dir = config.path(cfg, "mimic_dir")
    missing = [f for f in needed() if not (mimic_dir / f).exists()]
    if not missing:
        print("MIMIC-IV files: all here.")
        return
    print(f"{len(missing)} MIMIC-IV files to download from PhysioNet, several GB in all.\n"
          "The adjudicator types their own PhysioNet login. It is used for this download only "
          "and never saved.")
    auth = basic(input("PhysioNet username: ").strip(),
                 getpass.getpass("PhysioNet password (hidden as you type): "))
    base = cfg["paths"]["mimic_url"]
    if not (mimic_dir / SUMS).exists():
        fetch(f"{base}/{SUMS}", mimic_dir / SUMS, auth, None)
    expected = sums(mimic_dir / SUMS)
    for f in missing:
        fetch(f"{base}/{f}", mimic_dir / f, auth, expected[f])


def run(*args: str) -> None:
    """One stage in its own process, as adjudicate.sh ran them. UTF-8 mode,
    because Windows' default encoding cannot write every character the
    stages print and write."""
    print(f"\n== {' '.join(args)}", flush=True)
    if subprocess.run([sys.executable, "-m", *args], env=os.environ | {"PYTHONUTF8": "1"}).returncode:
        raise SystemExit(f"Setup stopped while running {args[0]}. The message above says why. "
                         "Send that text, and nothing from any page, to the study team.")


def stages(cfg: dict) -> None:
    # Build the database only if there is none. Rebuilding recreates it from
    # scratch, which would delete every later stage's tables on a machine
    # that also runs run_all.sh.
    if not config.path(cfg, "duckdb").exists():
        run("crrt.build_db")
    for module in ("crrt.circuits", "crrt.cohort", "crrt.adjudication"):
        run(module)
    run("crrt.adjudication_viewer", "build")


def unpack(package: Path, out: Path) -> None:
    """Unpack the exported pages into `out`. A verdict sheet already there is
    kept: unpacking a newer package replaces the pages, never the answers."""
    sheets = {sheet for sheet, _ in SHEETS.values()}
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as z:
        for member in z.namelist():
            if not (member in sheets and (out / member).exists()):
                z.extract(member, out)


def desktop() -> Path:
    """The desktop folder. On Windows it can be moved, often into OneDrive,
    so ask Windows where it is."""
    if sys.platform == "win32":
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
    return Path.home() / "Desktop"


def launcher(platform: str, repo: Path, uv: str, home: Path) -> tuple[str, str]:
    """(file name, contents) of the double-click launcher for `platform`."""
    serve = "run python -m crrt.adjudication_viewer serve"
    if platform == "win32":
        # cmd reads a .bat in the console's legacy code page, so a home
        # folder named with accents would break it: name it %USERPROFILE%.
        def win(p: str | Path) -> str:
            p, h = str(p), str(home)
            return "%USERPROFILE%" + p[len(h):] if p.lower().startswith(h.lower()) else p
        # pause keeps the window open if the app stops with an error.
        return "Adjudicate.bat", f'@echo off\r\ncd /d "{win(repo)}"\r\n"{win(uv)}" {serve}\r\npause\r\n'
    if platform == "darwin":
        return "Adjudicate.command", f'#!/bin/bash\ncd "{repo}" || exit 1\n"{uv}" {serve}\n'
    return "Adjudicate.desktop", ("[Desktop Entry]\nType=Application\nName=Adjudicate\n"
                                  f'Path={repo}\nExec="{uv}" {serve}\nTerminal=true\n')


def place_launcher(repo: Path) -> Path:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise SystemExit("uv was not found. Install it (docs/adjudication_guide.md), then run setup again.")
    folder = desktop()
    if not folder.is_dir():
        folder = repo
    name, text = launcher(sys.platform, repo, uv, Path.home())
    path = folder / name
    path.write_text(text, newline="")
    if sys.platform != "win32":
        path.chmod(0o755)
    return path


def main() -> None:
    cfg = config.load()
    repo = config.REPO_ROOT
    if synced(repo):
        raise SystemExit(f"This folder is inside a cloud-synced folder:\n  {repo}\n"
                         "MIMIC-IV must never be synced to a cloud (PhysioNet DUA). Move the folder "
                         f"somewhere that is not synced, such as {Path.home() / 'crrt'}, and run setup again.")
    out = config.path(cfg, "adjudication_dir")
    package = repo / package_name(cfg)
    if package.exists():
        unpack(package, out)
        print(f"Unpacked the circuit pages from {package.name}. You can delete that file now.")
    elif not (out / "index.html").exists():
        print(f"There is no {package.name} in {repo}, and no circuit pages yet.")
        answer = input("Download MIMIC-IV with the adjudicator's own PhysioNet login and build the "
                       "pages on this computer instead? It takes hours and about 35 GB. [y/N] ")
        if answer.strip().lower() != "y":
            raise SystemExit(f"Copy {package.name} into {repo}, then run setup again.")
        download(cfg)
        stages(cfg)
    path = place_launcher(repo)
    where = "on the desktop" if path.parent != repo else f"in {repo}"
    print(f"\nSetup done. To adjudicate, double-click Adjudicate {where}.")


if __name__ == "__main__":
    main()
