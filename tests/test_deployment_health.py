import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Thread
import unittest


class DeploymentHealthTest(unittest.TestCase):
    def test_http_200_with_degraded_storage_fails_deployment(self):
        payload = {"status": "degraded", "storage": {"status": "error"}, "workspace": {"status": "ok"}}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        script = Path(__file__).resolve().parents[1] / "scripts/check-health.py"
        try:
            command = [sys.executable, str(script), "--url", f"http://127.0.0.1:{server.server_port}", "--attempts", "1"]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            payload.update(status="ok", storage={"status": "ok"})
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
