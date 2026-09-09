from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_payload_wait_deadline_and_late_response_isolation():
    subprocess.run(['node', str(ROOT / 'docs/e4-tonconnect-payload-wait/acceptance.cjs')],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=20)
