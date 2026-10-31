import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

class MemoryHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent), **kwargs)

    def do_GET(self):
        if self.path == '/api/memories':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            memories = []
            out_dir = Path(__file__).parent.parent / 'out'
            for mem_file in out_dir.rglob('memory.jsonl'):
                with open(mem_file, encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            memories.append(json.loads(line))

            self.wfile.write(json.dumps(memories, ensure_ascii=False).encode())
        else:
            super().do_GET()

if __name__ == '__main__':
    server = HTTPServer(('localhost', 8737), MemoryHandler)
    print('Web App 运行在 http://localhost:8737')
    server.serve_forever()