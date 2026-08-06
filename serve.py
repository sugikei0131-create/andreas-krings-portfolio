#!/usr/bin/env python3
"""Stable static file server for the portfolio project.

Logs go to a file (server.log), NEVER to the session stdout/stderr pipe.
If the launching session dies and nobody drains the pipe, the 16KB pipe
buffer fills up and every log write fails, crashing each handler thread
mid-response ("accepts connections but replies nothing"). Writing to a
file makes that failure mode impossible.
"""
import functools
import http.server
import os
import socketserver

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
HOST = "127.0.0.1"
LOG = os.path.join(ROOT, "server.log")


class FileLogHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        with open(LOG, "a") as f:
            f.write(
                "%s - - [%s] %s\n"
                % (self.address_string(), self.log_date_time_string(), fmt % args)
            )


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    server = ThreadingServer((HOST, PORT), FileLogHandler)
    with open(LOG, "a") as f:
        f.write("--- serving %s at http://%s:%d/ ---\n" % (ROOT, HOST, PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
