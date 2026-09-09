from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_buy_offering_validation_and_route_signature_landmines():
    subprocess.run(['node', str(ROOT / 'tests/e4_buy_refresh_adversarial.cjs'),
                    str(ROOT / 'relay/webapp.html')], cwd=ROOT, check=True,
                   capture_output=True, text=True)
