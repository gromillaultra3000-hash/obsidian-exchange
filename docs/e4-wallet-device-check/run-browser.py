"""Serve unchanged static asset bytes through the existing isolated supervisors."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--engine', choices=['chromium', 'webkit'], required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
assets = ROOT / 'preview/e4-wallet-device-check'
bundle = {name: base64.b64encode((assets / name).read_bytes()).decode('ascii')
          for name in ['index.html', 'device-check.js', 'device-check.css', 'manifest.json']}
args.output.mkdir(parents=True, exist_ok=False)
script = 'run_e4_review_browser.py' if args.engine == 'chromium' else 'run_e4_webkit_browser.py'
spec = importlib.util.spec_from_file_location('launcher', ROOT / 'scripts' / script)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
with tempfile.TemporaryDirectory(prefix='e4-device-check-fixture-') as temporary:
    directory = Path(temporary)
    source = directory / 'assets.json'
    source.write_text(json.dumps({'engine': args.engine, 'assets': bundle}, sort_keys=True, separators=(',', ':')))
    runner = ROOT / 'tests/e4_wallet_device_check_browser.cjs'
    if args.engine == 'chromium':
        (directory / 'tests').mkdir()
        shutil.copyfile(runner, directory / 'tests/e4_review_browser.cjs')
        (directory / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
        result = launcher.run(source, args.output.resolve(), directory)
    else:
        result = launcher.run(source, args.output.resolve(), ROOT, Path('/tmp/e4-webkit-runtime/browsers'), runner,
                              Path('/tmp/e4-webkit-runtime/deps/usr/lib/x86_64-linux-gnu'))
    raise SystemExit(result)
