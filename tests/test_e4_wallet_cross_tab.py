"""Cross-tab wallet handoff exclusion with deterministic inert boundaries."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_cross_tab_wallet_handoff_and_reconciliation():
    node = shutil.which('node')
    assert node
    result = subprocess.run(
        [node, str(ROOT / 'tests/e4_wallet_cross_tab.cjs'),
         os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html'))],
        cwd=ROOT, capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WALLET_CROSS_TAB_PASS 15' in result.stdout
