import os, json, sqlite3, qrcode, logging, re, asyncio
from io import BytesIO
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from services.payment_service import PaymentService
from services.polling_service import start_polling_service
from utils.logger import get_logger

# Все переменные читаем ТОЛЬКО из окружения
DB_PATH = os.environ.get('DB_PATH', '/app/exchange.db')
SECRET_KEY = os.environ.get('RELAY_SECRET', 'fallback')
PUBLIC_RELAY = os.environ.get('PUBLIC_RELAY', 'https://obsidian-exchange.org')

app = FastAPI(title="ObsidianExchange Relay", version="2.0")
logger = get_logger(__name__)

@app.on_event("startup")
async def startup():
    start_polling_service()
    logger.info("FastAPI relay started (Docker)")

# --- Статические страницы ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return "ObsidianExchange OK"

@app.get("/webapp", response_class=HTMLResponse)
async def webapp():
    try:
        with open('/app/webapp.html', 'r') as f:
            return f.read()
    except:
        raise HTTPException(status_code=500)

# --- API эндпоинты ---
@app.get("/api/history")
async def api_history(user_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT order_id, rub_amount, currency, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"order_id": r[0], "amount": r[1], "currency": r[2], "status": r[3], "created": r[4]} for r in rows]

@app.get("/api/referral_stats")
async def api_referral(user_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(total_bonus_btc) FROM referrals WHERE referrer_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"referrals": row[0] or 0, "total_bonus_btc": row[1] or 0}

@app.get("/api/order/{order_id}")
async def api_order(order_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT status, paid_btc_tx FROM orders WHERE order_id=?", (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404)
    return {"status": row[0], "txid": row[1]}

# --- Платёжный шлюз (новый формат с токенами) ---
@app.get("/pay/{token}", response_class=HTMLResponse)
async def pay_with_token(token: str, request: Request):
    client_ip = request.client.host
    from utils.security import rate_limiter
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429)

    if token.isdigit():
        return await pay_old(token)

    payment_service = PaymentService()
    session = payment_service.get_session(token)
    if not session:
        raise HTTPException(status_code=404)

    amount = session['amount']
    order_id = session['order_id']
    platega_url = session.get('qr_payload', 'https://obsidian-exchange.org/error')
    banks = payment_service.get_payment_methods(token)

    qr = qrcode.make(platega_url)
    bio = BytesIO(); qr.save(bio, "PNG"); bio.seek(0)
    import base64
    qr_base64 = base64.b64encode(bio.read()).decode()

    bank_buttons = ""
    for bank in banks:
        gateway_url = f"/gateway/{order_id}?bank={bank['code']}"
        bank_buttons += f'<a href="{gateway_url}" class="bank-btn">{bank["name"]}</a>'

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secure Payment #{order_id} | ObsidianExchange</title>
    <style>
        :root {{ --bg: #050507; --card: #0f0f14; --input: #151520; --border: rgba(168,85,247,.18); --purple: #8b5cf6; --text: #f3f3f3; --radius: 22px; }}
        @keyframes matrixRain {{
            0% {{ transform: translateY(-100vh); opacity: 0; }}
            20% {{ opacity: 1; }}
            100% {{ transform: translateY(100vh); opacity: 0; }}
        }}
        @keyframes pulseGlow {{
            0%, 100% {{ box-shadow: 0 0 20px rgba(168,85,247,0.5); }}
            50% {{ box-shadow: 0 0 40px rgba(168,85,247,0.9), 0 0 80px rgba(168,85,247,0.4); }}
        }}
        @keyframes scanLine {{
            0% {{ transform: translateY(-100%); }}
            100% {{ transform: translateY(100%); }}
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: radial-gradient(circle at top, rgba(139,92,246,.25), transparent 45%), linear-gradient(180deg,#050507,#09090f); color: var(--text); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; position: relative; }}
        .container {{ width: 100%; max-width: 420px; background: rgba(10,10,15,.88); backdrop-filter: blur(24px); border: 1px solid var(--border); border-radius: 34px; padding: 30px 20px; box-shadow: 0 0 80px rgba(168,85,247,.18), inset 0 0 0 1px rgba(255,255,255,.03); text-align: center; }}
        h1 {{ font-size: 24px; font-weight: 800; background: linear-gradient(90deg,#fff,#c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }}
        .amount {{ font-size: 28px; font-weight: 700; color: #00ff9d; margin: 15px 0; }}
        .qr {{ margin: 20px auto; border-radius: 15px; padding: 10px; background: rgba(168,85,247,.05); border: 1px solid rgba(168,85,247,.2); display: inline-block; animation: pulseGlow 2s ease-in-out infinite; position: relative; }}
        .qr img {{ border-radius: 10px; }}
        .bank-list {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 20px; }}
        .bank-btn {{ display: block; padding: 14px; border-radius: 18px; background: linear-gradient(180deg, rgba(168,85,247,.18), rgba(168,85,247,.08)); border: 1px solid rgba(168,85,247,.25); color: #fff; font-weight: 600; text-decoration: none; transition: all .3s; backdrop-filter: blur(5px); position: relative; overflow: hidden; }}
        .bank-btn:hover {{ background: linear-gradient(180deg, #7c3aed, #a855f7); box-shadow: 0 0 25px rgba(168,85,247,.5); transform: translateY(-2px); }}
        .bank-btn::before {{ content: ""; position: absolute; top: 0; left: -100%; width: 100%; height: 100%; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent); transition: left 0.5s; }}
        .bank-btn:hover::before {{ left: 100%; }}
        .info-text {{ color: #999; font-size: 14px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚫ ObsidianExchange</h1>
        <p>Заказ #{order_id}</p>
        <div class="amount">{amount} RUB</div>
        <p>📲 Отсканируйте QR или выберите банк</p>
        <div class="qr"><img src="data:image/png;base64,{qr_base64}" width="220" alt="QR-код"><div class="scan-overlay"></div></div>
        <div class="bank-list">
            {bank_buttons}
        </div>
        <p class="info-text">Вы будете перенаправлены в приложение банка</p>
    </div>
</body>
</html>"""
    return html

async def pay_old(order_id_str: str):
    order_id = int(order_id_str)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT rub_amount, paid_btc_tx FROM orders WHERE order_id=?", (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404)

    amount, platega_url = row
    if not platega_url:
        platega_url = "https://obsidian-exchange.org/error"

    qr = qrcode.make(platega_url)
    bio = BytesIO(); qr.save(bio, "PNG"); bio.seek(0)
    import base64
    qr_base64 = base64.b64encode(bio.read()).decode()

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Оплата заказа #{order_id} | ObsidianExchange</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #e0e0e0; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .container {{ text-align: center; background: #141414; padding: 40px; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); max-width: 400px; width: 90%; }}
        h1 {{ color: #2a7d2a; font-size: 24px; }}
        .amount {{ font-size: 28px; font-weight: 700; color: #2a7d2a; margin: 20px 0; }}
        .qr {{ margin: 20px auto; }}
        .qr img {{ border-radius: 15px; }}
        .btn {{ display: inline-block; padding: 14px 30px; background: #2a7d2a; color: #fff; text-decoration: none; border-radius: 10px; font-size: 18px; margin-top: 20px; }}
        .btn:hover {{ background: #236923; }}
        p {{ color: #999; font-size: 14px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚫ ObsidianExchange</h1>
        <p>Заказ #{order_id}</p>
        <div class="amount">{amount} RUB</div>
        <p>📲 Отсканируйте QR-код в приложении вашего банка для оплаты через СБП</p>
        <div class="qr"><img src="data:image/png;base64,{qr_base64}" width="250" alt="QR-код оплаты"></div>
        <a class="btn" href="{platega_url}" target="_blank">Открыть в приложении банка</a>
        <p>После оплаты нажмите «Я оплатил» в боте</p>
    </div>
</body>
</html>"""
    return html

@app.get("/gateway/{order_id}")
async def gateway(order_id: str, bank: str = "sber"):
    deep_links = {
        "sber": "https://sberbank.ru/pay/sbp?qrcode=...",
        "tbank": "https://www.tbank.ru/pay/qr/...",
        "alfa": "https://alfa.link/a/qr/...",
        "vtb": "https://vtb.ru/pay/sbp?...",
    }
    redirect_url = deep_links.get(bank, "https://obsidian-exchange.org/error")
    return RedirectResponse(url=redirect_url)

@app.post("/platega/webhook")
async def platega_webhook(request: Request):
    from services.webhook_service import WebhookService
    data = await request.json()
    ws = WebhookService()
    success, message = ws.handle_platega_webhook(data)
    if success:
        return JSONResponse(status_code=200, content={})
    return JSONResponse(status_code=400, content={"error": message})

@app.post("/payment/callback")
async def payment_callback(request: Request):
    from urllib.parse import parse_qs
    body = (await request.body()).decode()
    data = parse_qs(body)
    order_id = data.get('order_id', [None])[0]
    key = data.get('key', [''])[0]
    if key != SECRET_KEY:
        raise HTTPException(status_code=403)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
    conn.commit()
    conn.close()
    return JSONResponse(status_code=200, content={})
