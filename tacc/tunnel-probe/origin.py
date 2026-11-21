"""Serve the repository's test PDF as a local HTTP endpoint."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PDF_PATH = Path(__file__).resolve().with_name("paper.pdf")


class PDFHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/paper.pdf":
            self.send_error(404)
            return

        pdf = PDF_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(pdf)))
        self.end_headers()
        self.wfile.write(pdf)

        job_id = self.headers.get("X-TACC-Probe-Job", "")
        client = f"TACC job {job_id}" if job_id.isascii() and job_id.isdecimal() else "smoke check"
        print(f"Origin served {len(pdf)} PDF bytes for {client}", flush=True)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", 8765), PDFHandler) as server:
        print("Origin listening at http://127.0.0.1:8765/paper.pdf", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
