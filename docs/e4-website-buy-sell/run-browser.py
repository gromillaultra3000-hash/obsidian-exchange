"""Render synthetic site fixtures; reuse verified network-isolated Chrome supervisor."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / 'relay-fastapi/templates'
spec = importlib.util.spec_from_file_location('launcher', ROOT / 'scripts/run_e4_review_browser.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(['html']))
offers = [{'code': 'TON', 'label': 'Toncoin', 'rate': 200, 'networks': [{'code': 'MAINNET', 'label': 'TON mainnet'}, {'code': 'ALT', 'label': 'Synthetic alternate'}], 'tag_name': 'memo', 'tag_kind': 'text', 'tag_sep': '#'}]
ways = [{'code': 'sbp', 'label': 'СБП', 'details_label': 'Телефон для выплаты по СБП', 'needs_bank': True, 'needs_name': True}, {'code': 'card', 'label': 'Банковская карта', 'details_label': 'Номер карты', 'needs_bank': False, 'needs_name': False}]
data = dict(web_user={'email': 'synthetic@example.invalid', 'csrf_token': 'synthetic-csrf-only', 'totp_enabled': False}, request={'url': {'path': '/dashboard'}}, offered_currencies=['TON'], bot_username='synthetic', offerings=offers, offerings_json=offers, currencies=['TON'], commission_tiers=[{'to_rub': None, 'percent': 19, 'label': 'synthetic'}], min_amount=1000, max_amount=100000, address_book=[], form=None, prefill=None, error=None, created=None, sell_coins=[{'code': 'TON', 'label': 'Toncoin (TON mainnet)', 'rate': 170}], sell_js=json.dumps({'TON': {'rate': 170, 'market': 200, 'min': 1, 'manual': False, 'fee_percent': 15, 'network': 'TON'}}), payout_ways=ways, payout_js=json.dumps({w['code']: w for w in ways}), payout_banks=[{'code': 'fixture-bank', 'label': 'Синтетический банк'}], sell_commission='15%', sell_currencies=['TON'])
files = ['dashboard_exchange.html', 'dashboard_sell.html', 'dashboard_action_review.html', 'dashboard_base.html', 'base.html']
bundle = {'pages': {}, 'assets': {}, 'inputHashes': {str(TEMPLATES / name): hashlib.sha256((TEMPLATES / name).read_bytes()).hexdigest() for name in files}}
for theme in ['legacy', 'v5']:
    for kind, name in [('buy', 'dashboard_exchange.html'), ('sell', 'dashboard_sell.html')]:
        bundle['pages'][theme + '-' + kind] = env.get_template(name).render(**data, v5=theme == 'v5', active='exchange' if kind == 'buy' else 'sell')
    single = dict(data, payout_ways=ways[:1], payout_js=json.dumps({'sbp': ways[0]}))
    bundle['pages'][theme + '-sell-single'] = env.get_template('dashboard_sell.html').render(**single, v5=theme == 'v5', active='sell')
for name in ['css/style.css', 'css/v5.css', 'js/main.js', 'js/ambient.js', 'js/lucide-0.468.0.min.js', 'js/v5.js']:
    p = ROOT / 'relay-fastapi/static' / name
    bundle['assets']['/static/' + name] = p.read_text()
    bundle['inputHashes'][str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
for path in [Path(__file__), ROOT / 'scripts/run_e4_review_browser.py']:
    bundle['inputHashes'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=False)
with tempfile.TemporaryDirectory(prefix='e4-site-review-harness-') as temporary:
    root = Path(temporary)
    (root / 'tests').mkdir()
    shutil.copyfile(ROOT / 'tests/e4_website_buy_sell_browser.cjs', root / 'tests/e4_review_browser.cjs')
    (root / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    source = root / 'fixtures.json'
    source.write_text(json.dumps(bundle))
    raise SystemExit(launcher.run(source, output, root))
