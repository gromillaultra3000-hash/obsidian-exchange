from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_sell_estimate_numeric_and_freshness_landmines():
    subprocess.run(['node', str(ROOT / 'tests/e4_sell_estimate_adversarial.cjs'),
                    str(ROOT / 'relay/webapp.html')], cwd=ROOT, check=True,
                   capture_output=True, text=True)
