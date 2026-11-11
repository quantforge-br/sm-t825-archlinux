#!/usr/bin/env python3
"""Prevent installer mutations and use a read-only root for direct diagnosis."""
from pathlib import Path
import re
import sys


def protect_root_mount(functions: str) -> str:
    """Protect the block device before mounting; never fall back to RW."""
    marker = '# T825 diagnostic root: block writes and journal replay'
    if marker in functions:
        return functions
    match = re.search(r'^mount_root_partition\(\) \{\n.*?^\}', functions,
                      re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError('root mount function changed')
    body = match[0]
    anchor = '\tif ! mount -t "$type" -o rw"$rootfsopts" "$partition" /sysroot; then\n'
    if body.count(anchor) != 1:
        raise ValueError('root mount options changed')
    protection = '''\t# T825 diagnostic root: block writes and journal replay
\tlocal t825_root_mountopts t825_root_uuid t825_root_devices t825_root_device
\tcase ",$rootfsopts," in
\t\t*,rw,*) echo "Diagnostic root refuses rw rootfsopts"; fail_halt_boot ;;
\tesac
\tcase "$type" in
\t\tbtrfs) t825_root_mountopts=ro,rescue=nologreplay ;;
\t\text4) t825_root_mountopts=ro,noload ;;
\t\t*) echo "No validated read-only diagnostic mode for $type"; fail_halt_boot ;;
\tesac
\t# This tablet's Btrfs spans system and userdata. Protect every member
\t# matching the filesystem UUID, including the selected root device.
\tt825_root_uuid=$(blkid -s UUID -o value "$partition") || fail_halt_boot
\t[ -n "$t825_root_uuid" ] || fail_halt_boot
\tt825_root_devices="$partition $(blkid -c /dev/null -t UUID="$t825_root_uuid" -o device)" || fail_halt_boot
\tfor t825_root_device in $t825_root_devices; do
\t\tbusybox blockdev --setro "$t825_root_device" || fail_halt_boot
\t\t[ "$(busybox blockdev --getro "$t825_root_device")" = 1 ] || fail_halt_boot
\tdone

'''
    body = body.replace(anchor, protection + anchor, 1)
    body = body.replace('-o rw"$rootfsopts"', '-o "$t825_root_mountopts$rootfsopts"')
    body = body.replace('(read-write)', '(read-only, no journal replay)')
    return functions[:match.start()] + body + functions[match.end():]


def guard(init2: str, functions: str, direct: bool) -> tuple[str, str]:
    for call in ('delete_old_install_partition', 'resize_root_partition',
                 'resize_root_filesystem', 'resize_filesystem_after_mount /sysroot'):
        original = call + '\n'
        replacement = ': # Diagnostic boot skips ' + call + '\n'
        if replacement in init2:
            continue
        if init2.count(original) != 1:
            raise ValueError(f'diagnostic root anchor changed: {call}')
        init2 = init2.replace(original, replacement, 1)
    if direct:
        functions = protect_root_mount(functions)
        # The transient direct init has no need for the installed boot volume.
        # Even an ext4 read-only mount can replay its journal without noload.
        for mode in ('rw', 'ro'):
            init2 = init2.replace(f'mount_boot_partition /sysroot/boot "{mode}"',
                                  ': # Diagnostic boot skips installed boot mount')
        # Keep a second check at the transition; the initial mount is already
        # read-only and the backing block device rejects writes for this boot.
        marker = 'mount_root_partition\n'
        if 'mount -o remount,ro /sysroot || fail_halt_boot' not in init2:
            if init2.count(marker) != 1:
                raise ValueError('root mount anchor changed')
            init2 = init2.replace(marker,
                                  marker + 'mount -o remount,ro /sysroot || fail_halt_boot\n', 1)
    return init2, functions


if __name__ == '__main__':
    init2, functions = map(Path, sys.argv[1:3])
    a, b = guard(init2.read_text(), functions.read_text(), sys.argv[3] == '1')
    init2.write_text(a)
    functions.write_text(b)
