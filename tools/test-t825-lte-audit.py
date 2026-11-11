#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit", ROOT / "tools/audit-t825-lte.py")
audit = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(audit)


class LteAudit(unittest.TestCase):
    def test_production_boundary_is_closed(self):
        result = audit.audit(
            "/tmp/t825-config",
            str(audit.DEFAULT_ACTIVE),
            str(audit.DEFAULT_DIAG),
        )
        self.assertEqual(result["production"]["mss_status"], "disabled")
        self.assertEqual(result["diagnostic"]["mss_status"], "okay")
        self.assertEqual(result["production"]["config"]["GNSS"], "disabled")
        self.assertEqual(result["production"]["config"]["WWAN"], "disabled")
        self.assertEqual(result["decision"], "transport-only-diagnostic; do-not-enable-production-LTE")

    def test_config_parser(self):
        config = "# CONFIG_GNSS is not set\nCONFIG_QCOM_IPA=m\n"
        self.assertEqual(audit.config_state(config, "GNSS"), "disabled")
        self.assertEqual(audit.config_state(config, "QCOM_IPA"), "m")

    def test_ipa_nodes_in_real_dtc_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'fixture.dts'
            for node in ['ipa@1e40000', 'ipa: ipa@1e40000', 'qcom,ipa@1e40000', 'ipa']:
                for status in ['okay', 'disabled']:
                    with self.subTest(node=node, status=status):
                        source.write_text('/dts-v1/; / { soc { ' + node + ' { status = "' + status + '"; }; }; };')
                        self.assertTrue(audit.ipa_node_present(audit.dts_text(source)))
            source.write_text('/dts-v1/; / { /* ipa@1 { }; */ soc { qcom,rmnet-ipa { }; }; };')
            self.assertFalse(audit.ipa_node_present(audit.dts_text(source)))


if __name__ == "__main__":
    unittest.main()
