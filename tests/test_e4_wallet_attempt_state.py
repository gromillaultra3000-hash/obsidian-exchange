"""Same-tab unresolved handoff regressions with inert SDK/network boundaries."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_wallet_attempt_state_and_storage_faults():
    node = shutil.which('node')
    assert node, 'Node required for exact JavaScript acceptance'
    source = os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html'))
    result = subprocess.run(
        [node, str(ROOT / 'tests/e4_wallet_attempt_state.cjs'), source],
        cwd=ROOT, capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WALLET_ATTEMPT_STATE_PASS 18' in result.stdout
