from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "cex-readonly-operations.md"


class CexReadonlyOperationsContractTests(unittest.TestCase):
    def test_readonly_operations_contract_keeps_safety_and_slo_gates(self):
        text = CONTRACT.read_text(encoding="utf-8")

        required = (
            "read=true",
            "trade=false",
            "withdraw=false",
            "internal_transfer=false",
            "<=15m",
            "an error must never be rendered as a zero balance",
            "Cross-owner disclosure | exactly 0",
            "Forbidden capability observed | exactly 0",
            "never API keys, secrets, vault references",
            "two consecutive healthy five-minute windows",
            "Do not call order, transfer or withdrawal endpoints",
            "explicit owner-approved production gate",
        )
        for invariant in required:
            self.assertIn(invariant, text)

    def test_runbook_covers_every_frozen_connector_failure_class(self):
        text = CONTRACT.read_text(encoding="utf-8")

        for section in (
            "### Permission drift or forbidden capability",
            "### Provider outage, timeout or rate limit",
            "### Authentication failure",
            "### Owner-boundary or privacy breach",
            "### Disconnect stuck in `REVOKING`",
        ):
            self.assertIn(section, text)


if __name__ == "__main__":
    unittest.main()
