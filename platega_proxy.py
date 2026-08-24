import os, requests, json, traceback
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv('/root/whiteshop/bot/.env')

MERCHANT_ID = os.getenv('PLATEGA_MERCHANT_ID')
SECRET_KEY = os.getenv('PLATEGA_SECRET_KEY')

app = Flask(__name__)

@app.route('/platega/invoice', methods=['POST'])
def proxy():
    data = request.json
    # Преобразуем входные данные в формат API v2
    payload = {
        "amount": data.get("amount"),
        "description": data.get("description", f"Order #{data.get('order_id')}"),
        "returnUrl": "https://obsidian-exchange.org/success",
        "failedUrl": "https://obsidian-exchange.org/fail"
    }
    headers = {
        'X-MerchantId': MERCHANT_ID,
        'X-Secret': SECRET_KEY,
        'Content-Type': 'application/json'
    }
    try:
        resp = requests.post('https://app.platega.io/api/v2/transaction/process', json=payload, headers=headers, timeout=15)
        # Прокси возвращает то, что вернул Platega
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003)
