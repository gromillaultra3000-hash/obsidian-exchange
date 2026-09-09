from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_buy_estimate_numeric_freshness_and_tier_landmines():
    subprocess.run(
        ['node', str(ROOT / 'tests/e4_buy_estimate_adversarial.cjs'),
         str(ROOT / 'relay/webapp.html')],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
