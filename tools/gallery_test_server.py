"""Serve one built private gallery on loopback, with normal and ranged HTTP reads."""

import re
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class GalleryRequest(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if urlsplit(self.path).path != "/oasis-portrait-gallery.html":
            self.send_error(404)
            return
        data = self.server.gallery
        try:
            if "Range" in self.headers:
                match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers["Range"])
                if match:
                    start, end = map(int, match.groups())
                    if 0 <= start <= end < len(data):
                        self.send_range(data, start, end)
                        return
                self.send_error(416)
            else:
                self.send_document(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A browser may cancel a fallback response or close a page.

    def document_headers(self, size):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(size))
        self.end_headers()

    def send_document(self, data):
        self.document_headers(len(data))
        self.wfile.write(data)

    def send_range(self, data, start, end):
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self.wfile.write(data[start:end + 1])


@contextmanager
def gallery_http(gallery, handler=GalleryRequest):
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        server.gallery = memoryview(gallery.read_bytes())
        server.url = f"http://127.0.0.1:{server.server_port}/oasis-portrait-gallery.html"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()
