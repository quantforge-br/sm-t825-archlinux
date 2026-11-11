#!/usr/bin/env python3
"""Host-only checks for the bounded nonpersistent kexec runner."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/t825-kexec-cycle.sh"


class KexecCycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text()

    def test_runner_is_nonpersistent_and_has_recovery_path(self):
        self.assertNotIn("fastboot flash", self.source)
        self.assertNotIn("systemctl reboot", self.source)
        self.assertIn("/run/t825-kexec-", self.source)
        self.assertIn("t825.ramdiag", self.source)
        self.assertIn("t825.direct-init", self.source)
        self.assertIn("panic=10", self.source)
        self.assertIn("/sys/kernel/config/usb_gadget/g1/UDC", self.source)
        self.assertIn("fastboot -s \"$serial\" reboot", self.source)
        self.assertIn("RECOVERY_PASS_DIAGNOSTIC_UNOBSERVED", self.source)

    def test_disabled_entry_points_never_access_transport(self):
        for script in (SCRIPT, ROOT / "tools/t825-kexec-proof-cycle.sh"):
            with self.subTest(script=script.name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                commands = root / "commands"
                commands.mkdir()
                touched = root / "transport-used"
                for name in ("ssh", "fastboot", "scp", "setsid"):
                    command = commands / name
                    command.write_text('#!/bin/sh\ntouch "$TEST_TRANSPORT_MARKER"\nexit 91\n')
                    command.chmod(0o755)
                bundle = root / "bundle"
                bundle.mkdir()
                for name in ("vmlinuz", "initramfs", "t825.dtb"):
                    (bundle / name).write_bytes(b"fixture")
                result = subprocess.run(
                    ["bash", str(script), str(bundle), str(root / "report")],
                    env={**os.environ, "PATH": str(commands) + ":/usr/bin:/bin",
                         "T825_RUNNER_SNAPSHOT": "1",
                         "TEST_TRANSPORT_MARKER": str(touched)},
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("BLOCKED_PREENTRY_RECOVERY", result.stderr)
                self.assertFalse(touched.exists())
                self.assertFalse((root / "report").exists())

    def test_fastboot_reset_without_candidate_marker_is_not_boot_proof(self):
        # Model a reset that could have come from the old kernel or a panic:
        # fastboot appears, then the installed kernel returns with a new boot
        # ID. No evidence says the candidate initramfs ever executed.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifacts/roadmap-7.3").mkdir(parents=True)
            bundle = root / "bundle"
            bundle.mkdir()
            for name in ("vmlinuz", "initramfs", "t825.dtb"):
                (bundle / name).write_bytes(b"fixture")
            (bundle / "manifest.txt").write_text("mode=pre-supervisor-proof\n")
            kexec = root / "kexec"
            kexec.write_bytes(b"fixture")
            commands = root / "commands"
            commands.mkdir()
            (commands / "ssh").write_text('''#!/bin/sh
case "$*" in
    *"cat /proc/sys/kernel/random/boot_id"*)
        if [ -f "$TEST_RESET_MARKER" ]; then
            echo 22222222-2222-2222-2222-222222222222
        else
            echo 11111111-1111-1111-1111-111111111111
        fi ;;
    *"uname -a;"*) printf 'fixture kernel\\nfixture cmdline\\n0\\n' ;;
    *"cat /sys/kernel/kexec/loaded"*) echo 1 ;;
esac
exit 0
''')
            (commands / "fastboot").write_text('''#!/bin/sh
case "$*" in
    devices) printf '957be8c9\\tfastboot\\n' ;;
    *reboot*) touch "$TEST_RESET_MARKER" ;;
esac
''')
            for command in commands.iterdir():
                command.chmod(0o755)
            report = root / "report"
            # Exercise the preserved classifier only in this fake-transport
            # fixture. Production has no bypass for its unconditional gate.
            experimental = root / "experimental.sh"
            experimental.write_text(self.source.replace("\nrequire_preentry_recovery\n", "\n", 1))
            result = subprocess.run(
                ["bash", str(experimental), str(bundle), str(report)],
                env={**os.environ, "PATH": str(commands) + ":/usr/bin:/bin",
                     "T825_SOURCE_ROOT": str(root), "T825_KEXEC_BIN": str(kexec),
                     "TEST_RESET_MARKER": str(root / "reset-observed")},
                text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((report / "status.txt").read_text().strip(),
                             "RECOVERY_PASS_PROOF_UNOBSERVED")
            self.assertEqual((report / "diagnostic-pass").read_text().strip(), "0")
            self.assertEqual((report / "restore-pass").read_text().strip(), "1")


if __name__ == "__main__":
    unittest.main()
