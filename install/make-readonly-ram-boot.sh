#!/usr/bin/env bash
# Build a direct-root recovery candidate from a hash-pinned normal RAM bundle.
# This only prepares host files. It never connects to or boots the tablet.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
bundle=$(realpath "${1:?usage: make-readonly-ram-boot.sh NORMAL_BUNDLE OUTPUT_DIRECTORY}")
out=${2:?output directory required}
: "${T825_EXPECTED_BASE_SHA256:?pin the normal source image SHA256}"
: "${T825_ROOT_UUID:?supply the observed installed root UUID}"
: "${T825_ROOTFSOPTS:?supply the observed installed root options}"
public_key=${T825_DIAGNOSTIC_SSH_PUBLIC_KEY:-$HOME/.ssh/id_ed25519.pub}
base=$bundle/t825-normal-r2.img
kernel=$bundle/boot/vmlinuz
dtbs=$bundle/boot/dtbs
initramfs=$bundle/initramfs
[ ! -e "$out" ] || { echo 'Use a fresh output directory' >&2; exit 2; }
umask 077
mkdir -p "$out"
out=$(realpath "$out")
printf '%s\n' 'UNVALIDATED: do not boot before archive review and independent recovery planning' > "$out/NOT_ACCEPTED"
ssh-keygen -l -f "$public_key" > "$out/public-key-fingerprint.txt"
# Bind the archive, kernel and both DTBs to the same known normal boot image.
python3 - "$base" "$T825_EXPECTED_BASE_SHA256" "$kernel" "$initramfs" "$dtbs" \
    "$T825_ROOT_UUID" "$T825_ROOTFSOPTS" > "$out/base-check.json" <<'PY'
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
base, expected, kernel, archive, dtbs, uuid, opts = sys.argv[1:]
image = Path(base).read_bytes()
assert re.fullmatch('[a-f0-9]{64}', expected), 'invalid expected SHA256'
assert hashlib.sha256(image).hexdigest() == expected, 'normal image hash mismatch'
assert image[:8] == b'ANDROID!', 'not an Android boot image'
ksize, _, rsize, _, second, _, _, page, version, _ = struct.unpack_from('<10I', image, 8)
assert page == 4096 and second == 0 and version == 0, 'unsupported boot header'
ram_offset = ((page + ksize + page - 1) // page) * page
assert image[ram_offset:ram_offset+rsize] == Path(archive).read_bytes(), 'base archive mismatch'
payload = Path(kernel).read_bytes()
states = {}
for name in ('apq8096-samsung-gts3lwifi.dtb', 'msm8996-samsung-gts3llte.dtb'):
    path = Path(dtbs) / 'qcom' / name
    state = subprocess.run(['fdtget', '-t', 's', str(path), '/soc/remoteproc@2080000', 'status'],
                           check=True, capture_output=True, text=True).stdout.strip()
    states[name] = state
    if name == 'msm8996-samsung-gts3llte.dtb':
        assert state == 'disabled', 'normal SM-T825 input must keep MSS disabled'
    payload += path.read_bytes()
assert image[page:page+ksize] == payload, 'kernel/DTB set differs from pinned normal image'
banner = re.search(rb'Linux version [^\x00\n]+', gzip.decompress(Path(kernel).read_bytes()))
assert banner and banner[0].startswith(b'Linux version 7.3.1-t825 '), 'not the normal kernel'
assert re.fullmatch('[a-fA-F0-9-]{36}', uuid), 'invalid root UUID'
assert opts.startswith('subvol=/@,') and re.fullmatch('[a-zA-Z0-9_/@,:=.-]+', opts), 'unsupported root options'
assert 'rw' not in opts.split(','), 'writable root options forbidden'
print(json.dumps({'status': 'PASS', 'source_image_sha256': expected,
                  'kernel_banner': banner[0].decode(), 'MSS_by_dtb': states,
                  'hardware_scope': 'SM-T825 samsung,gts3llte only',
                  'root_uuid': uuid, 'root_options': opts}, indent=2))
PY
mkdir "$out/root"
# The hash-pinned private source archive is trusted build input, not an
# arbitrary downloaded cpio. The preparer rejects escaping symlinks as well.
unzstd -c "$initramfs" | (cd "$out/root" && cpio -id --quiet --no-absolute-filenames)
"$here/tools/build-t825-recovery-supervisor.sh" "$out/supervisor"
python3 "$here/install/prepare-t825-readonly-initramfs.py" "$out/root" \
    --supervisor "$out/supervisor" --public-key "$public_key" --release 7.3.1-t825
mkdir -p "$out/dtbs/qcom"
cp "$kernel" "$out/vmlinuz"
cp "$dtbs/qcom/apq8096-samsung-gts3lwifi.dtb" \
    "$dtbs/qcom/msm8996-samsung-gts3llte.dtb" "$out/dtbs/qcom/"
(cd "$out/root" && find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --owner=0:0 2>/dev/null) |
    zstd -q -T1 -o "$out/initramfs"
python3 - "$out/vmlinuz" "$out/initramfs" > "$out/memory-budget.json" <<'PY'
import gzip
import json
from pathlib import Path
import sys
kernel = len(gzip.decompress(Path(sys.argv[1]).read_bytes()))
ramdisk = Path(sys.argv[2]).stat().st_size
budget = (52428800 - ramdisk) // 4096 * 4096 - 2097152 - 32768
assert ramdisk < 52428800 and kernel <= budget, 'lk2nd memory budget exceeded'
print(json.dumps({'status': 'PASS', 'kernel_decompressed': kernel,
                  'initramfs': ramdisk, 'kernel_budget': budget,
                  'margin': budget-kernel}, indent=2))
PY
env -u PMOS_BOOT_UUID -u T825_MSS_DIAGNOSTIC_HOLD -u T825_MSS_DIAGNOSTIC_BOOT \
    KERNEL="$out/vmlinuz" INITRAMFS="$out/initramfs" DTB_DIR="$out/dtbs" \
    CMDLINE_EXTRA="t825.ramdiag t825.direct-init panic=10 pmos.debug-shell pmos_root_uuid=$T825_ROOT_UUID pmos_rootfsopts=$T825_ROOTFSOPTS" \
    "$here/install/make-boot-image.sh" "$out/t825-readonly-ram.img"
(cd "$out" && sha256sum t825-readonly-ram.img vmlinuz initramfs supervisor dtbs/qcom/*.dtb > SHA256SUMS)
echo "Prepared unaccepted read-only recovery candidate: $out"
