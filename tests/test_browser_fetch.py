import http.cookiejar
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from kurs_app.browser import write_cookies_txt
from kurs_app.fetch import fetch_resource


def test_cookie_file_private_and_loadable(tmp_path):
    f = tmp_path / "p" / "cookies.txt"
    write_cookies_txt([{"domain": ".a.b", "path": "/", "secure": True, "httpOnly": True, "expires": -1,
                        "name": "sid", "value": "v"}], f)
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    cj = http.cookiejar.MozillaCookieJar(str(f))
    cj.load(ignore_discard=True, ignore_expires=True)
    assert [c.name for c in cj] == ["sid"]


class H(BaseHTTPRequestHandler):
    seen = {}

    def do_GET(self):
        H.seen["cookie"] = self.headers.get("Cookie")
        H.seen["referer"] = self.headers.get("Referer")
        self.send_response(200)
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''Ek%20Dosya.pdf")
        self.end_headers()
        self.wfile.write(b"PDFDATA")

    def log_message(self, *a):
        pass


def test_fetch_resource_uses_cookies_and_header_name(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cf = tmp_path / "c.txt"
        write_cookies_txt([{"domain": "127.0.0.1", "path": "/", "secure": False, "expires": -1, "name": "sid", "value": "abc"}], cf)
        r = fetch_resource(f"http://127.0.0.1:{srv.server_port}/x", tmp_path / "out", "https://ref/", cf)
    finally:
        srv.shutdown()
    assert r["name"] == "Ek Dosya.pdf" and (tmp_path / "out" / "Ek Dosya.pdf").read_bytes() == b"PDFDATA"
    assert "sid=abc" in (H.seen["cookie"] or "") and H.seen["referer"] == "https://ref/"
