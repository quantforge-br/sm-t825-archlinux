#!/usr/bin/env python3
"""Exercise the actual AArch64 supervisor under QEMU; never invoke host reboot."""
import pathlib
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RecoverySupervisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="t825-recovery-")
        cls.folder = pathlib.Path(cls.temporary.name)
        cls.binary = cls.folder / "supervisor"
        subprocess.run([str(ROOT / "tools/build-t825-recovery-supervisor.sh"), str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def command(self, seconds, directory):
        return ["qemu-aarch64-static", "-strace", str(self.binary), str(seconds), str(directory), "--dry-run"]

    def test_expires_without_reboot_syscall(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            result = subprocess.run(self.command(1, directory), capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = (pathlib.Path(directory) / "supervisor.log").read_text()
            self.assertIn("deadline expired", log)
            self.assertIn("dry-run: reboot suppressed", log)
            self.assertNotIn("reboot(", result.stderr)

    def test_lease_and_log_survive_directory_move(self):
        directory = self.folder / "before-pivot"
        directory.mkdir()
        moved = self.folder / "after-pivot"
        process = subprocess.Popen(self.command(2, directory), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            limit = time.monotonic() + 3
            while not (directory / "supervisor.log").exists():
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), limit)
                time.sleep(0.02)
            directory.rename(moved)
            expiry = int(time.clock_gettime(time.CLOCK_BOOTTIME)) + 4
            (moved / "lease").write_text(str(expiry))
            _, stderr = process.communicate(timeout=7)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertGreaterEqual(time.clock_gettime(time.CLOCK_BOOTTIME), expiry)
            self.assertIn("deadline expired", (moved / "supervisor.log").read_text())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_unbounded_lease_does_not_disable_timeout(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as directory:
            (pathlib.Path(directory) / "lease").write_text("99999999999999")
            result = subprocess.run(self.command(1, directory), capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_deadline_is_rejected(self):
        for deadline in ("0", "-1", "3601", "oops"):
            result = subprocess.run(self.command(deadline, self.folder), capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == "__main__":
    unittest.main()
