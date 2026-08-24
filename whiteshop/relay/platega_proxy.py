import http.server
import socketserver
import json
import asyncio
import os
from uuid import uuid4
from plategaio import PlategaAsyncClient, CreateTransactionRequest, PaymentDetails

PORT = 5003

class PlategaProxy(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/create':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            req = json.loads(post_data.decode())
            amount = req.get('amount')
            order_id = req.get('order_id')

            merchant_id = os.getenv('PLATEGA_MERCHANT_ID')
            secret = os.getenv('PLATEGA_SECRET')

            if not merchant_id or not secret:
                payment_url = "https://platega.io/pay"
            else:
                # Получаем реальную платёжную ссылку через SDK
                payment_url = asyncio.run(self.create_payment(merchant_id, secret, amount, order_id))

            response = {"payment_url": payment_url}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    async def create_payment(self, merchant_id, secret, amount, order_id):
        try:
            async with PlategaAsyncClient(
                merchant_id=merchant_id,
                secret=secret,
            ) as client:
                tx_request = CreateTransactionRequest(
                    payment_method=2,  # 2 = СБП
                    id=str(uuid4()),
                    payment_details=PaymentDetails(amount=float(amount), currency="RUB"),
                    description=f"Order #{order_id}",
                    return_url="https://obsidian-exchange.org/success",
                    failed_url="https://obsidian-exchange.org/fail",
                )
                tx_response = await client.create_transaction(tx_request)
                return tx_response.redirect
        except Exception as e:
            print(f"Platega error: {e}")
            return "https://platega.io/pay"

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), PlategaProxy) as httpd:
        print(f"Platega proxy running on port {PORT}")
        httpd.serve_forever()
