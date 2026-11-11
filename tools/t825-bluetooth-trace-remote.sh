#!/usr/bin/env bash
# Run only on the tablet, from a private /run snapshot and a bounded unit.
set -euo pipefail
export LC_ALL=C
mode=${1:?collect or restore}
report=${2:?private /run report}
case "$report" in /run/t825-bt-trace-[0-9]*) ;; *) exit 2 ;; esac
[ "$(id -u)" = 0 ] || exit 2
cd "$report"

restore() {
    if [ -f mask-owned ]; then
        systemctl unmask --runtime gts3-bdaddr.service || return
        systemctl daemon-reload || return
        rm -f mask-owned || return
    fi
    if [ -f serdev ]; then
        name=$(cat serdev)
        case "$name" in serial0-0) ;; *) return 2 ;; esac
        if [ ! -L "/sys/bus/serial/devices/$name/driver" ]; then
            printf '%s' "$name" > /sys/bus/serial/drivers/hci_uart_qca/bind || return
        fi
    fi
    systemctl reset-failed gts3-bdaddr.service || return
    systemctl start --no-block bluetooth.service gts3-bdaddr.service || return
    printf '%s\n' "$(date -u +%FT%TZ) restoration queued" >> restoration.log
}

# Keep every diagnostic command bounded.  A controller reset can leave a
# userspace query blocked while the independent restoration timer is still
# responsible for returning the normal service state.
bounded() {
    timeout --kill-after=2s 8 "$@"
}

snapshot_ibs() {
    local destination=$1
    local ibs=/sys/kernel/debug/bluetooth/hci0/ibs
    : > "$destination"
    if [ -d "$ibs" ]; then
        for file in "$ibs"/*; do
            [ -f "$file" ] || continue
            case "$(basename "$file")" in
                tx_idle_delay|wake_retrans|ibs_recv_wake_acks|ibs_recv_wakes|ibs_recv_sleeps|\
                ibs_sent_wake_acks|ibs_sent_wakes|ibs_sent_sleeps|tx_ibs_state|rx_ibs_state|\
                tx_vote|rx_vote|tx_votes_on|tx_votes_off|rx_votes_on|rx_votes_off|votes_on|votes_off|vote_on_ms|vote_off_ms)
                    printf '%s=' "$(basename "$file")" >> "$destination"
                    cat "$file" >> "$destination" 2>/dev/null || printf '<unreadable>\n' >> "$destination"
                    ;;
            esac
        done
    fi
}

if [ "$mode" = restore ]; then restore; exit; fi
[ "$mode" = collect ] || exit 2
umask 077
btmon_pid=''
ibs_pid=''
cleanup() {
    status=$?
    trap - EXIT
    set +e
    if [ -n "$ibs_pid" ]; then
        kill -TERM "$ibs_pid" 2>/dev/null || true
        wait "$ibs_pid"
        sampler_status=$?
        printf '%s\n' "$sampler_status" > ibs-sampler.status
        if [ "$sampler_status" != 0 ] || [ ! -s ibs-timeline.jsonl ]; then
            printf '%s\n' ibs_sampler_failed > classification
            status=1
        fi
    fi
    if [ -n "$btmon_pid" ]; then
        kill -TERM "$btmon_pid" 2>/dev/null || true
        wait "$btmon_pid" 2>/dev/null || true
    fi
    # Preserve failure evidence too, including a provisioning-readiness timeout.
    dmesg > kernel.after
    snapshot_ibs ibs.after
    sha256sum /usr/sbin/gts3-bdaddr /usr/lib/systemd/system/gts3-bdaddr.service > payload.after
    cat /proc/sys/kernel/random/boot_id > boot-id.after
    if ! cmp -s payload.before payload.after || ! cmp -s boot-id.before boot-id.after; then
        printf '%s\n' identity_changed > classification
        status=1
    fi
    python3 ./t825-bluetooth-trace-evidence.py kernel . > analysis.log 2>&1
    analysis_status=$?
    if [ "$analysis_status" != 0 ]; then
        if [ -s kernel.classification ]; then cat kernel.classification > classification;
        else printf '%s\n' kernel_analysis_failed > classification; fi
        status=1
    elif [ "$status" = 0 ]; then
        cat kernel.classification > classification
    fi
    restore >> restoration.log 2>&1
    restore_status=$?
    printf '%s\n' "$restore_status" > restoration.status
    if [ "$restore_status" != 0 ]; then status=1; fi
    printf '%s\n' "$status" > collection.status
    exit "$status"
}
trap cleanup EXIT
printf '%s\n' collection_failed > classification
cat /proc/sys/kernel/random/boot_id > boot-id.before
sha256sum /usr/sbin/gts3-bdaddr /usr/lib/systemd/system/gts3-bdaddr.service > payload.before
bounded btmgmt info > controller.before 2>&1
bounded bluetoothctl devices Connected > connections.before 2>&1
[ ! -s connections.before ] || { echo 'Refusing to interrupt a connected Bluetooth device'; exit 2; }
[ "$(systemctl is-enabled gts3-bdaddr.service)" != masked ] || exit 2
[ ! -e /run/systemd/system/gts3-bdaddr.service ] || exit 2
name=$(basename "$(readlink -f /sys/class/bluetooth/hci0/device)")
[ "$name" = serial0-0 ] || exit 2
[ "$(readlink -f /sys/bus/serial/devices/serial0-0/driver)" = /sys/bus/serial/drivers/hci_uart_qca ] || exit 2
printf '%s\n' "$name" > serdev
cp /usr/sbin/gts3-bdaddr helper.snapshot
sha256sum helper.snapshot "$0" ./t825-bluetooth-trace-evidence.py ./t825-bluetooth-ibs-sample.py ./t825-validate.py > runner.sha256
dmesg > kernel.before
snapshot_ibs ibs.before
python3 ./t825-bluetooth-ibs-sample.py --seconds 115 > ibs-timeline.jsonl 2> ibs-sampler.stderr &
ibs_pid=$!
btmon -T -K -C 200 -c never -w trace.btsnoop > trace.txt 2>&1 &
btmon_pid=$!
sleep 1
kill -0 "$btmon_pid"
kill -0 "$ibs_pid"
systemctl stop gts3-bdaddr.service
touch mask-owned
systemctl mask --runtime gts3-bdaddr.service
printf '%s\n' "$(cut -d' ' -f1 /proc/uptime) unbind" >> stages.txt
printf '%s' "$name" > /sys/bus/serial/drivers/hci_uart_qca/unbind
sleep 2
printf '%s\n' "$(cut -d' ' -f1 /proc/uptime) bind" >> stages.txt
printf '%s' "$name" > /sys/bus/serial/drivers/hci_uart_qca/bind
# Wait for the unconfigured options stanza, not a primary controller: the EFS
# address must be provisioned before primary-controller enumeration can occur.
readiness_deadline=$((SECONDS+15))
ready=0
while [ "$SECONDS" -lt "$readiness_deadline" ]; do
    # info uses READ_INDEX_LIST (configured only). config requests
    # READ_UNCONF_INDEX_LIST and READ_CONFIG_INFO, including missing options.
    query_status=0
    timeout --kill-after=1s 2 btmgmt config > controller.unconfigured 2>&1 || query_status=$?
    printf '%s\n' "$(cut -d' ' -f1 /proc/uptime) config status=$query_status" >> readiness.log
    cat controller.unconfigured >> readiness.log
    if [ "$query_status" = 0 ] && python3 ./t825-bluetooth-trace-evidence.py ready controller.unconfigured; then ready=1; break; fi
    sleep 1
done
if [ "$ready" != 1 ]; then
    printf '%s\n' provisioning_readiness_timeout > classification
    exit 1
fi
printf '%s\n' "$(cut -d' ' -f1 /proc/uptime) helper" >> stages.txt
helper_status=0
timeout --kill-after=3s 80 /bin/sh ./helper.snapshot > helper.log 2>&1 || helper_status=$?
printf '%s\n' "$helper_status" > helper.status
printf '%s\n' "$(cut -d' ' -f1 /proc/uptime) helper-finished" >> stages.txt
bounded btmgmt info > controller.after 2>&1 || true
bounded bluetoothctl show > bluez.after 2>&1 || true
[ "$helper_status" = 0 ]
grep -q '^hci0:.*Primary controller' controller.after
grep -q '^Controller ' bluez.after
