from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
import sqlite3, qrcode, base64, os
from pathlib import Path
from io import BytesIO

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

async def pay_page(token: str, request: Request):
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT order_id, rub_amount, paid_btc_tx FROM orders WHERE paid_btc_tx LIKE ? ORDER BY order_id DESC LIMIT 1", (f'%{token}%',))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    order_id, amount, platega_url = row

    qr = qrcode.make(platega_url)
    bio = BytesIO()
    qr.save(bio, "PNG")
    qr_base64 = base64.b64encode(bio.getvalue()).decode()

    template_path = Path(__file__).resolve().parents[1] / "relay" / "pay_template.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="Template not found")
    with template_path.open("r") as f:
        html = f.read()

    html = html.replace("{{order_id}}", str(order_id))
    html = html.replace("{{amount}}", f"{amount:.2f}")
    html = html.replace("{{qr_base64}}", qr_base64)
    html = html.replace("{{payment_url}}", platega_url)

    return HTMLResponse(content=html)
