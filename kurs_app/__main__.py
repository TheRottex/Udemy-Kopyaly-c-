"""Giriş noktası: python -m kurs_app  (yalnızca 127.0.0.1)"""
import argparse
import threading
import webbrowser

import uvicorn

from .server import create_app

HOST = "127.0.0.1"   # bilerek sabit: ağa açılmaz


def main():
    ap = argparse.ArgumentParser(prog="kurs_app")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="Tarayıcıyı otomatik açma")
    a = ap.parse_args()
    url = f"http://{HOST}:{a.port}"
    if not a.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Arayüz: {url}  (durdurmak için Ctrl+C)")
    uvicorn.run(create_app(), host=HOST, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
