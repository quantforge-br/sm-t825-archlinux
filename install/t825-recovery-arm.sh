#!/bin/sh
# Called immediately after proc/sys/dev/run mounting, before stage 2 and udev.
set -eu
case " $(cat /proc/cmdline) " in
    *" t825.mssdiag.hold "*|*" t825.ramdiag "*) ;;
    *) exit 0 ;;
esac
mkdir -p /run/t825-recovery
# The binary uses CLOCK_BOOTTIME and open directory/procfs descriptors, so it
# survives switch_root and the initramfs's `pidof sh` cleanup.
setsid /usr/local/libexec/t825-recovery-supervisor 240 /run/t825-recovery \
    </dev/null >/dev/null 2>&1 &
pid=$!
printf '%s\n' "$pid" > /run/t825-recovery/supervisor.pid
sleep 1
kill -0 "$pid"
test -s /run/t825-recovery/supervisor.log
