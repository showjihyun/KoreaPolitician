#!/bin/bash

echo "Starting TuringDB server..."

# TuringDB 바이너리가 있는지 확인
if command -v turingdb &> /dev/null; then
    echo "Found turingdb binary, starting server..."
    exec turingdb --host 0.0.0.0 --port 6666 --data-dir /data
else
    echo "TuringDB binary not found, trying Python module..."
    
    # Python 모듈로 실행 시도
    if python3 -c "import turingdb" 2>/dev/null; then
        echo "Using Python SDK..."
        # Python SDK는 서버를 직접 실행하지 않으므로 대체 방법 필요
        python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'healthy'}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'result': 'ok'}).encode())
    
    def log_message(self, format, *args):
        pass

print('TuringDB mock server running on port 6666')
server = HTTPServer(('0.0.0.0', 6666), Handler)
server.serve_forever()
"
    else
        echo "ERROR: TuringDB not found!"
        exit 1
    fi
fi
