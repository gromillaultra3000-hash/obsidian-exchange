#!/usr/bin/env python3
"""Статический контракт-тест маршрутов (без запуска приложения, только stdlib).

Ловит два класса регрессий:
  1. Критичный эндпоинт удалён/переименован в relay-fastapi/main.py.
  2. Mini App (relay/webapp.html) дёргает fetch() на несуществующий роут
     (ровно тот баг-класс, из-за которого заявка «создавалась» и зависала).
Быстрый, детерминированный, не требует зависимостей и секретов — годится для CI.
"""
import re
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "relay-fastapi", "main.py")
WEBAPP = os.path.join(ROOT, "relay", "webapp.html")

# Роуты, без которых продукт сломан — должны существовать всегда.
CRITICAL = [
    ("POST", "/api/create_order"),
    ("GET",  "/api/order/{order_id}"),
    ("GET",  "/api/history"),
    ("GET",  "/api/stats/public"),
    ("GET",  "/api/rates"),
    ("GET",  "/webapp"),
    ("POST", "/montera/webhook"),
    ("POST", "/brabus/webhook"),
    ("POST", "/stormtrade/webhook"),
    ("POST", "/xpay/webhook"),
]

route_re = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', re.I)


def extract_routes(path):
    """{(METHOD, PATH)} из декораторов FastAPI."""
    routes = set()
    with open(path, encoding="utf-8") as f:
        for m in route_re.finditer(f.read()):
            routes.add((m.group(1).upper(), m.group(2)))
    return routes


def route_to_regex(p):
    """'/api/order/{order_id}' -> ^/api/order/[^/]+$"""
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(p).replace(r"\{", "{").replace(r"\}", "}")) + "$")


def extract_webapp_fetches(path):
    """Same-origin пути из fetch(...) в webapp.html (без query/хоста)."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    paths = set()
    for m in re.finditer(r"""fetch\(\s*[`'"]([^`'"]+)[`'"]""", html):
        raw = m.group(1)
        if not raw.startswith("/"):
            continue  # внешние (coingecko и т.п.) не проверяем
        raw = raw.split("?", 1)[0]                    # убрать query
        raw = re.sub(r"\$\{[^}]+\}", "X", raw)         # ${var} -> X
        paths.add(raw)
    return paths


def main():
    routes = extract_routes(MAIN)
    paths_only = {p for _, p in routes}
    regexes = [route_to_regex(p) for p in paths_only]
    errors = []

    # 1) Критичные роуты на месте
    for method, p in CRITICAL:
        if (method, p) not in routes:
            errors.append(f"КРИТИЧНЫЙ роут отсутствует: {method} {p}")

    # 2) Каждый fetch из webapp ведёт на существующий роут
    for fp in sorted(extract_webapp_fetches(WEBAPP)):
        if not any(rx.match(fp) for rx in regexes):
            errors.append(f"webapp.html fetch('{fp}') не соответствует ни одному роуту main.py")

    if errors:
        print("❌ Контракт маршрутов нарушен:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print(f"✅ OK: {len(routes)} роутов, все критичные на месте, все fetch() webapp сопоставлены.")


if __name__ == "__main__":
    main()
