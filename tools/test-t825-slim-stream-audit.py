import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("audit", Path(__file__).with_name("audit-t825-slim-stream.py"))
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)

class SlimStreamAudit(unittest.TestCase):
    def test_pinned_source_exposes_all_ignored_transaction_sites(self):
        source = Path("/var/tmp/polly-kernel73/linux/drivers/slimbus/stream.c").read_text()
        result = audit.audit(source)
        self.assertEqual(result["status"], "ignored_slimbus_transaction_returns")
        self.assertEqual({f["id"] for f in result["findings"] if f["count"]}, set(audit.PATTERNS))
        self.assertTrue(all(not f["return_checked"] for f in result["findings"] if f["count"]))
        self.assertFalse(result["production_fix_accepted"])

    def test_unrelated_source_is_not_accepted(self):
        result = audit.audit("int main(void) { return 0; }\n")
        self.assertEqual(result["status"], "no_matches")

if __name__ == "__main__":
    unittest.main()
