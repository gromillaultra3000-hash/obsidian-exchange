"""Reuse the established launcher unchanged with payment-specific public input."""
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('launcher', ROOT / 'scripts/run_e4_review_browser.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=False)
with tempfile.TemporaryDirectory(prefix='e4-payment-harness-') as temporary:
    root = Path(temporary)
    (root / 'tests').mkdir()
    shutil.copyfile(ROOT / 'tests/e4_payment_status_browser.cjs', root / 'tests/e4_review_browser.cjs')
    (root / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    raise SystemExit(launcher.run(Path(__file__).parent / 'acceptance-pages.json', output, root))
