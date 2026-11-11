#!/usr/bin/env python3
"""Check the detached kexec-proof launcher without touching a device."""
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools/t825-kexec-proof-cycle.sh"


class KexecProofLauncher(unittest.TestCase):
    def test_disabled_launcher_fails_before_transport_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(SCRIPT), str(Path(tmp) / "missing"), str(Path(tmp) / "report")],
                env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED_PREENTRY_RECOVERY", result.stderr)

    def test_launcher_is_bounded_and_never_flashes(self):
        source = SCRIPT.read_text()
        self.assertIn("setsid env", source)
        self.assertIn("T825_KEXEC_PROOF_START_WAIT_SECONDS", source)
        self.assertIn("fastboot -s \"$serial\" reboot", source)
        self.assertNotIn("fastboot flash", source)
        self.assertNotIn("heimdall flash", source)


if __name__ == "__main__":
    unittest.main()
