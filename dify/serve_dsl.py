#!/usr/bin/env python3
"""带 CORS 头的静态文件服务，供浏览器从 Dify 页面 fetch DSL 文件。"""
import http.server
import socketserver
import os

PORT = 8200
DIR = os.path.dirname(os.path.abspath(__file__))


class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


if __name__ == "__main__":
    os.chdir(DIR)
    with socketserver.TCPServer(("0.0.0.0", PORT), CORSHandler) as httpd:
        print(f"serving {DIR} on 0.0.0.0:{PORT} with CORS")
        httpd.serve_forever()
