#!/usr/bin/env python3
from __future__ import annotations
import argparse, http.server, socketserver, sys, threading, urllib.request
from functools import partial
from pathlib import Path

class Server(socketserver.TCPServer): allow_reuse_address = True

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("app_dir", type=Path); p.add_argument("--port", type=int, default=0); p.add_argument("--smoke-test", action="store_true"); a = p.parse_args()
    root = a.app_dir.resolve()
    if not (root / "index.html").is_file(): print("index.html not found", file=sys.stderr); return 2
    with Server(("127.0.0.1", a.port), partial(http.server.SimpleHTTPRequestHandler, directory=str(root))) as server:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        if a.smoke_test:
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with urllib.request.urlopen(url, timeout=5) as response: body, status = response.read(4096).lower(), response.status
                ok = status == 200 and b"<html" in body; print(f"{url} status={status} html={ok}"); return 0 if ok else 1
            finally: server.shutdown()
        print(url, flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: return 0
    return 0

if __name__ == "__main__": sys.exit(main())
