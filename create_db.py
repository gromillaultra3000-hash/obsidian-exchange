import sqlite3

conn = sqlite3.connect('exchange.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    exchanges INTEGER DEFAULT 0,
    total_rub REAL DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    currency TEXT,
    rub_amount REAL,
    crypto_amount REAL,
    crypto_address TEXT,
    payment_id TEXT,
    qr_payload TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)''')

conn.commit()
conn.close()
print("Новая база exchange.db успешно создана!")
