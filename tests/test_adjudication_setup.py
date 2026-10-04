"""Setup of the adjudication app (crrt.adjudication_setup).

No network and no MIMIC data: the download runs against a local server that
plays PhysioNet, with Basic auth and HTTP Range, serving made-up bytes.
"""

import hashlib
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from crrt import build_db
from crrt.adjudication_setup import basic, fetch, launcher, needed, sums, synced, unpack

BLOB = bytes(range(256)) * 4096
DIGEST = hashlib.sha256(BLOB).hexdigest()
AUTH = basic("adjudicator", "right password")


@pytest.mark.parametrize("path, cloud", [
    ("C:/Users/ana/OneDrive/crrt", True),
    ("C:/Users/ana/OneDrive - St Elsewhere/Documents/crrt", True),
    ("/Users/ana/Library/CloudStorage/Dropbox/crrt", True),
    ("/Users/ana/Library/Mobile Documents/com~apple~CloudDocs/crrt", True),
    ("/Users/ana/Google Drive/crrt", True),
    ("C:/Users/ana/crrt", False),
    ("/home/ana/crrt", False),
])
def test_cloud_synced_folders_are_recognised(path, cloud):
    assert synced(Path(path)) is cloud


def test_it_downloads_exactly_what_the_database_build_reads():
    assert sorted(needed()) == sorted(f"{t}.csv.gz" for t in [*build_db.PARQUET_TABLES, *build_db.CSV_TABLES])


def test_checksum_lines_are_read(tmp_path):
    (tmp_path / "SHA256SUMS.txt").write_text(f"{DIGEST} hosp/admissions.csv.gz\n\n{'0' * 64}  LICENSE.txt\n")
    assert sums(tmp_path / "SHA256SUMS.txt") == {"hosp/admissions.csv.gz": DIGEST, "LICENSE.txt": "0" * 64}


class PhysioNet(BaseHTTPRequestHandler):
    ranges: list[str | None] = []

    def do_GET(self):
        # As PhysioNet does: anything but wget gets a flat 403, login or not.
        if not self.headers.get("User-Agent", "").startswith("Wget/"):
            self.send_response(403)
            self.end_headers()
            return
        if self.headers.get("Authorization") != AUTH:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="PhysioNet"')
            self.end_headers()
            return
        rng = self.headers.get("Range")
        self.ranges.append(rng)
        start = int(rng.removeprefix("bytes=").rstrip("-")) if rng else 0
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(BLOB) - start))
        self.end_headers()
        self.wfile.write(BLOB[start:])

    def log_message(self, *args):
        pass


@pytest.fixture
def physionet():
    PhysioNet.ranges = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), PhysioNet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/hosp/admissions.csv.gz"
    srv.shutdown()
    srv.server_close()


def test_a_download_is_kept_only_once_its_checksum_matches(physionet, tmp_path):
    dest = tmp_path / "hosp" / "admissions.csv.gz"
    fetch(physionet, dest, AUTH, DIGEST)
    assert dest.read_bytes() == BLOB and not dest.with_name(dest.name + ".part").exists()


def test_a_stopped_download_carries_on(physionet, tmp_path):
    dest = tmp_path / "admissions.csv.gz"
    half = len(BLOB) // 2
    dest.with_name(dest.name + ".part").write_bytes(BLOB[:half])
    fetch(physionet, dest, AUTH, DIGEST)
    assert PhysioNet.ranges == [f"bytes={half}-"]
    assert dest.read_bytes() == BLOB


def test_a_damaged_download_is_deleted(physionet, tmp_path):
    dest = tmp_path / "admissions.csv.gz"
    with pytest.raises(SystemExit, match="damaged"):
        fetch(physionet, dest, AUTH, "0" * 64)
    assert not dest.exists() and not dest.with_name(dest.name + ".part").exists()


def test_a_wrong_password_says_so(physionet, tmp_path):
    with pytest.raises(SystemExit, match="did not accept"):
        fetch(physionet, tmp_path / "admissions.csv.gz", basic("adjudicator", "wrong"), DIGEST)


def test_the_windows_launcher_names_the_home_folder_by_variable():
    home = Path("C:/Users/José")
    name, text = launcher("win32", home / "crrt", str(home / ".local/bin/uv.exe"), home)
    assert name == "Adjudicate.bat" and text.endswith("pause\r\n")
    assert "%USERPROFILE%" in text and "José" not in text
    assert "crrt.adjudication_viewer serve" in text


@pytest.mark.parametrize("platform, name", [("darwin", "Adjudicate.command"), ("linux", "Adjudicate.desktop")])
def test_the_mac_and_linux_launchers_run_the_app_from_the_repo(platform, name):
    repo, uv = Path("/Users/ana/crrt"), "/Users/ana/.local/bin/uv"
    got, text = launcher(platform, repo, uv, Path("/Users/ana"))
    assert got == name and str(repo) in text and f'"{uv}" run python -m crrt.adjudication_viewer serve' in text


def test_unpacking_replaces_the_pages_and_keeps_the_answers(tmp_path):
    package = tmp_path / "adjudication_pages_test.zip"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("index.html", "new list")
        z.writestr("practice/practice_1.html", "practice page")
        z.writestr("verdicts.csv", "review_order,verdict,note\r\n1,,\r\n")
        z.writestr("practice_verdicts.csv", "practice_order,verdict,note\r\n1,,\r\n")
    out = tmp_path / "adjudication"
    out.mkdir()
    (out / "index.html").write_text("old list")
    answered = "review_order,verdict,note\r\n1,clotting,checked\r\n"
    (out / "verdicts.csv").write_bytes(answered.encode())
    unpack(package, out)
    assert (out / "index.html").read_text() == "new list"
    assert (out / "practice" / "practice_1.html").exists()
    assert (out / "verdicts.csv").read_bytes() == answered.encode()  # answers kept
    assert (out / "practice_verdicts.csv").exists()            # missing sheet added
