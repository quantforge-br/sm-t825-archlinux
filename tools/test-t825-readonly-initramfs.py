#!/usr/bin/env python3
"""Exercise normal RAM preparation safety gates against real initramfs input.

Usage: test-t825-readonly-initramfs.py TRUSTED_NORMAL_INITRAMFS
All extraction and mutation stays in a temporary host directory. No device,
mount, module loading or reboot command is used.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "readonly_prepare", REPO / "install/prepare-t825-readonly-initramfs.py")
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


class PreparationSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = tempfile.TemporaryDirectory(prefix="t825-normal-fixture-")
        cls.tree = Path(cls.source.name)
        archive = subprocess.run(["unzstd", "-c", str(INPUT)], check=True, capture_output=True).stdout
        subprocess.run(["cpio", "-id", "--quiet", "--no-absolute-filenames"],
                       cwd=cls.tree, input=archive, check=True)
        cls.init = (cls.tree / "init_2nd.sh").read_text()
        cls.functions = (cls.tree / "init_functions.sh").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.source.cleanup()

    def test_transformed_root_cannot_run_installer_or_repair(self):
        init, functions = prep.transform(self.init, self.functions)
        for call in ("delete_old_install_partition", "resize_root_partition",
                     "resize_root_filesystem", "resize_filesystem_after_mount /sysroot"):
            self.assertNotIn(call, init.splitlines())
        for command in ("e2fsck -p", "fsck.f2fs -p", "fsck.vfat -p", "fsck.xfs -p"):
            self.assertNotIn(command, functions)
        self.assertIn('busybox blockdev --setro "$t825_root_device" || fail_halt_boot', functions)
        self.assertIn("t825_root_mountopts=ro,rescue=nologreplay", functions)
        self.assertNotIn("wait_boot_partition", init)
        self.assertNotIn("mount_boot_partition /sysroot/boot", init)
        self.assertIn('init="/run/t825-recovery/postpivot-init"', init)
        self.assertNotIn('init="/sbin/init"', init)
        self.assertIn('busybox ash /hooks-cleanup/90-t825-readonly-runtime.sh || fail_halt_boot', init)

    def test_recovery_is_armed_before_first_module_operation(self):
        _, functions = prep.transform(self.init, self.functions)
        mount_function = functions.split('mount_proc_sys_dev() {', 1)[1].split('\n}', 1)[0]
        self.assertLess(mount_function.index('mount -t tmpfs'), mount_function.index('t825-recovery-arm'))
        self.assertLess(mount_function.index('t825-recovery-arm'), mount_function.index('modprobe'))
        self.assertIn('run /run || fail_halt_boot', mount_function)

    def test_drift_and_repeated_preparation_are_rejected(self):
        for init, functions in ((self.init.replace('check_keys\n', 'changed\n'), self.functions),
                                (self.init, self.functions.replace('setup_usb_acm_configfs\n', 'changed\n')),
                                (self.init, self.functions.replace('check_filesystem() {', 'changed() {')),
                                prep.transform(self.init, self.functions)):
            with self.assertRaises(ValueError):
                prep.transform(init, functions)

    def variant(self):
        tmp = tempfile.TemporaryDirectory(prefix="t825-prepare-variant-")
        self.addCleanup(tmp.cleanup)
        tree = Path(tmp.name) / "root"
        shutil.copytree(self.tree, tree, symlinks=True)
        return tree

    def reject_without_mutation(self, tree, release="7.3.1-t825"):
        before = (tree / "init_2nd.sh").read_bytes()
        with self.assertRaises(ValueError):
            prep.prepare(tree, Path("unused-supervisor"), Path("unused-public-key"), release)
        self.assertEqual(before, (tree / "init_2nd.sh").read_bytes())
        self.assertFalse((tree / "usr/local/libexec/t825-recovery-supervisor").exists())

    def test_mss_and_mixed_module_releases_are_rejected(self):
        self.reject_without_mutation(self.variant(), "7.3.1-t825-mssdiag")
        tree = self.variant()
        (tree / "usr/lib/modules/7.3.1-t825-mssdiag").mkdir()
        self.reject_without_mutation(tree)

    def test_existing_hooks_and_host_escaping_symlinks_are_rejected(self):
        tree = self.variant()
        (tree / "hooks-extra").mkdir()
        (tree / "hooks-extra/stale.sh").write_text("exit 0\n")
        self.reject_without_mutation(tree)
        tree = self.variant()
        (tree / "usr/local").symlink_to('/var/tmp')
        self.reject_without_mutation(tree)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    INPUT = Path(sys.argv.pop(1)).resolve()
    unittest.main()
