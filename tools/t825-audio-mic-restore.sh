#!/usr/bin/env bash
# Root-only transient mixer restoration; independent of SSH and the collector.
set -euo pipefail
export LC_ALL=C
report=${1:?private report}
case "$report" in /run/t825-mic-phases-[0-9]*) ;; *) exit 2 ;; esac
[ "$(id -u)" = 0 ] || exit 2
cd "$report"
trap 'printf "%s\n" "$?" > restoration.status' EXIT
timeout --kill-after=2s 10 alsactl -f mixer-before.state restore 0 > restoration.log 2>&1
timeout --kill-after=2s 10 alsactl -f mixer-restored.state store 0 >> restoration.log 2>&1
cmp mixer-before.state mixer-restored.state >> restoration.log 2>&1
