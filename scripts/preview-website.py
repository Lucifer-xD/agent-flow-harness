"""Preview the website locally with the same clean URLs as nginx (/features → features.html).

    python scripts/preview-website.py [port]      # default 5520, then open http://127.0.0.1:5520/
"""
import http.server
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "website"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        target = ROOT / path.lstrip("/")
        if path != "/" and not target.exists() and (ROOT / (path.lstrip("/") + ".html")).is_file():
            self.path = path + ".html"
        elif not target.exists():  # nginx answers 404 with this page; here it comes with a 200
            self.path = "/404.html"
        return super().send_head()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5520
    print(f"http://127.0.0.1:{port}/")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
