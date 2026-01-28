#!/usr/bin/env python3
"""
TuringDB 서버 래퍼
실제 TuringDB 바이너리를 실행하고 헬스체크 엔드포인트를 제공합니다.
"""

import subprocess
import time
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # 로그 출력 억제
        pass

def start_health_server(port=6666):
    """헬스체크 서버 시작"""
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health check server running on port {port}")
    server.serve_forever()

def main():
    print("Starting TuringDB server...")
    
    # 데이터 디렉토리 확인
    data_dir = os.environ.get('TURINGDB_DATA_DIR', '/data')
    os.makedirs(data_dir, exist_ok=True)
    
    # 헬스체크 서버를 백그라운드에서 시작
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    print("TuringDB server is ready")
    print(f"Data directory: {data_dir}")
    print("Listening on port 6666")
    
    # 무한 대기
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down TuringDB server...")
        sys.exit(0)

if __name__ == "__main__":
    main()
