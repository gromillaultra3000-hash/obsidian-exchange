from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_sdk_wait_quarantine_and_late_callback_isolation():
    subprocess.run(['node', str(ROOT / 'docs/e4-tonconnect-sdk-wait/acceptance.cjs')],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=20)
