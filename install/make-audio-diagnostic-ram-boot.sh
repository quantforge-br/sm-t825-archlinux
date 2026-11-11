#!/usr/bin/env bash
# Build an unaccepted audio-instrumentation RAM candidate from a read-only root.
# This is host-only and never boots or writes a tablet partition.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
normal=${1:?usage: make-audio-diagnostic-ram-boot.sh NORMAL_CANDIDATE AUDIO_BUILD OUTPUT}
audio_build=${2:?audio build tree required}
out=${3:?output directory required}
expected=${T825_EXPECTED_NORMAL_IMAGE_SHA256:?pin normal candidate image SHA256}
root_uuid=${T825_ROOT_UUID:?root UUID required}
root_opts=${T825_ROOTFSOPTS:?root options required}
transaction_diag=${T825_SLIM_TRANSACTION_DIAGNOSTICS:-0}
channel_removal=${T825_NGD_CHANNEL_REMOVAL:-0}
event_trace=${T825_AUDIO_EVENT_TRACE:-0}
rcg_trace=${T825_RCG_UPDATE_TRACE:-0}
case "$transaction_diag" in 0|1) ;; *) echo 'invalid transaction diagnostic opt-in' >&2; exit 2 ;; esac
case "$channel_removal" in 0|1) ;; *) echo 'invalid channel removal opt-in' >&2; exit 2 ;; esac
case "$event_trace" in 0|1) ;; *) echo 'invalid audio event trace opt-in' >&2; exit 2 ;; esac
case "$rcg_trace" in 0|1) ;; *) echo 'invalid RCG update trace opt-in' >&2; exit 2 ;; esac
if [ "$channel_removal" = 1 ] && [ "$transaction_diag" != 1 ]; then
	echo 'channel removal requires transaction diagnostics' >&2; exit 2
fi
if [ "$event_trace" = 1 ] && [ "$transaction_diag" != 1 ]; then
	echo 'audio event trace requires transaction diagnostics' >&2; exit 2
fi
transaction_cmdline=
if [ "$transaction_diag" = 1 ]; then
	transaction_cmdline='slimbus.transaction_diagnostics=1'
fi
if [ "$channel_removal" = 1 ]; then
	transaction_cmdline="$transaction_cmdline slim_qcom_ngd_ctrl.channel_removal=1"
fi
if [ "$event_trace" = 1 ]; then
	transaction_cmdline="$transaction_cmdline slimbus.event_trace=1"
fi
if [ "$rcg_trace" = 1 ]; then
	# Built-in clk_qcom parameter; the kernel must carry the diagnostic patch.
	transaction_cmdline="$transaction_cmdline clk_qcom.rcg_update_trace=1"
fi
[ -f "$normal/initramfs" ] && [ -f "$normal/t825-readonly-ram.img" ] || { echo 'normal candidate incomplete' >&2; exit 2; }
[ -f "$audio_build/out/arch/arm64/boot/Image.gz" ] || { echo 'audio Image.gz missing' >&2; exit 2; }
[ -d "$audio_build/mod-install/lib/modules/7.3.1-t825-audiodiag" ] || { echo 'audio modules missing' >&2; exit 2; }
mkdir -p "$out"; out=$(realpath "$out")
sha256sum "$normal/t825-readonly-ram.img" | awk -v e="$expected" '$1 == e {ok=1} END {exit !ok}'
unzstd -c "$normal/initramfs" | (mkdir "$out/root"; cd "$out/root"; cpio -id --quiet --no-absolute-filenames)
python3 - "$out/root" "$audio_build/mod-install/lib/modules/7.3.1-t825-audiodiag" <<'PY'
from pathlib import Path
import shutil, sys
root, source = map(Path, sys.argv[1:])
old = root/'usr/lib/modules/7.3.1-t825'
old_names = [p.relative_to(old) for p in old.rglob('*.ko.zst')]
modroot = source
text = (modroot/'modules.dep').read_text().splitlines()
dep = {}
for line in text:
    if ':' not in line: continue
    key, values = line.split(':',1)
    dep[key] = [x for x in values.split() if x]
seeds = set(str(x) for x in old_names)
seeds.update({
 'kernel/sound/soc/codecs/snd-soc-wcd9335.ko.zst',
 'kernel/sound/soc/codecs/snd-soc-rt5508.ko.zst',
 'kernel/sound/soc/qcom/snd-soc-apq8096.ko.zst',
 'kernel/sound/soc/qcom/qdsp6/q6asm-dai.ko.zst',
 'kernel/sound/soc/qcom/qdsp6/q6afe-dai.ko.zst',
 'kernel/drivers/remoteproc/qcom_q6v5_pas.ko.zst',
 'kernel/drivers/slimbus/slim-qcom-ngd-ctrl.ko.zst',
})
needed = set()
stack = list(seeds)
while stack:
    item = stack.pop()
    if item in needed: continue
    needed.add(item); stack.extend(dep.get(item, []))
missing = sorted(x for x in needed if not (modroot/x).is_file())
if missing: raise SystemExit('missing audio module closure: '+repr(missing[:10]))
if old.exists(): shutil.rmtree(old)
dst = root/'usr/lib/modules/7.3.1-t825-audiodiag'; dst.mkdir(parents=True)
for rel in needed:
    target = dst/rel; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(modroot/rel, target)
for name in ('modules.order', 'modules.builtin', 'modules.builtin.modinfo'):
    shutil.copy2(modroot/name, dst/name)
PY
# Regenerate metadata for the selected closure only.
depmod -b "$out/root" 7.3.1-t825-audiodiag
cp "$audio_build/out/arch/arm64/boot/Image.gz" "$out/vmlinuz"
mkdir -p "$out/dtbs/qcom"
cp "$audio_build/out/arch/arm64/boot/dts/qcom/apq8096-samsung-gts3lwifi.dtb" "$out/dtbs/qcom/"
cp "$audio_build/out/arch/arm64/boot/dts/qcom/msm8996-samsung-gts3llte.dtb" "$out/dtbs/qcom/"
fdtget -t s "$out/dtbs/qcom/msm8996-samsung-gts3llte.dtb" /soc/remoteproc@2080000 status | grep -qx disabled
(cd "$out/root" && find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --owner=0:0 2>/dev/null) | zstd -q -T1 -o "$out/initramfs"
KERNEL="$out/vmlinuz" INITRAMFS="$out/initramfs" DTB_DIR="$out/dtbs" \
 CMDLINE_EXTRA="t825.ramdiag t825.direct-init panic=10 pmos.debug-shell snd_soc_wcd9335.port_diagnostics=1 $transaction_cmdline pmos_root_uuid=$root_uuid pmos_rootfsopts=$root_opts" \
 "$here/install/make-boot-image.sh" "$out/t825-audiodiag-ram.img"
printf '%s\n' 'UNACCEPTED: audio instrumentation; no tablet boot performed' > "$out/NOT_ACCEPTED"
# The validator checks the manifest before reporting success. Pin the payload
# first; append generated validation/decision hashes only after validation.
(cd "$out" && sha256sum t825-audiodiag-ram.img vmlinuz initramfs dtbs/qcom/*.dtb > SHA256SUMS)
# Packing a valid Android header does not establish the lk2nd memory budget,
# module identity or read-only handoff invariants. Refuse before publishing a
# successful decision if the assembled image fails the independent validator.
python3 "$here/tools/test-t825-audiodiag-ram-image.py" "$out" > "$out/validation.json"
cat > "$out/decision.json" <<JSON
{
  "status": "OFFLINE_AUDIO_IMAGE_PASS_NOT_BOOT_ACCEPTANCE",
  "kernel_release": "7.3.1-t825-audiodiag",
  "module_parameter": "snd_soc_wcd9335.port_diagnostics=1",
  "transaction_diagnostics_requested": $transaction_diag,
  "channel_removal_requested": $channel_removal,
  "event_trace_requested": $event_trace,
  "rcg_update_trace_requested": $rcg_trace,
  "mss": "disabled on samsung,gts3llte",
  "normal_candidate_sha256": "$expected",
  "scope": "read-only direct-root candidate; no tablet load or audio stream",
  "remaining": ["nonpersistent handoff execution", "supervisor/reset observation", "audio hardware capture"]
}
JSON
(cd "$out" && sha256sum t825-audiodiag-ram.img vmlinuz initramfs dtbs/qcom/*.dtb decision.json validation.json > SHA256SUMS)
printf '%s\n' "Prepared unaccepted audio candidate: $out"
