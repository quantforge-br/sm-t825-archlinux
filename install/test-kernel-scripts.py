#!/usr/bin/env python3
"""Exercise update/rollback in fake roots; never mount or modify host modules."""
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
OLD = '6.19.5-t825'
NEW = '7.3.1-t825'
DTB = 'boot/dtbs/qcom/msm8996-samsung-gts3llte.dtb'
STATE = 'var/tmp/t825-kernel/'


class KernelScripts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='t825-install-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, ROOT=str(self.root), PATH=str(self.bin) + ':' + os.environ['PATH'])
        for key in ('KVER', 'FAIL_COPY_MATCH', 'LOW_SPACE'):
            self.env.pop(key, None)
        real_cp = shutil.which('cp')
        real_df = shutil.which('df')
        mocks = {
            'mountpoint': 'test "$1" = -q && test -d "$2"',
            'depmod': 'test "$1" = -b && test -f "$2/usr/lib/modules/$4/modules.dep"',
            'sync': 'exit 0',
            'cp': f'''if [[ -n "${{FAIL_COPY_MATCH:-}}" && "${{@: -1}}" == *"$FAIL_COPY_MATCH"* ]]; then
    printf truncated > "${{@: -1}}"
    echo 'injected copy failure: no space left on device' >&2
    exit 1
fi
exec {real_cp} "$@"''',
            'df': f'''if [[ "${{LOW_SPACE:-}}" == 1 ]]; then
    printf 'Avail\\n0\\n'
else
    exec {real_df} "$@"
fi''',
        }
        for name, body in mocks.items():
            p = self.bin / name
            p.write_text('#!/bin/bash\nset -eu\n' + body + '\n')
            p.chmod(0o755)
        self.old_image = self.image(OLD)
        self.put('boot/vmlinuz-t825', self.old_image)
        self.put('boot/initramfs-t825', b'old initramfs')
        self.put(DTB, b'old DTB')
        self.put(f'usr/lib/modules/{OLD}/modules.dep', b'old modules')
        self.kernel = self.base / 'vmlinuz'
        self.kernel.write_bytes(self.image(NEW))
        self.initramfs = self.base / 'initramfs'
        self.initramfs.write_bytes(b'new initramfs')
        self.dtb = self.base / 'new.dtb'
        self.dtb.write_bytes(b'new DTB')
        self.mods = self.package(NEW, b'new modules')

    @staticmethod
    def image(version):
        return gzip.compress(b'\0Linux version ' + version.encode() + b' (test build)\0', mtime=0)

    def put(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def package(self, release, data):
        p = self.base / (release + '-modules')
        p.mkdir(exist_ok=True)
        (p / 'modules.dep').write_bytes(data)
        archive = self.base / (release + '.tar')
        with tarfile.open(archive, 'w') as tar:
            tar.add(p, arcname=release)
        return archive

    def run_script(self, script, *args, success=True, extra=None):
        result = subprocess.run(['bash', str(REPO / 'install' / script), *map(str, args)],
                                env=self.env | (extra or {}), capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertFalse(list(self.root.rglob('*.tmp')), 'temporary files leaked')
        return result

    def update(self, dtb=True, **kwargs):
        args = [self.mods, self.kernel, self.initramfs]
        if dtb:
            args.append(self.dtb)
        return self.run_script('update-kernel.sh', *args, **kwargs)

    def rollback(self, **kwargs):
        return self.run_script('rollback-kernel.sh', **kwargs)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def assert_old_boot(self):
        self.assertEqual((self.root / 'boot/vmlinuz-t825').read_bytes(), self.old_image)
        self.assertEqual((self.root / 'boot/initramfs-t825').read_bytes(), b'old initramfs')
        self.assertEqual((self.root / DTB).read_bytes(), b'old DTB')
        self.assertEqual((self.root / f'usr/lib/modules/{OLD}/modules.dep').read_bytes(), b'old modules')

    def cross_release_flow(self):
        self.put(STATE + 'modules-prev.tar', b'stale archive')
        self.put(STATE + 'modules-version', OLD.encode())
        self.update()
        self.assertFalse((self.root / (STATE + 'modules-prev.tar')).exists())
        self.assertFalse((self.root / (STATE + 'modules-version')).exists())
        self.assertEqual((self.root / DTB).read_bytes(), b'new DTB')
        self.assertEqual((self.root / (DTB + '.prev')).read_bytes(), b'old DTB')
        self.rollback()
        self.assert_old_boot()
        self.rollback()
        self.assert_old_boot()

    def test_cross_release_and_dtb_rollback(self):
        self.cross_release_flow()

    def test_staged_modules_are_fresh_install(self):
        self.put(f'usr/lib/modules/{NEW}/modules.dep', b'RAM-test modules')
        self.cross_release_flow()
        self.assertEqual((self.root / f'usr/lib/modules/{NEW}/modules.dep').read_bytes(), b'new modules')

    def test_same_release_restore_uses_installed_kernel(self):
        # Valid gzip image with a distinguishable built-in version string.
        current = gzip.compress(b'\0Linux version ' + NEW.encode() + b' (previous build)\0', mtime=0)
        self.put('boot/vmlinuz-t825', current)
        self.put(f'usr/lib/modules/{NEW}/modules.dep', b'current modules')
        self.update()
        self.assertEqual((self.root / (STATE + 'modules-version')).read_text(), NEW + '\n')
        self.put(f'usr/lib/modules/{NEW}/leftover.ko', b'replacement-only module')
        self.rollback(extra={'KVER': 'wrong-default'})
        self.assertEqual((self.root / 'boot/vmlinuz-t825').read_bytes(), current)
        self.assertEqual((self.root / f'usr/lib/modules/{NEW}/modules.dep').read_bytes(), b'current modules')
        self.assertFalse((self.root / f'usr/lib/modules/{NEW}/leftover.ko').exists())
        self.rollback()

    def test_optional_dtb_clears_stale_backup(self):
        self.put(DTB + '.prev', b'unrelated DTB')
        self.update(dtb=False)
        self.assertFalse((self.root / (DTB + '.prev')).exists())
        self.assertEqual((self.root / DTB).read_bytes(), b'old DTB')
        self.rollback()
        self.assert_old_boot()

    def test_legacy_archive_error_and_explicit_release(self):
        self.update()
        self.put(STATE + 'modules-prev.tar', self.package(OLD, b'legacy modules').read_bytes())
        before = self.snapshot()
        result = self.rollback(success=False)
        self.assertIn(f'modules-prev.tar has no {NEW}/modules.dep (set KVER=', result.stderr)
        self.assertEqual(before, self.snapshot())
        self.rollback(extra={'KVER': OLD})
        self.assertEqual((self.root / f'usr/lib/modules/{OLD}/modules.dep').read_bytes(), b'legacy modules')

    def test_wrong_kernel_and_corrupt_gzip_rejected(self):
        for image in (self.image(OLD), b'not gzip', self.image(NEW)[:-8]):
            with self.subTest(image=image):
                self.kernel.write_bytes(image)
                before = self.snapshot()
                result = self.update(success=False)
                self.assertIn('does not contain Linux version', result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_binary_banner_without_strings(self):
        stub = self.bin / 'strings'
        stub.write_text('#!/bin/bash\necho strings must not be used >&2\nexit 1\n')
        stub.chmod(0o755)
        self.kernel.write_bytes(gzip.compress(
            b'\xffbinary prefix\0Linux version ' + NEW.encode() + b' (build)\0' +
            b'\0' * 200000 + b'Linux version ' + NEW.encode() + b' (second banner)\0'))
        self.update()
        self.rollback()
        self.assert_old_boot()

    def test_missing_required_tool_has_explicit_error(self):
        isolated = self.base / 'isolated-bin'
        isolated.mkdir()
        commands = ('grep tar mountpoint mktemp cp chmod sync mv stat df tail rm mkdir cat '
                    'gzip awk sha256sum').split()
        for command in commands:
            (isolated / command).symlink_to(shutil.which(command))
        for script in ('update-kernel.sh', 'rollback-kernel.sh'):
            with self.subTest(script=script):
                before = self.snapshot()
                result = subprocess.run(
                    ['/bin/bash', str(REPO / 'install' / script)],
                    env=self.env | {'PATH': str(isolated)}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('missing required command: depmod', result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_wrong_modules_rejected(self):
        self.mods = self.package('wrong-release', b'wrong')
        before = self.snapshot()
        self.update(success=False)
        self.assertEqual(before, self.snapshot())

    def test_missing_boot_backup_rejected(self):
        self.update()
        (self.root / 'boot/initramfs-t825.prev').unlink()
        before = self.snapshot()
        self.rollback(success=False)
        self.assertEqual(before, self.snapshot())

    def test_update_space_preflight(self):
        before = self.snapshot()
        result = self.update(success=False, extra={'LOW_SPACE': '1'})
        self.assertIn('not enough free space', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_rollback_space_preflight(self):
        self.update()
        before = self.snapshot()
        result = self.rollback(success=False, extra={'LOW_SPACE': '1'})
        self.assertIn('not enough free space', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_update_truncated_backup_preserves_all_destinations(self):
        self.put('boot/vmlinuz-t825.prev', b'earlier kernel backup')
        self.put('boot/initramfs-t825.prev', b'earlier initramfs backup')
        before = self.snapshot()
        self.update(success=False, extra={'FAIL_COPY_MATCH': 'initramfs-t825.prev.'})
        self.assertEqual(before, self.snapshot())

    def test_update_truncated_dtb_preserves_all_destinations(self):
        before = self.snapshot()
        self.update(success=False, extra={'FAIL_COPY_MATCH': 'gts3llte.dtb.'})
        self.assertEqual(before, self.snapshot())

    def test_rollback_truncated_copy_preserves_all_destinations(self):
        self.update()
        before = self.snapshot()
        self.rollback(success=False, extra={'FAIL_COPY_MATCH': 'initramfs-t825.'})
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main(verbosity=2)
