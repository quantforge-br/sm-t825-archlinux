#!/bin/bash
# Run on the tablet as its desktop user; sudo -n is used only for privileged reads.
# Usage: install/collect-kernel-baseline.sh [NEW-output-directory]
# No firmware, calibration, microphone recordings or camera images are copied.
# shellcheck disable=SC2016,SC2094
set -euo pipefail
umask 077
if [[ ${1:-} == --help ]]; then
    echo "Usage: $0 [NEW-output-directory] (run as the desktop user)"
    exit 0
fi
for cmd in timeout realpath mkdir date sha256sum find sort; do
    command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done
out=$(realpath -m -- "${1:-$HOME/t825-runs/$(date -u +%Y%m%dT%H%M%SZ)-baseline}")
mkdir -p -- "$(dirname -- "$out")"
# Refuse reuse, including symlinks, so an old run can never masquerade as this one.
mkdir -m 700 -- "$out" || { echo "output must be a NEW directory: $out" >&2; exit 1; }
priv=()
if (( EUID != 0 )); then priv=(sudo -n); fi
session_user=${SUDO_USER:-$(id -un)}
session_uid=$(id -u "$session_user")
session=(env "XDG_RUNTIME_DIR=/run/user/$session_uid" "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$session_uid/bus")
if (( EUID == 0 && session_uid != 0 )); then
    session=(runuser -u "$session_user" -- "${session[@]}")
fi
printf 'file\texit_code\tstatus\n' > "$out/commands.tsv"
run() {
    local name=$1 rc status
    shift
    if timeout --kill-after=2s 30s "$@" >"$out/$name" 2>&1; then
        rc=0; status=COLLECTED
    else
        rc=$?
        case $rc in
            77|126|127) status=UNAVAILABLE;;
            124|137) status=TIMEOUT;;
            *) status=ERROR;;
        esac
    fi
    printf '%s\t%s\t%s\n' "$name" "$rc" "$status" >> "$out/commands.tsv"
}
run uname.txt uname -a
run version.txt cat /proc/version
run cmdline.txt cat /proc/cmdline
run boot-id.txt cat /proc/sys/kernel/random/boot_id
run model.txt bash -c 'tr "\0" "\n" </proc/device-tree/model'
run uts-release.txt uname -r
run config.txt bash -o pipefail -c 'if [[ -r /proc/config.gz ]]; then gzip -dc /proc/config.gz; elif [[ -r /boot/config-$(uname -r) ]]; then cat "/boot/config-$(uname -r)"; else echo unavailable >&2; exit 77; fi'
run dmesg.txt "${priv[@]}" dmesg
run kernel-journal.txt "${priv[@]}" journalctl -b -k --no-pager -o short-monotonic
run lsmod.txt lsmod
run mounts.txt findmnt -rn
run boot-files.txt "${priv[@]}" bash -o pipefail -c 'find /boot -maxdepth 4 -type f -printf "%p %s\n" | sort'
run extlinux.conf "${priv[@]}" cat /boot/extlinux/extlinux.conf
run boot-hashes.txt "${priv[@]}" sha256sum /boot/vmlinuz-t825 /boot/initramfs-t825 /boot/dtbs/qcom/msm8996-samsung-gts3llte.dtb
run modules.txt bash -o pipefail -c 'find "/usr/lib/modules/$(uname -r)" -maxdepth 1 -type f -printf "%f %s\n" | sort'
# These checks distinguish a runtime config/module set from a merely matching name.
run module-vermagic.txt bash -c 'for m in msm ath10k_pci snd_soc_wcd9335 qcom_q6v5_pas; do printf "%s: " "$m"; modinfo -F vermagic "$m" || exit; done'
run device-tree.tar "${priv[@]}" tar -C /sys/firmware/devicetree/base -cf - .
run fdt.bin "${priv[@]}" cat /sys/firmware/fdt
run remoteproc.txt bash -c 'shopt -s nullglob; for d in /sys/class/remoteproc/remoteproc*; do for a in name state firmware; do [[ -f "$d/$a" ]] || continue; printf "%s=" "$d/$a"; cat "$d/$a" || exit; done; done'
run services.txt systemctl --no-pager --plain --type=service --state=running
run network.txt ip -brief address
run wireless.txt iw dev
run regulatory.txt iw reg get
run rfkill.txt rfkill list
run bluetooth.txt bluetoothctl show
run audio.txt "${session[@]}" wpctl status
run audio-alsa.txt aplay -l
run audio-capture-devices.txt arecord -l
run cameras.txt cam -l
run video-devices.txt v4l2-ctl --list-devices
run sensors.txt bash -c 'shopt -s nullglob; for d in /sys/bus/iio/devices/iio:device*; do for a in name in_accel_sampling_frequency in_anglvel_sampling_frequency in_magn_sampling_frequency in_accel_mount_matrix in_accel_x_raw in_accel_y_raw in_accel_z_raw in_illuminance_input; do [[ -f "$d/$a" ]] || continue; printf "%s=" "$d/$a"; cat "$d/$a" || exit; done; done'
run power.txt bash -c 'cat /sys/power/mem_sleep || exit; shopt -s nullglob; for d in /sys/class/power_supply/*; do for a in type status capacity temp online voltage_now current_now; do [[ -f "$d/$a" ]] || continue; printf "%s=" "$d/$a"; cat "$d/$a" || exit; done; done'
run thermal.txt bash -c 'shopt -s nullglob; for d in /sys/class/thermal/thermal_zone*; do printf "%s " "$d"; cat "$d/type" "$d/temp" || exit; done'
run drm.txt bash -c 'shopt -s nullglob; for f in /sys/class/drm/card*-*/{status,modes}; do [[ -f "$f" ]] || continue; printf "[%s]\n" "$f"; cat "$f" || exit; done'
run clocks.txt bash -c 'shopt -s nullglob; for f in /sys/class/devfreq/*/{governor,cur_freq,min_freq,max_freq} /sys/devices/system/cpu/cpufreq/policy*/{scaling_governor,scaling_cur_freq,scaling_min_freq,scaling_max_freq}; do [[ -f "$f" ]] || continue; printf "%s=" "$f"; cat "$f" || exit; done'
run versions.txt bash -c 'for p in mesa hyprland pipewire wireplumber bluez libcamera; do pacman -Q "$p" || exit; done'
collector_sha=unavailable
if [[ -f $0 ]]; then
    collector_sha=$(sha256sum -- "$0" | cut -d' ' -f1)
fi
{
    printf 'collected_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'hostname=%s\n' "$(uname -n)"
    printf 'desktop_user=%s\n' "$session_user"
    printf 'collector_sha256=%s\n' "$collector_sha"
    printf 'private=yes\n'
    printf 'scope=read-only-enumeration-not-functional-validation\n'
} > "$out/MANIFEST"
# Exclude SHA256SUMS itself; no self-referential/truncated checksum on repeated runs.
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
printf 'Private baseline: %s\n' "$out"
awk -F '\t' 'NR>1 && $3!="COLLECTED" {print $1 ": " $3 " (exit " $2 ")"}' "$out/commands.tsv"
