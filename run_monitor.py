from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import json
import traceback
import time
import threading
from dashboard import build_stats, HTML, HOST, PORT, LOG_DIR

# Cache statistics by period so the 15-second browser refresh does not rescan
# every log file on each request. Cache lifetime is deliberately short.
CACHE_SECONDS = 60
_stats_cache = {}
_cache_lock = threading.Lock()
_build_lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                print("Browser closed the page connection.")
        elif u.path == "/api/stats":
            period = parse_qs(u.query).get("period", ["today"])[0]
            if period not in ("today", "yesterday", "7", "30", "all"):
                period = "today"
            started = time.time()
            try:
                # Use a recent result immediately when available.
                now = time.time()
                with _cache_lock:
                    cached = _stats_cache.get(period)
                if cached and (now - cached[0]) < CACHE_SECONDS:
                    body = cached[1]
                    print("/api/stats period=%s served from cache; age=%.1fs; response=%d bytes" %
                          (period, now - cached[0], len(body)))
                else:
                    # Avoid two browser requests doing the same expensive scan at once.
                    with _build_lock:
                        now = time.time()
                        with _cache_lock:
                            cached = _stats_cache.get(period)
                        if cached and (now - cached[0]) < CACHE_SECONDS:
                            body = cached[1]
                            print("/api/stats period=%s served from cache after waiting; age=%.1fs" %
                                  (period, now - cached[0]))
                        else:
                            result = build_stats(period)
                            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                            finished = time.time()
                            with _cache_lock:
                                _stats_cache[period] = (finished, body)
                            print("/api/stats period=%s recalculated in %.2f seconds; response=%d bytes; cache=%ds" %
                                  (period, finished - started, len(body), CACHE_SECONDS))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    print("Browser disconnected while stats were being sent; calculation itself completed.")
            except Exception as exc:
                print("\nERROR while generating /api/stats:")
                traceback.print_exc()
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    print("Browser disconnected before the diagnostic error response could be sent.")
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

if __name__ == "__main__":
    print("AltairMini BBS Monitor - Mystic Edition (cached server)")
    print("Log folder:", LOG_DIR)
    print("Local browser: http://127.0.0.1:%d/" % PORT)
    print("LAN access: http://IP-OF-MYSTIC-PC:%d/" % PORT)
    print("Server active on LAN; CTRL+C to stop.")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except OSError as exc:
        print("Server startup error:", exc)
        input("Press ENTER to close...")
