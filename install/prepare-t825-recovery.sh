#!/usr/bin/env bash
# Install the supervisor into a host build root and arm it before stage 2.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
rootfs=${1:?usage: prepare-t825-recovery.sh BUILD_ROOT}
[ -f "$rootfs/usr/share/initramfs/init.sh" ] || exit 2
binary=$(mktemp)
trap 'unlink "$binary"' EXIT
"$here/tools/build-t825-recovery-supervisor.sh" "$binary"
sudo install -Dm755 "$binary" "$rootfs/usr/local/libexec/t825-recovery-supervisor"
sudo install -Dm755 "$here/install/t825-recovery-arm.sh" "$rootfs/usr/local/libexec/t825-recovery-arm"
sudo python3 - "$rootfs/usr/share/initramfs" <<'PY'
from pathlib import Path
import sys
folder = Path(sys.argv[1])
call = '/bin/busybox ash /usr/local/libexec/t825-recovery-arm || fail_halt_boot\n'
# Remove the earlier insertion after mount_proc_sys_dev: that function also
# loads libcomposite and mounts configfs, either of which can block first.
init = folder / 'init.sh'
text = init.read_text()
if call in text:
    init.write_text(text.replace(call, ''))
path = folder / 'init_functions.sh'
text = path.read_text()
anchor = '\tmount -t tmpfs -o nosuid,nodev,mode=0755 run /run || echo "Couldn\'t mount /run"\n'
if call not in text:
    if text.count(anchor) != 1:
        raise SystemExit('initramfs mounting anchor changed; refusing unprotected image')
    text = text.replace(anchor, anchor + '\t' + call, 1)
    path.write_text(text)
PY
sudo install -d "$rootfs/etc/mkinitfs/files"
sudo install -m644 /dev/stdin "$rootfs/etc/mkinitfs/files/00-t825-recovery.files" <<'FILES'
/usr/local/libexec/t825-recovery-supervisor
/usr/local/libexec/t825-recovery-arm
FILES
