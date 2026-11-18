"""Lab receiver on 127.0.0.1:8080: logs every GET line to stdout and answers 200."""
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(self.command, self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")


HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
