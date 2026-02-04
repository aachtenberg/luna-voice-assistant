"""Background HTTP server for Prometheus metrics."""

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from metrics import get_metrics, get_content_type

METRICS_PORT = 8001


class MetricsHandler(BaseHTTPRequestHandler):
    """Handle /metrics requests."""

    def do_GET(self):
        if self.path == "/metrics":
            content = get_metrics()
            self.send_response(200)
            self.send_header("Content-Type", get_content_type())
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def start_metrics_server(port: int = METRICS_PORT):
    """Start metrics HTTP server in background thread."""
    server = HTTPServer(("0.0.0.0", port), MetricsHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server
