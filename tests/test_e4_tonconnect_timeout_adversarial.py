from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_tonconnect_verification_timeout_and_late_loser_isolation():
    subprocess.run(['node', str(ROOT / 'tests/e4_tonconnect_timeout_adversarial.cjs'),
                    str(ROOT / 'relay/webapp.html')], cwd=ROOT, check=True,
                   capture_output=True, text=True)
