#!/usr/bin/env python3
"""Validate the minimal pre-supervisor kexec candidate builder offline."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
BUILDER = REPO / "install/make-kexec-proof-bundle.sh"
CANDIDATE = REPO / "artifacts/roadmap-7.3/kexec-route-audit-20261110/candidate"
ROOTFS = REPO / "artifacts/work/pmb/chroot_rootfs_samsung-gts3lwifi"
SUPERVISOR = REPO / "artifacts/roadmap-7.3/normal-r2-readonly-candidate-20261110d/supervisor"


@unittest.skipUnless((CANDIDATE / "vmlinuz").is_file(), "local candidate artifacts unavailable")
class KexecProofBundle(unittest.TestCase):
    def env(self):
        return {
            **os.environ,
            "T825_KEXEC_PROOF_KERNEL": str(CANDIDATE / "vmlinuz"),
            "T825_KEXEC_PROOF_DTB": str(CANDIDATE / "t825.dtb"),
            "T825_KEXEC_PROOF_BUSYBOX": str(ROOTFS / "usr/bin/busybox"),
            "T825_KEXEC_PROOF_LOADER": str(ROOTFS / "lib/ld-musl-aarch64.so.1"),
            "T825_KEXEC_PROOF_SUPERVISOR": str(SUPERVISOR),
            "T825_KEXEC_PROOF_SECONDS": "45",
        }

    def build(self, directory):
        subprocess.run([str(BUILDER), str(directory)], check=True, env=self.env(),
                       capture_output=True, text=True)

    def unpack(self, archive, directory):
        raw = subprocess.run(["unzstd", "-c", str(archive)], check=True,
                             capture_output=True).stdout
        subprocess.run(["cpio", "-id", "--quiet", "--no-absolute-filenames"],
                       cwd=directory, input=raw, check=True)

    def test_bundle_is_deterministic_and_has_no_root_transition(self):
        with tempfile.TemporaryDirectory(prefix="t825-kexec-proof-test-") as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"
            self.build(first)
            self.build(second)
            self.assertEqual(hashlib.sha256((first / "initramfs").read_bytes()).digest(),
                             hashlib.sha256((second / "initramfs").read_bytes()).digest())
            self.assertEqual((first / "SHA256SUMS").read_text(), (second / "SHA256SUMS").read_text())
            with tempfile.TemporaryDirectory() as extracted:
                self.unpack(first / "initramfs", extracted)
                init = (Path(extracted) / "init").read_text()
                self.assertIn("t825-recovery 45 /run/t825-recovery", init)
                self.assertIn("mount -t tmpfs tmpfs /run", init)
                self.assertNotIn("mount_root", init)
                self.assertNotIn("/sysroot", init)
                self.assertNotIn("mmcblk", init)
            subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=first,
                           check=True, capture_output=True, text=True)

    def test_invalid_deadline_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory(prefix="t825-kexec-proof-test-") as tmp:
            output = Path(tmp) / "bad"
            env = self.env()
            env["T825_KEXEC_PROOF_SECONDS"] = "301"
            result = subprocess.run([str(BUILDER), str(output)], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
