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
        for key in ('KVER', 'FAIL_COPY_MATCH', 'LOW_SPACE', 'FAIL_EXTRACT', 'FAIL_DEPMOD',
                    'FAIL_MV_MATCH', 'FAIL_RM_MATCH', 'ALLOW_LEGACY_MODULES',
                    'LK2ND_MAX_KERNEL_SIZE', 'LK2ND_BOOT_MEM_SIZE'):
            self.env.pop(key, None)
        real_cp = shutil.which('cp')
        real_df = shutil.which('df')
        real_tar = shutil.which('tar')
        real_mv = shutil.which('mv')
        real_rm = shutil.which('rm')
        mocks = {
            'mountpoint': 'test "$1" = -q && test -d "$2"',
            'depmod': '''test "${FAIL_DEPMOD:-}" != 1 || { echo 'injected depmod failure' >&2; exit 1; }
test "$1" = -b && test "$3" = -m && test "$4" = /lib/modules && test "$5" = -a
test -f "$2/lib/modules/$6/modules.dep"''',
            'tar': f'''if [[ "${{FAIL_EXTRACT:-}}" == 1 && " $* " == *" -xf "* ]]; then
    printf partial > "$2/partial-extract.ko"
    echo 'injected tar extraction failure' >&2
    exit 1
fi
exec {real_tar} "$@"''',
            'mv': f'''if [[ -n "${{FAIL_MV_MATCH:-}}" && "${{@: -1}}" == "$FAIL_MV_MATCH" ]]; then
    # Fail once so the EXIT trap can restore the original directory.
    if [[ ! -e "$ROOT/mv-failed" ]]; then
        touch "$ROOT/mv-failed"
        echo 'injected rename failure' >&2
        exit 1
    fi
fi
exec {real_mv} "$@"''',
            'rm': f'''if [[ -n "${{FAIL_RM_MATCH:-}}" && " $* " == *"$FAIL_RM_MATCH"* ]]; then
    echo 'injected removal failure' >&2
    exit 1
fi
exec {real_rm} "$@"''',
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
        header = bytearray(64)
        header[16:24] = (4096).to_bytes(8, 'little')
        header[56:60] = b'ARM\x64'
        return gzip.compress(header + b'Linux version ' + version.encode() + b' (test build)\0', mtime=0)

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

    def run_script(self, script, *args, success=True, extra=None, old_left=False):
        result = subprocess.run(['bash', str(REPO / 'install' / script), *map(str, args)],
                                env=self.env | (extra or {}), capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertFalse(list(self.root.rglob('*.tmp')), 'temporary files leaked')
        self.assertFalse(list(self.root.glob('usr/lib/modules/.*.new')), 'module staging leaked')
        if not old_left:
            self.assertFalse(list(self.root.glob('usr/lib/modules/.*.old')), 'old modules leaked')
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
        result = self.rollback(success=False, extra={'ALLOW_LEGACY_MODULES': '1'})
        self.assertIn(f'modules-prev.tar has no {NEW}/modules.dep (set KVER=', result.stderr)
        self.assertEqual(before, self.snapshot())
        result = self.rollback(extra={'KVER': OLD, 'ALLOW_LEGACY_MODULES': '1'})
        self.assertIn('unverified legacy module backup', result.stderr)
        self.assertEqual((self.root / f'usr/lib/modules/{OLD}/modules.dep').read_bytes(), b'legacy modules')

    def test_wrong_kernel_and_corrupt_gzip_rejected(self):
        for image in (self.image(OLD), b'not gzip', self.image(NEW)[:-8]):
            with self.subTest(image=image):
                self.kernel.write_bytes(image)
                before = self.snapshot()
                result = self.update(success=False)
                self.assertIn('does not contain Linux version' if image == self.image(OLD)
                              else 'cannot decompress', result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_lk2nd_over_limit_refused_without_mutation(self):
        # Highly compressible: compressed size and header image_size both fit.
        data = bytearray(28106753)
        data[16:24] = (64).to_bytes(8, 'little')
        data[56:60] = b'ARM\x64'
        banner = b'Linux version ' + NEW.encode() + b' (test)\0'
        data[64:64 + len(banner)] = banner
        self.kernel.write_bytes(gzip.compress(data, mtime=0))
        before = self.snapshot()
        directories = sorted(str(p) for p in self.root.rglob('*') if p.is_dir())
        result = self.update(success=False, extra={'LK2ND_MAX_KERNEL_SIZE': '28106752'})
        self.assertIn('28106753 decompressed bytes > effective limit 28106752', result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(directories, sorted(str(p) for p in self.root.rglob('*') if p.is_dir()))

    def test_lk2nd_under_limit_and_exact_limit_ok(self):
        size = len(gzip.decompress(self.kernel.read_bytes()))
        for limit in (size + 1, size):
            with self.subTest(limit=limit):
                self.update(extra={'LK2ND_MAX_KERNEL_SIZE': str(limit)})

    def test_lk2nd_override_and_invalid_limit_refused(self):
        size = len(gzip.decompress(self.kernel.read_bytes()))
        for limit in (str(size - 1), '0', '-1', 'abc', '1+1', '4294967296', '99999999999999999999'):
            with self.subTest(limit=limit):
                before = self.snapshot()
                result = self.update(success=False, extra={'LK2ND_MAX_KERNEL_SIZE': limit})
                self.assertIn('effective limit' if limit == str(size - 1)
                              else 'LK2ND_MAX_KERNEL_SIZE', result.stderr)
                self.assertEqual(before, self.snapshot())

    def sized_kernel(self, size, *, text_offset=0, image_size=4096, arm64=True):
        data = bytearray(size)
        data[8:16] = text_offset.to_bytes(8, 'little')
        data[16:24] = image_size.to_bytes(8, 'little')
        data[56:60] = b'ARM\x64' if arm64 else b'nope'
        banner = b'Linux version ' + NEW.encode() + b' (test)\0'
        data[64:64 + len(banner)] = banner
        self.kernel.write_bytes(gzip.compress(data, mtime=0))

    def sized_initramfs(self, size):
        with self.initramfs.open('wb') as stream:
            stream.truncate(size)

    def refused_without_mutation(self, **kwargs):
        before = self.snapshot()
        directories = sorted(str(p) for p in self.root.rglob('*') if p.is_dir())
        result = self.update(success=False, **kwargs)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(directories, sorted(str(p) for p in self.root.rglob('*') if p.is_dir()))
        return result

    def test_lk2nd_actual_initramfs_sets_budget(self):
        self.sized_kernel(23966208)
        self.sized_initramfs(22222608)
        result = self.update()
        self.assertIn('rounddown(52428800 - 22222608, 4096) - 2097152 - 0 = 30203904 - 2097152 - 0 = 28106752', result.stderr)
        self.sized_initramfs(28000000)
        # An extra cap can only tighten the computed budget, never bypass it.
        result = self.refused_without_mutation(extra={'LK2ND_MAX_KERNEL_SIZE': '50000000'})
        self.assertIn('kernel too big', result.stderr)
        self.assertIn('cap=50000000', result.stderr)

    def test_lk2nd_reference_cap_is_optional(self):
        self.sized_kernel(29356544)
        self.update()  # Small initramfs: the historical reference cap is irrelevant.
        result = self.refused_without_mutation(extra={'LK2ND_MAX_KERNEL_SIZE': '28106752'})
        self.assertIn('29356544 decompressed bytes > effective limit 28106752', result.stderr)

    def test_lk2nd_rounddown_boundary(self):
        self.sized_kernel(23966208)
        self.sized_initramfs(26361856)
        result = self.update()
        self.assertIn('effective=23969792; kernel=23966208', result.stderr)
        self.sized_initramfs(26361857)
        result = self.refused_without_mutation()
        self.assertIn('rounddown(52428800 - 26361857, 4096) - 2097152 - 0 = 26062848 - 2097152 - 0 = 23965696', result.stderr)

    def test_lk2nd_initramfs_at_or_above_boot_memory(self):
        for size in (52428800, 52428801, 2**32):
            with self.subTest(size=size):
                self.sized_initramfs(size)
                result = self.refused_without_mutation()
                self.assertIn(f'initramfs={size} >= boot_mem=52428800', result.stderr)

    def test_lk2nd_zero_and_negative_budget(self):
        for size in (52428800 - 2097152, 52428800 - 2097152 + 1):
            with self.subTest(size=size):
                self.sized_initramfs(size)
                result = self.refused_without_mutation()
                self.assertIn('lk2nd budget refused: rounddown(', result.stderr)

    def test_lk2nd_header_offsets(self):
        # Use a small boot-memory override to test offsets without huge fixtures.
        for fields, offset in (({'text_offset': 4096}, 4096),
                               ({'image_size': 0, 'text_offset': 4096}, 0x80000),
                               ({'arm64': False}, 0x8000),
                               ({'text_offset': 2097152}, 2097152),
                               ({'text_offset': 2097153}, 0),
                               ({'text_offset': 2**63}, 0),
                               ({'text_offset': 2**64 - 1, 'image_size': 0}, 0),
                               ({'image_size': 2**63, 'text_offset': 4096}, 4096)):
            with self.subTest(fields=fields):
                self.sized_kernel(4096, **fields)
                mem = 2097152 + offset + 4096 + 4096
                self.sized_initramfs(4096)
                result = self.update(extra={'LK2ND_BOOT_MEM_SIZE': str(mem)})
                self.assertIn(f'- 2097152 - {offset} = 4096', result.stderr)
                self.sized_initramfs(4097)
                result = self.refused_without_mutation(extra={'LK2ND_BOOT_MEM_SIZE': str(mem)})
                self.assertIn(f'- 2097152 - {offset} = 0', result.stderr)

    def test_lk2nd_invalid_boot_memory(self):
        for value in ('0', '-1', 'abc', '1+1', '4294967296', '99999999999999999999'):
            with self.subTest(value=value):
                result = self.refused_without_mutation(extra={'LK2ND_BOOT_MEM_SIZE': value})
                self.assertIn('LK2ND_BOOT_MEM_SIZE must be', result.stderr)

    def test_lk2nd_short_header_refused(self):
        self.kernel.write_bytes(gzip.compress(b'Linux version ' + NEW.encode() + b' '))
        result = self.refused_without_mutation()
        self.assertIn('cannot read the first 64 bytes', result.stderr)

    def test_lk2nd_readable_banner_with_late_gzip_corruption(self):
        data = gzip.decompress(self.image(NEW)) + b'\0' * 200000
        compressed = gzip.compress(data, mtime=0)
        bad_crc = compressed[:-8] + bytes([compressed[-8] ^ 1]) + compressed[-7:]
        for blob in (compressed[:-8], bad_crc):
            with self.subTest(truncated=len(blob) != len(compressed)):
                self.kernel.write_bytes(blob)
                decoded = subprocess.run(['gzip', '-dc', str(self.kernel)], capture_output=True)
                self.assertIn(b'Linux version ' + NEW.encode(), decoded.stdout)
                self.assertNotEqual(decoded.returncode, 0)
                result = self.refused_without_mutation()
                self.assertIn('cannot decompress', result.stderr)

    def test_lk2nd_concatenated_members_are_conservative(self):
        self.sized_kernel(4096)
        self.kernel.write_bytes(self.kernel.read_bytes() + gzip.compress(b'\0' * 4096))
        result = self.refused_without_mutation(extra={'LK2ND_MAX_KERNEL_SIZE': '4096'})
        self.assertIn('8192 decompressed bytes > effective limit 4096', result.stderr)

    def test_lk2nd_dtb_has_separate_size_limit(self):
        self.sized_initramfs(22222608)
        for size in (2097152, 2097153):
            with self.subTest(size=size):
                with self.dtb.open('wb') as stream:
                    stream.truncate(size)
                result = self.refused_without_mutation()
                self.assertIn(f'DTB too big for lk2nd: {size} bytes >= MAX_TAGS_SIZE=2097152', result.stderr)
        with self.dtb.open('wb') as stream:
            stream.truncate(2097151)
        result = self.update()
        self.assertIn('effective=28106752', result.stderr)

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

    def same_release_setup(self):
        self.put('boot/vmlinuz-t825', self.image(NEW))
        self.put(f'usr/lib/modules/{NEW}/modules.dep', b'current modules')

    def test_extraction_failure_preserves_modules_update_and_rollback(self):
        self.same_release_setup()
        before = self.snapshot()
        self.update(success=False, extra={'FAIL_EXTRACT': '1'})
        self.assertEqual(before, self.snapshot())
        self.update()
        before = self.snapshot()
        self.rollback(success=False, extra={'FAIL_EXTRACT': '1'})
        self.assertEqual(before, self.snapshot())

    def test_depmod_failure_preserves_modules_update_and_rollback(self):
        self.same_release_setup()
        before = self.snapshot()
        self.update(success=False, extra={'FAIL_DEPMOD': '1'})
        self.assertEqual(before, self.snapshot())
        self.update()
        before = self.snapshot()
        self.rollback(success=False, extra={'FAIL_DEPMOD': '1'})
        self.assertEqual(before, self.snapshot())

    def test_real_depmod_uses_private_staging_root(self):
        self.same_release_setup()
        # Empty module set is enough to verify real kmod's -b/-m layout and
        # index output, without touching the host's module tree.
        payload = self.base / (NEW + '-modules')
        for name in ('modules.order', 'modules.builtin', 'modules.builtin.modinfo'):
            (payload / name).write_bytes(b'')
            self.put(f'usr/lib/modules/{NEW}/{name}', b'')
        self.mods = self.package(NEW, b'')
        (self.bin / 'depmod').unlink()
        (self.bin / 'depmod').symlink_to(shutil.which('depmod'))
        self.update()
        live = self.root / f'usr/lib/modules/{NEW}'
        self.assertTrue((live / 'modules.dep.bin').is_file())
        self.assertEqual((live / 'modules.dep').read_bytes(), b'')
        self.rollback()
        self.assertTrue((live / 'modules.dep.bin').is_file())
        self.assertEqual((live / 'modules.dep').read_bytes(), b'')

    def test_module_swap_failure_restores_old_directory(self):
        self.same_release_setup()
        path = f'usr/lib/modules/{NEW}/modules.dep'
        target = str(self.root / f'usr/lib/modules/{NEW}')
        self.update(success=False, extra={'FAIL_MV_MATCH': target})
        self.assertEqual((self.root / path).read_bytes(), b'current modules')
        (self.root / 'mv-failed').unlink()
        self.update()
        self.rollback(success=False, extra={'FAIL_MV_MATCH': target})
        self.assertEqual((self.root / path).read_bytes(), b'new modules')

    def test_boot_backup_failure_does_not_publish_module_archive(self):
        self.same_release_setup()
        self.put('boot/vmlinuz-t825.prev', b'generation Z kernel')
        self.put(STATE + 'modules-prev.tar', b'generation Z modules')
        self.put(STATE + 'modules-version', NEW.encode())
        before = self.snapshot()
        self.update(success=False, extra={
            'FAIL_MV_MATCH': str(self.root / 'boot/vmlinuz-t825.prev')})
        (self.root / 'mv-failed').unlink()
        self.assertEqual(before, self.snapshot())

    def test_boot_backup_failure_does_not_discard_module_archive(self):
        self.put(STATE + 'modules-prev.tar', b'old archive')
        self.put(STATE + 'modules-version', OLD.encode())
        before = self.snapshot()
        self.update(success=False, extra={
            'FAIL_MV_MATCH': str(self.root / 'boot/vmlinuz-t825.prev')})
        (self.root / 'mv-failed').unlink()
        self.assertEqual(before, self.snapshot())

    def test_second_update_replaces_single_rollback_slot(self):
        self.update()
        self.update()
        self.assertEqual((self.root / 'boot/vmlinuz-t825.prev').read_bytes(), self.image(NEW))
        self.assertEqual((self.root / (STATE + 'modules-version')).read_text(), NEW + '\n')
        result = self.rollback()
        self.assertIn(f'restoring modules: KVER={NEW} path={self.root}/usr/lib/modules/{NEW}',
                      result.stdout)
        self.assertEqual((self.root / 'boot/vmlinuz-t825').read_bytes(), self.image(NEW))

    def generation_setup(self):
        self.same_release_setup()
        self.update()  # archive Z bound to kernel Z
        self.put('boot/vmlinuz-t825', gzip.compress(
            b'\0Linux version ' + NEW.encode() + b' (generation A)\0', mtime=0))
        self.put(f'usr/lib/modules/{NEW}/modules.dep', b'generation A modules')

    def assert_binding_refusal(self):
        before = self.snapshot()
        result = self.rollback(success=False)
        self.assertIn('generation mismatch', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_death_before_archive_publish_rejects_mixed_generation(self):
        self.generation_setup()
        self.update(success=False, extra={
            'FAIL_MV_MATCH': str(self.root / (STATE + 'modules-prev.tar'))})
        self.assert_binding_refusal()

    def test_death_before_binding_publish_rejects_mixed_generation(self):
        self.generation_setup()
        self.update(success=False, extra={
            'FAIL_MV_MATCH': str(self.root / (STATE + 'modules-binding'))})
        self.assert_binding_refusal()

    def test_cross_release_stale_archive_rejected_after_boot_backup(self):
        self.generation_setup()
        self.put('boot/vmlinuz-t825', self.image(OLD))
        self.update(success=False, extra={
            'FAIL_RM_MATCH': str(self.root / (STATE + 'modules-prev.tar'))})
        self.assert_binding_refusal()

    def test_binding_rejects_changed_archive_even_with_same_kernel(self):
        self.same_release_setup()
        self.update()
        self.put(STATE + 'modules-prev.tar', self.package(NEW, b'wrong build').read_bytes())
        self.assert_binding_refusal()

    def test_missing_binding_requires_explicit_legacy_opt_in(self):
        self.same_release_setup()
        self.update()
        (self.root / (STATE + 'modules-binding')).unlink()
        before = self.snapshot()
        result = self.rollback(success=False)
        self.assertIn('set ALLOW_LEGACY_MODULES=1', result.stderr)
        self.assertEqual(before, self.snapshot())
        result = self.rollback(extra={'ALLOW_LEGACY_MODULES': '1'})
        self.assertIn('unverified legacy module backup', result.stderr)

    def test_malformed_binding_cannot_use_legacy_bypass(self):
        self.same_release_setup()
        self.update()
        self.put(STATE + 'modules-binding', b'incomplete')
        before = self.snapshot()
        result = self.rollback(success=False, extra={'ALLOW_LEGACY_MODULES': '1'})
        self.assertIn('invalid modules-binding', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_update_old_cleanup_failure_still_publishes_boot_files(self):
        self.same_release_setup()
        self.kernel.write_bytes(gzip.compress(
            b'\0' * 64 + b'Linux version ' + NEW.encode() + b' (replacement build)\0', mtime=0))
        old = self.root / f'usr/lib/modules/.{NEW}.old'
        result = self.update(old_left=True, extra={'FAIL_RM_MATCH': str(old)})
        self.assertIn(f'warning: could not remove {old}', result.stderr)
        self.assertEqual((old / 'modules.dep').read_bytes(), b'current modules')
        self.assertEqual((self.root / f'usr/lib/modules/{NEW}/modules.dep').read_bytes(), b'new modules')
        self.assertEqual((self.root / 'boot/vmlinuz-t825').read_bytes(), self.kernel.read_bytes())
        self.assertEqual((self.root / 'boot/initramfs-t825').read_bytes(), b'new initramfs')
        self.assertEqual((self.root / DTB).read_bytes(), b'new DTB')
        # Keep the leftovers for inspection, rather than silently removing them
        # or overwriting them on the next attempt.
        before = self.snapshot()
        result = self.update(success=False, old_left=True)
        self.assertIn('unfinished module swap', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_rollback_old_cleanup_failure_still_restores_boot_files(self):
        self.same_release_setup()
        previous = self.snapshot()
        self.kernel.write_bytes(gzip.compress(
            b'\0' * 64 + b'Linux version ' + NEW.encode() + b' (replacement build)\0', mtime=0))
        self.update()
        old = self.root / f'usr/lib/modules/.{NEW}.old'
        result = self.rollback(old_left=True, extra={'FAIL_RM_MATCH': str(old)})
        self.assertIn(f'warning: could not remove {old}', result.stderr)
        self.assertEqual((old / 'modules.dep').read_bytes(), b'new modules')
        self.assertEqual((self.root / f'usr/lib/modules/{NEW}/modules.dep').read_bytes(), b'current modules')
        for name in ('boot/vmlinuz-t825', 'boot/initramfs-t825', DTB):
            self.assertEqual((self.root / name).read_bytes(), previous[name])

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
