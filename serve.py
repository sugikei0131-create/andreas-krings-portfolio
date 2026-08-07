#!/usr/bin/env python3
"""Stable local server for the Andreas Krings portfolio + dashboard API.

Serves the static site AND three JSON endpoints used by dashboard.html:

    POST /api/status   git / connection status
    POST /api/sync     apply dashboard state JSON to the site files
    POST /api/publish  commit + push the updated files to GitHub

Together they let a non-technical user run the whole "edit → update the
site → publish" loop from the dashboard alone (no terminal, no AI).

Logs go to a file (server.log), NEVER to the session stdout/stderr pipe.
If the launching session dies and nobody drains the pipe, the 16KB pipe
buffer fills up and every log write fails, crashing each handler thread
mid-response ("accepts connections but replies nothing"). Writing to a
file makes that failure mode impossible.
"""
import http.server
import json
import os
import socketserver
import subprocess
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
HOST = "0.0.0.0"  # accessible from any device on the same WiFi
LOG = os.path.join(ROOT, "server.log")


def log(msg):
    with open(LOG, "a") as f:
        f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def git(args, timeout=180):
    return subprocess.run(
        ["git", "-C", ROOT] + args, capture_output=True, text=True, timeout=timeout
    )


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        log("%s %s" % (self.address_string(), fmt % args))

    # ---------- helpers ----------

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        return self.rfile.read(n) if n else b""

    # ---------- endpoints ----------

    def api_status(self):
        st = git(["status", "--porcelain"])
        branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
        commit = git(["rev-parse", "--short", "HEAD"])
        self.send_json({
            "ok": True,
            "server": "andreas-krings local server",
            "git": {
                "branch": (branch.stdout or "?").strip(),
                "commit": (commit.stdout or "?").strip(),
                "dirty": bool(st.stdout.strip()),
                "changes": (st.stdout or "").strip()[:600],
            },
        })

    def api_sync(self, raw):
        import sync_from_dashboard as sync
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return self.send_json({"ok": False, "error": "invalid JSON body"}, 400)
        try:
            result = sync.apply_data(data, dry_run=False, write_upload_files=True)
        except Exception as e:  # unexpected — report instead of crashing
            log("api_sync ERROR: %r" % e)
            return self.send_json({"ok": False, "error": "sync failed: %s" % e}, 500)
        self.send_json(result)

    def api_publish(self):
        r = git(["add", "-A"])
        if r.returncode:
            return self.send_json({"ok": False, "error": "git add failed: " + (r.stderr or r.stdout)[-500:]})
        staged = git(["diff", "--cached", "--quiet"])
        if staged.returncode == 0:
            return self.send_json({"ok": True, "nothing": True,
                                   "message": "No changes to publish — the site already matches."})
        msg = "Site update via dashboard — " + time.strftime("%Y-%m-%d %H:%M")
        c = git(["commit", "-m", msg])
        if c.returncode:
            return self.send_json({"ok": False, "error": "commit failed: " + (c.stderr or c.stdout)[-500:]})
        commit_short = git(["rev-parse", "--short", "HEAD"]).stdout.strip()
        p = git(["push", "origin", "HEAD"], timeout=300)
        if p.returncode:
            log("push failed: %s" % ((p.stderr or p.stdout)[-500:]))
        self.send_json({
            "ok": True,
            "nothing": False,
            "commit": commit_short,
            "message": msg,
            "pushed": p.returncode == 0,
            "push": "ok" if p.returncode == 0 else ("failed: " + (p.stderr or p.stdout)[-300:]),
        })

    # ---------- dispatch ----------

    def do_POST(self):
        try:
            raw = self.read_body()
            if self.path == "/api/status":
                return self.api_status()
            if self.path == "/api/sync":
                return self.api_sync(raw)
            if self.path == "/api/publish":
                return self.api_publish()
            self.send_json({"ok": False, "error": "unknown endpoint"}, 404)
        except Exception as e:
            log("API ERROR %s: %r" % (self.path, e))
            try:
                self.send_json({"ok": False, "error": "server error: %s" % e}, 500)
            except Exception:
                pass


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    server = ThreadingServer((HOST, PORT), Handler)
    with open(LOG, "a") as f:
        f.write("--- serving %s at http://%s:%d/ (API: /api/status /api/sync /api/publish) ---\n"
                % (ROOT, HOST, PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
