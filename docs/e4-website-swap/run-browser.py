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
data = dict(web_user={'email':'synthetic@example.invalid','csrf_token':'synthetic','totp_enabled':False},request={'url':{'path':'/dashboard/swap'}},bot_username='synthetic',swap_coins=['BTC','LTC'],swap_currencies=['BTC','LTC'],form={'coin_from':'BTC','coin_to':'LTC','amount':.1,'address':'synthetic-address'},prefill=None,error=None,network_from='BTC',network_to='LTC',review={'token':'synthetic-review','ttl':120,'quote':{'estimated_receive':'2','rate':'20','withdraw_fee':None}})
files=['dashboard_swap.html','dashboard_swap_review.html','dashboard_base.html','base.html']
bundle={'pages':{},'assets':{},'inputHashes':{str(TEMPLATES/name):hashlib.sha256((TEMPLATES/name).read_bytes()).hexdigest() for name in files}}
for theme in ['legacy','v5']:
    for kind,name in [('form','dashboard_swap.html'),('review','dashboard_swap_review.html')]:
        bundle['pages'][theme+'-'+kind]=env.get_template(name).render(**data,v5=theme=='v5',active='swap')
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
    shutil.copyfile(ROOT / 'tests/e4_website_swap_browser.cjs', root / 'tests/e4_review_browser.cjs')
    (root / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    source = root / 'fixtures.json'
    source.write_text(json.dumps(bundle))
    raise SystemExit(launcher.run(source, output, root))
