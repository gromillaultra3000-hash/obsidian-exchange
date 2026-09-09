"""Use the existing non-root/private-network browser supervisor unchanged."""
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
with tempfile.TemporaryDirectory(prefix='e4-sell-estimate-harness-') as temporary:
    root = Path(temporary)
    (root / 'tests').mkdir()
    shutil.copyfile(ROOT / 'tests/e4_sell_estimate_browser.cjs', root / 'tests/e4_review_browser.cjs')
    (root / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    raise SystemExit(launcher.run(Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT / 'relay/webapp.html', output, root))
