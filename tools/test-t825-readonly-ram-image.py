#!/usr/bin/env python3
"""Validate an SM-T825 read-only RAM candidate offline; never grant boot acceptance."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def extract(archive, destination):
    raw = subprocess.run(['unzstd', '-c', str(archive)], check=True, capture_output=True).stdout
    subprocess.run(['cpio', '-id', '--quiet', '--no-absolute-filenames'],
                   cwd=destination, input=raw, check=True)


def validate(bundle, source):
    require((bundle / 'NOT_ACCEPTED').is_file(), 'candidate must retain its unaccepted marker')
    baseline = json.loads((bundle / 'base-check.json').read_text())
    require(hashlib.sha256(source.read_bytes()).hexdigest() == baseline['source_image_sha256'],
            'pinned normal source image mismatch')
    subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=bundle,
                   check=True, capture_output=True, text=True)
    image = (bundle / 't825-readonly-ram.img').read_bytes()
    require(image[:8] == b'ANDROID!', 'wrong boot magic')
    ks, ka, rs, ra, ss, sa, ta, page, version, _ = struct.unpack_from('<10I', image, 8)
    require((ka, ra, ss, sa, ta, page, version) ==
            (0x80008000, 0x82200000, 0, 0x80F00000, 0x82000000, 4096, 0),
            'wrong boot header/address layout')
    kernel = (bundle / 'vmlinuz').read_bytes()
    dtbs = b''.join((bundle / 'dtbs/qcom' / name).read_bytes() for name in (
        'apq8096-samsung-gts3lwifi.dtb', 'msm8996-samsung-gts3llte.dtb'))
    require(image[page:page+ks] == kernel+dtbs, 'embedded kernel or DTBs differ')
    offset = (page+ks+page-1) // page * page
    require(image[offset:offset+rs] == (bundle / 'initramfs').read_bytes(), 'embedded archive differs')
    original = source.read_bytes()
    oks, _, _, _, _, _, _, opage, _, _ = struct.unpack_from('<10I', original, 8)
    require(original[opage:opage+oks] == kernel+dtbs, 'candidate changed normal kernel/DTB set')
    state = subprocess.run(['fdtget', '-t', 's',
                            str(bundle / 'dtbs/qcom/msm8996-samsung-gts3llte.dtb'),
                            '/soc/remoteproc@2080000', 'status'], check=True,
                           capture_output=True, text=True).stdout.strip()
    require(state == 'disabled', 'LTE MSS is enabled')
    cmdline = image[64:576].split(b'\0', 1)[0].decode()
    for word in ('t825.ramdiag', 't825.direct-init', 'panic=10', 'pmos.debug-shell',
                 'pmos_root_uuid='+baseline['root_uuid'],
                 'pmos_rootfsopts='+baseline['root_options']):
        require(word in cmdline.split(), f'missing command-line word: {word}')
    require('pmos_boot_uuid=' not in cmdline and 't825.mssdiag' not in cmdline,
            'unexpected installed-boot or MSS command line')
    raw_kernel = gzip.decompress(kernel)
    budget = (52428800-rs) // page * page - 2097152 - 32768
    require(len(raw_kernel) <= budget, 'lk2nd decompression budget exceeded')
    with tempfile.TemporaryDirectory(prefix='t825-readonly-archive-') as tmp:
        tree = Path(tmp)
        extract(bundle / 'initramfs', tree)
        init = (tree / 'init_2nd.sh').read_text()
        functions = (tree / 'init_functions.sh').read_text()
        for line in ('delete_old_install_partition', 'resize_root_partition',
                     'resize_root_filesystem', 'resize_filesystem_after_mount /sysroot'):
            require(line not in init.splitlines(), f'installer mutation remains: {line}')
        for command in ('e2fsck -p', 'fsck.f2fs -p', 'fsck.vfat -p', 'fsck.xfs -p'):
            require(command not in functions, 'filesystem auto-repair remains')
        require('mount_boot_partition /sysroot/boot' not in init and 'wait_boot_partition' not in init,
                'installed boot path remains active')
        require('init="/run/t825-recovery/postpivot-init"' in init and 'init="/sbin/init"' not in init,
                'PID 1 can enter the installed systemd/service configuration')
        require('exec switch_root /sysroot "$init"' in init, 'not a real root transition')
        require('busybox ash /hooks-cleanup/90-t825-readonly-runtime.sh || fail_halt_boot' in init,
                'cleanup failure does not halt the diagnostic')
        mount = re.search(r'^mount_root_partition\(\) \{\n.*?^\}', functions, re.M | re.S)[0]
        require('blkid -c /dev/null -t UUID="$t825_root_uuid" -o device' in mount,
                'not all Btrfs member devices are discovered')
        require('busybox blockdev --setro "$t825_root_device" || fail_halt_boot' in mount,
                'missing backing block-device protection')
        require('busybox blockdev --getro "$t825_root_device"' in mount, 'missing read-only verification')
        require('t825_root_mountopts=ro,rescue=nologreplay' in mount, 'Btrfs replay permitted')
        require(' -o rw' not in mount, 'root mount permits writes')
        require(mount.index('blockdev --getro') < mount.index('if ! mount'),
                'block-device verification happens after mount')
        early = functions.split('mount_proc_sys_dev() {', 1)[1].split('\n}', 1)[0]
        require(early.index('run /run || fail_halt_boot') < early.index('t825-recovery-arm') < early.index('modprobe'),
                'supervisor not armed immediately after /run')
        arm = (tree / 'usr/local/libexec/t825-recovery-arm').read_text()
        require('t825.ramdiag' in arm and 't825-recovery-supervisor 240' in arm,
                'generic recovery marker/deadline not handled')
        cleanup = (tree / 'hooks-cleanup/90-t825-readonly-runtime.sh').read_text()
        for command in ('kill -0 "$(cat /run/t825-recovery/supervisor.pid)"',
                        'cp -a /usr/lib/modules /run/t825-recovery/modules',
                        'mount --bind /run/t825-recovery/modules /sysroot/usr/lib/modules',
                        'mount -o remount,bind,ro /sysroot/usr/lib/modules',
                        'mount --move /run /sysroot/run'):
            require(command in cleanup, f'missing retained-runtime step: {command}')
        supervisor = tree / 'usr/local/libexec/t825-recovery-supervisor'
        elf = supervisor.read_bytes()
        require(elf[:4] == b'\x7fELF' and struct.unpack_from('<H', elf, 18)[0] == 183,
                'supervisor is not AArch64 ELF')
        require(elf == (bundle / 'supervisor').read_bytes(), 'supervisor copy differs')
        # Parse with the actual target shell. -n never executes the scripts.
        for script in ('init', 'init_2nd.sh', 'init_functions.sh',
                       'usr/local/libexec/t825-recovery-arm', 'usr/local/libexec/t825-direct-init',
                       'hooks-cleanup/90-t825-readonly-runtime.sh'):
            subprocess.run(['qemu-aarch64-static', '-L', str(tree),
                            str(tree / 'usr/bin/busybox'), 'ash', '-n', str(tree / script)],
                           check=True, capture_output=True, timeout=10)
        # This is exclusively the supervisor's no-reboot dry-run path.
        dry = tree / 'dry-run'
        dry.mkdir()
        subprocess.run(['qemu-aarch64-static', str(supervisor), '1', str(dry), '--dry-run'],
                       check=True, capture_output=True, timeout=5)
        require('dry-run: reboot suppressed' in (dry / 'supervisor.log').read_text(),
                'supervisor dry-run did not reach expiry')
    return {'status': 'OFFLINE_PASS_NOT_BOOT_ACCEPTANCE',
            'scope': 'SM-T825 only; direct PID 1 and SSH, no graphical session or audio-module acceptance',
            'image_sha256': hashlib.sha256(image).hexdigest(),
            'kernel_banner': baseline['kernel_banner'], 'cmdline': cmdline,
            'kernel_decompressed': len(raw_kernel), 'initramfs': rs,
            'kernel_budget': budget, 'margin': budget-len(raw_kernel),
            'remaining': ['On-device PID 1/SSH/read-only member verification',
                          'Original supervisor survival and observed final reset destination',
                          'Nonpersistent entry route from installed Linux',
                          'Hardware watchdog coverage for complete kernel/SoC stalls']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--source-image', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.bundle.resolve(), args.source_image.resolve()), indent=2))
