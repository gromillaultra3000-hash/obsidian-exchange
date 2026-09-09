from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_tonconnect_explicit_intent_nonce_attribution():
    subprocess.run(['node', str(ROOT / 'tests/e4_tonconnect_intent_adversarial.cjs'),
                    str(ROOT / 'relay/webapp.html')], cwd=ROOT, check=True,
                   capture_output=True, text=True)
