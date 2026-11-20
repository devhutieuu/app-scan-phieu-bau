"""Server tĩnh cho bản mẫu, luôn gửi kèm 'không lưu bộ nhớ đệm' để trình duyệt tải bản mới nhất.
Chạy: python3 tools/serve_nocache.py 8765 docs/ballot-scan/html-design"""
import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


port, root = int(sys.argv[1]), sys.argv[2]
ThreadingHTTPServer(("", port), functools.partial(NoCache, directory=root)).serve_forever()
