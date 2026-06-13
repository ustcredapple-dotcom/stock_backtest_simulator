from __future__ import annotations

import json
import socket
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
HTML_NAME = "炒股模拟器.html"
HOST = "127.0.0.1"
START_PORT = 8765


def find_port(start: int = START_PORT) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError("No available local port found.")


def yahoo_chart(symbol: str, interval: str, range_value: str) -> bytes:
    path_symbol = quote(symbol.strip(), safe="")
    query = urlencode(
        {
            "range": range_value,
            "interval": interval,
            "events": "div,splits",
            "includeAdjustedClose": "true",
            "includePrePost": "false",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{path_symbol}?{query}"
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=25) as response:
        return response.read()


class StockHandler(SimpleHTTPRequestHandler):
    server_version = "StockSimulator/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "time": time.time()})
            return
        if parsed.path == "/api/yahoo":
            self.handle_yahoo(parsed.query)
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path in ("", "/"):
            self.path = "/" + quote(HTML_NAME)
        super().do_GET()

    def handle_yahoo(self, query: str) -> None:
        params = parse_qs(query)
        symbol = (params.get("symbol") or [""])[0].strip()
        interval = (params.get("interval") or ["1d"])[0].strip()
        range_value = (params.get("range") or ["1y"])[0].strip()
        if not symbol:
            self.send_json({"error": "Missing symbol."}, status=400)
            return
        try:
            payload = yahoo_chart(symbol, interval, range_value)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            self.send_json({"error": f"Yahoo HTTP {error.code}", "detail": detail}, status=502)
            return
        except (URLError, TimeoutError, OSError) as error:
            self.send_json({"error": str(error)}, status=502)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), format % args))


def main() -> None:
    port = find_port()
    server = ThreadingHTTPServer((HOST, port), StockHandler)
    url = f"http://{HOST}:{port}/"
    print("Stock simulator server is running.")
    print(url)
    print("Keep this window open while downloading market data.")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
