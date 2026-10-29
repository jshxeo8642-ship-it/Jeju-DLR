"""Local-only dashboard server. No external dependencies or network services."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from contracts import load_json
from engine import run_engine


def serve(root, config_path, weather_path, port):
    lock = threading.Lock()
    assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "application/javascript"),
              "/style.css": ("style.css", "text/css")}

    class Handler(BaseHTTPRequestHandler):
        def send_data(self, status, data, content_type="application/json"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in assets:
                filename, mime = assets[path]
                self.send_data(200, (Path(root) / "ui" / filename).read_bytes(), mime)
            elif path == "/api/example":
                self.send_data(200, {"constant_data": load_json(config_path), "weather_scenarios_N": load_json(weather_path)})
            elif path == "/api/health":
                self.send_data(200, {"status": "ok"})
            else:
                self.send_data(404, {"error": "경로를 찾을 수 없습니다."})

        def do_POST(self):
            if self.path != "/api/calculate":
                return self.send_data(404, {"error": "경로를 찾을 수 없습니다."})
            # Browser requests are same-origin; reject unsolicited cross-origin jobs.
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return self.send_data(403, {"error": "동일한 로컬 페이지에서 요청하세요."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32 * 1024 * 1024:
                    return self.send_data(413, {"error": "입력 JSON은 최대 32 MB입니다."})
                payload = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                return self.send_data(400, {"error": "올바른 JSON 요청이 필요합니다."})
            if not lock.acquire(blocking=False):
                return self.send_data(409, {"error": "다른 계산이 진행 중입니다. 완료 후 다시 실행하세요."})
            try:
                result = run_engine(payload["constant_data"], payload["weather_scenarios_N"])
                self.send_data(200, result)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError) as error:
                self.send_data(400, {"error": f"입력/계산 오류: {error}"})
            except Exception:
                import traceback
                traceback.print_exc()
                self.send_data(500, {"error": "계산 중 내부 오류가 발생했습니다. 서버 로그를 확인하세요."})
            finally:
                lock.release()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"DLR dashboard: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
