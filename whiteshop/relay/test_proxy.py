from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"payment_url": "https://platega.io/pay"}).encode())

HTTPServer(("127.0.0.1", 5003), Handler).serve_forever()
