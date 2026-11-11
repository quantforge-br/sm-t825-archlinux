#!/usr/bin/env python3
"""Sample tablet IBS counters without writing debugfs or changing Bluetooth.

Each row carries a directory identity and read interval. Values are sequential
reads, not an atomic snapshot; never subtract across different identities.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import time

FIELDS = (
    "tx_ibs_state", "rx_ibs_state", "ibs_recv_wake_acks", "ibs_recv_wakes",
    "ibs_recv_sleeps", "ibs_sent_wake_acks", "ibs_sent_wakes",
    "ibs_sent_sleeps", "tx_vote", "rx_vote", "wake_retrans", "tx_idle_delay",
)
DEFAULT_ROOT = Path("/sys/kernel/debug/bluetooth/hci0/ibs")


def sample(root=DEFAULT_ROOT):
    row = {"start_monotonic_ns": time.monotonic_ns(), "values": {}, "errors": {}}
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        row["directory_error"] = exc.errno
    else:
        try:
            identity = os.fstat(directory)
            row["directory_identity"] = [identity.st_dev, identity.st_ino]
            for name in FIELDS:
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                                 dir_fd=directory)
                    with os.fdopen(fd) as stream:
                        raw = stream.read(64).strip()
                        if name in ("tx_vote", "rx_vote") and raw in ("Y", "N"):
                            row["values"][name] = int(raw == "Y")
                        else:
                            row["values"][name] = int(raw)
                except OSError as exc:
                    row["errors"][name] = exc.errno
                except ValueError:
                    row["errors"][name] = "invalid_integer"
        finally:
            os.close(directory)
    row["end_monotonic_ns"] = time.monotonic_ns()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=115)
    args = parser.parse_args()
    if not 0 < args.seconds <= 120:
        parser.error("duration must be in (0, 120] seconds")
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    deadline = time.monotonic() + args.seconds
    sequence = 0
    while not stopping and time.monotonic() < deadline:
        row = sample()
        row["sequence"] = sequence
        print(json.dumps(row, sort_keys=True), flush=True)
        sequence += 1
        time.sleep(0.1)


if __name__ == "__main__":
    main()
