#!/usr/bin/env python3
"""Prepare an extracted normal initramfs for a read-only, direct-root RAM test.

This changes host files only. Use a fresh extraction of a trusted normal build;
MSS images, existing hooks and drifted init scripts are rejected. Preparation
does not establish on-device handoff or autonomous recovery acceptance.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import shutil

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "diagnostic_guard", REPO / "install/guard-t825-diagnostic-root.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"initramfs anchor changed: {old!r}")
    return text.replace(old, new, 1)


def transform(init2: str, functions: str) -> tuple[str, str]:
    if "t825." in init2 or "t825." in functions:
        raise ValueError("use an unmodified normal initramfs")
    init2, functions = guard.guard(init2, functions, True)
    # Refuse every repair entry point, including a later unexpected caller.
    functions, count = re.subn(
        r"^check_filesystem\(\) \{\n.*?^\}",
        'check_filesystem() {\n\techo "RAM diagnostic refuses filesystem repair"\n'
        '\tfail_halt_boot\n}', functions, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise ValueError("filesystem repair function changed")
    functions = replace_once(
        functions,
        '\tmount -t tmpfs -o nosuid,nodev,mode=0755 run /run || echo "Couldn\'t mount /run"\n',
        '\tmount -t tmpfs -o nosuid,nodev,mode=0755 run /run || fail_halt_boot\n'
        '\t/bin/busybox ash /usr/local/libexec/t825-recovery-arm || fail_halt_boot\n')
    # Preserve the existing NCM gadget through the inspection shell and pivot.
    functions = replace_once(
        functions,
        '\tif [ -n "$have_udc" ]; then\n\t\tsetup_usb_acm_configfs\n'
        '\telse\n\t\tstart_unudhcpd\n\tfi\n',
        '\tstart_unudhcpd\n')
    functions = replace_once(
        functions,
        '\t# Remove the ACM/mass storage gadget devices\n'
        '\t# FIXME: would be nice to have a way to keep this on and\n'
        '\t# pipe kernel/init logs to it.\n'
        '\trm -f $CONFIGFS/g1/configs/c.1/"$CONFIGFS_ACM_FUNCTION"\n'
        '\trmdir $CONFIGFS/g1/functions/"$CONFIGFS_ACM_FUNCTION"\n'
        '\trm -f "$CONFIGFS/g1/configs/c.1/$CONFIGFS_MASS_STORAGE_FUNCTION"\n'
        '\trmdir "$CONFIGFS/g1/functions/$CONFIGFS_MASS_STORAGE_FUNCTION"\n'
        '\tsetup_usb_configfs_udc\n',
        '\t# RAM diagnostic preserves the inherited USB gadget.\n')
    init2 = replace_once(init2, '\ncheck_keys\n', '\n# RAM diagnostic skips physical-key boot selection.\n')
    init2 = replace_once(init2, '\nmount_subpartitions\n', '\n# RAM diagnostic uses the explicit root UUID.\n')
    init2 = replace_once(
        init2, 'setup_dynamic_partitions "${deviceinfo_super_partitions:=}"\n',
        '# RAM diagnostic does not set up Android dynamic partitions.\n')
    init2 = replace_once(
        init2,
        'if [ -z "$(cat /sysroot/etc/fstab | grep -v "#" | tr -d \'[:space:]\')" ]; then\n'
        '\twait_boot_partition\n\t: # Diagnostic boot skips installed boot mount\nfi\n',
        '# RAM diagnostic never waits for or mounts the installed boot volume.\n')
    init2 = replace_once(init2, 'init="/sbin/init"\nsetup_bootchart2\n',
                         'init="/run/t825-recovery/postpivot-init"\n')
    init2 = replace_once(init2, 'killall udevd syslogd unudhcpd', 'killall udevd syslogd')
    # Upstream run_hooks does not propagate an individual hook failure.
    init2 = replace_once(
        init2, 'run_hooks /hooks-cleanup\n',
        'busybox ash /hooks-cleanup/90-t825-readonly-runtime.sh || fail_halt_boot\n')
    return init2, functions


CLEANUP = '''#!/bin/ash
set -eu
test -s /run/t825-recovery/supervisor.pid
kill -0 "$(cat /run/t825-recovery/supervisor.pid)"
cp /usr/local/libexec/t825-direct-init /run/t825-recovery/postpivot-init
cp /usr/local/sbin/t825-usb-gadget /run/t825-recovery/usb-gadget
cp /usr/lib/t825-diagnostic/authorized_keys /run/t825-recovery/authorized_keys
# Copy before switch_root deletes the old initramfs. A bind from that root
# alone would not preserve directory entries deleted by switch_root.
cp -a /usr/lib/modules /run/t825-recovery/modules
test -d /sysroot/usr/lib/modules
mount --bind /run/t825-recovery/modules /sysroot/usr/lib/modules
mount -o remount,bind,ro /sysroot/usr/lib/modules
mount --move /run /sysroot/run
'''


def prepare(tree: Path, supervisor: Path, public_key: Path, release: str) -> None:
    tree = tree.resolve()
    if not re.fullmatch(r"7\.3\.1-t825(?:-audiodiag)?", release):
        raise ValueError("only normal or audio-diagnostic module releases are supported")
    # Reject host-escaping archive symlinks before writing through merged /usr.
    for path in tree.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(tree):
            raise ValueError(f"archive symlink escapes extraction root: {path}")
    for name in ("hooks", "hooks-extra", "hooks-cleanup"):
        folder = tree / name
        if folder.exists() and any(folder.iterdir()):
            raise ValueError(f"normal input must not contain hooks: {name}")
    releases = sorted(p.name for p in (tree / "usr/lib/modules").iterdir() if p.is_dir())
    if releases != [release]:
        raise ValueError(f"module release mismatch: {releases!r}")
    init2 = tree / "init_2nd.sh"
    functions = tree / "init_functions.sh"
    changed_init2, changed_functions = transform(init2.read_text(), functions.read_text())
    # All drift checks finish before the first mutation of the extraction.
    init2.write_text(changed_init2)
    functions.write_text(changed_functions)
    files = {
        "usr/local/libexec/t825-recovery-supervisor": supervisor,
        "usr/local/libexec/t825-recovery-arm": REPO / "install/t825-recovery-arm.sh",
        "usr/local/libexec/t825-direct-init": REPO / "rootfs/files/t825-direct-init",
        "usr/local/sbin/t825-usb-gadget": REPO / "rootfs/files/t825-usb-gadget",
        "usr/lib/t825-diagnostic/authorized_keys": public_key,
    }
    for target, source in files.items():
        destination = tree / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o644 if target.endswith("authorized_keys") else 0o755)
    hook = tree / "hooks-cleanup/90-t825-readonly-runtime.sh"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(CLEANUP)
    hook.chmod(0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree", type=Path)
    parser.add_argument("--supervisor", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    prepare(args.tree, args.supervisor, args.public_key, args.release)


if __name__ == "__main__":
    main()
