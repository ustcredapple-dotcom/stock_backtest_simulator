from __future__ import annotations

import json
import os
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
DATA_DIR = ROOT / "data" / "datasets"


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


def safe_dataset_id(value: str) -> str:
    safe = []
    for char in value.strip():
        if char.isalnum() or char in ("-", "_", "."):
            safe.append(char)
        else:
            safe.append("_")
    result = "".join(safe).strip("._")
    return result or "dataset"


def dataset_path(dataset_id: str) -> Path:
    return DATA_DIR / f"{safe_dataset_id(dataset_id)}.json"


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def list_saved_datasets() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    datasets: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as file:
                datasets.append(json.load(file))
        except (OSError, json.JSONDecodeError) as error:
            print(f"Skip broken dataset {path}: {error}")
    return datasets


def write_dataset(dataset: dict) -> Path:
    dataset_id = str(dataset.get("id") or "").strip()
    if not dataset_id:
        symbol = str(dataset.get("symbol") or "UNKNOWN").strip()
        interval = str(dataset.get("interval") or "1d").strip()
        dataset_id = f"{symbol}__{interval}"
        dataset["id"] = dataset_id
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = dataset_path(dataset_id)
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(dataset, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)
    return path


class StockHandler(SimpleHTTPRequestHandler):
    server_version = "StockSimulator/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
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
        if parsed.path == "/api/datasets":
            self.send_json({"datasets": list_saved_datasets(), "dataDir": str(DATA_DIR)})
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path in ("", "/"):
            self.path = "/" + quote(HTML_NAME)
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dataset":
            try:
                dataset = read_json_body(self)
                path = write_dataset(dataset)
            except (OSError, json.JSONDecodeError, TypeError) as error:
                self.send_json({"error": str(error)}, status=400)
                return
            self.send_json({"ok": True, "path": str(path)})
            return
        self.send_json({"error": "Not found."}, status=404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dataset":
            params = parse_qs(parsed.query)
            dataset_id = (params.get("id") or [""])[0].strip()
            if not dataset_id:
                self.send_json({"error": "Missing dataset id."}, status=400)
                return
            path = dataset_path(dataset_id)
            if path.exists():
                path.unlink()
            self.send_json({"ok": True})
            return
        self.send_json({"error": "Not found."}, status=404)

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
    print(f"Data folder: {DATA_DIR}")
    print("Keep this window open while downloading market data.")
    if os.environ.get("STOCK_SIMULATOR_NO_BROWSER") != "1":
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
