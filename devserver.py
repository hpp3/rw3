"""Local dev server for site/ that disables caching, so edits always show on
reload. Production (GitHub Pages) caches normally via ETag/max-age — this
no-store behaviour is dev-only and never ships."""
import os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")

class NoCacheHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=SITE, **k)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Expires", "0")
        super().end_headers()
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    print(f"dev server (no-cache) on http://localhost:{PORT}  serving {SITE}")
    ThreadingHTTPServer(("", PORT), NoCacheHandler).serve_forever()
