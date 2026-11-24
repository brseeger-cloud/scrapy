import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITES = Path(__file__).resolve().parent / "sites"
sys.path.insert(0, str(ROOT))


class _Handler(SimpleHTTPRequestHandler):
    """Serves tests/sites/<site>/ with /about-us, /about-us/ -> about-us.html."""

    def __init__(self, *args, log, **kwargs):
        self._log = log
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        base = Path(self.directory)
        clean = path.strip("/")
        if not clean:
            return str(base / "index.html")
        for candidate in (base / clean, base / f"{clean}.html"):
            if candidate.is_file():
                return str(candidate)
        return str(base / "__missing__")

    def log_request(self, code="-", size="-"):
        self._log.append(self.path)

    def log_message(self, fmt, *args):
        pass


class SiteServer:
    def __init__(self, name):
        self.name = name
        self.requests: list[str] = []
        handler = partial(_Handler, directory=str(SITES / name), log=self.requests)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def page_requests(self):
        return [p for p in self.requests if p != "/robots.txt"]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def sites():
    servers = {p.name: SiteServer(p.name) for p in SITES.iterdir() if p.is_dir()}
    yield servers
    for s in servers.values():
        s.close()
