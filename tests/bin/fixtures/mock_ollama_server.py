#!/usr/bin/env python3
"""Minimal mock Ollama server for tests/bin/test_ardconfig_onboard.bats.

Serves GET /api/tags with a canned models list, mimicking the shape of a
real `ollama.Client().list()` response closely enough for the `ollama`
pip client library (>=0.4.8,<1.0.0) to parse it successfully.

Every field on ollama's ListResponse.Model besides `model` itself is
Optional (confirmed by inspecting ollama==0.6.2's ollama._types module
during TASK-017 authoring), so a minimal per-entry body of
{"model": "<name>"} round-trips correctly. Empirically confirmed against
this repo's real local Ollama server (`curl -s $ARDCONFIG_OLLAMA_HOST
/api/tags`) that the real server's response also includes a "name" key
per entry — but ollama's own typed Model class does NOT declare `name`
as a field, so `getattr(model_obj, "name", None)` is always `None` on a
real parsed response; `.model` is the only reliable attribute (this is
the empirical answer to design.md's Open Design Question New-1, recorded
here per TASK-017 step 4). We include both keys below to mirror the real
server's wire shape exactly, even though only "model" is actually
consumed by bin/ardconfig-onboard's check_ollama_available().

Usage:
  mock_ollama_server.py PORT [MODEL_NAME ...]

Listens on 127.0.0.1:PORT. Prints "READY" to stdout once listening (the
bats test polls for this line before proceeding), then serves forever
until killed (SIGTERM from the test's teardown).
"""
import http.server
import json
import sys


def make_handler(model_names):
    payload = json.dumps(
        {"models": [{"model": name, "name": name} for name in model_names]}
    ).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/tags":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass  # keep bats output quiet; server behavior is what's under test

    return Handler


def main():
    if len(sys.argv) < 2:
        print("usage: mock_ollama_server.py PORT [MODEL_NAME ...]", file=sys.stderr)
        raise SystemExit(2)
    port = int(sys.argv[1])
    model_names = sys.argv[2:]
    handler = make_handler(model_names)
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    print("READY", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
