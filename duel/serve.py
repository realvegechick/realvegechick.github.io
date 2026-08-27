#!/usr/bin/env python3
"""本地开发用静态服务器：未知路径 fallback 到 index.html，模拟 SPA 部署。"""

from __future__ import annotations

import argparse
import http.server
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler 的命名约定)
        path = self.translate_path(self.path)
        # 路径不存在且不是 API 且没有扩展名 → 走 index.html
        if not os.path.exists(path):
            self.path = "/index.html"
        return super().do_GET()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    os.chdir(ROOT)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), SpaHandler) as srv:
        print(f"本地服务启动：http://127.0.0.1:{args.port}")
        srv.serve_forever()


if __name__ == "__main__":
    main()
