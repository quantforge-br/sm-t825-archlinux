#!/usr/bin/env python3
"""Charger-disconnected matched power profile from the SM5705 fuel gauge.

Run as root on installed Arch. It waits for the charger to be disconnected,
then repeats idle and fixed single-core load windows of equal length while
sampling current, voltage and temperature, and finishes with bounded s2idle
cycles whose success is taken from suspend_stats. It does not change charger
policy, governors or brightness; brightness and governor are recorded.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

GAUGE = Path('/sys/class/power_supply/sm5705-battery')
CHARGER = Path('/sys/class/power_supply/sm5705-charger')
STATS = Path('/sys/power/suspend_stats')


def read(path, default=None):
    try:
        return path.read_text().strip()
    except OSError:
        return default


def sample():
    return {'t': round(time.monotonic(), 2), 'ua': int(read(GAUGE/'current_now', '0')),
            'uv': int(read(GAUGE/'voltage_now', '0')), 'temp': int(read(GAUGE/'temp', '0')) / 10,
            'cap': int(read(GAUGE/'capacity', '0')), 'online': read(CHARGER/'online')}


def window(name, seconds, log, load=False):
    worker = subprocess.Popen([sys.executable, '-c', 'while True: pass']) if load else None
    samples, end = [], time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            samples.append(sample())
            time.sleep(1)
    finally:
        if worker:
            worker.kill()
            worker.wait()
    currents = [s['ua'] / 1000 for s in samples]
    result = {'name': name, 'seconds': seconds, 'samples': len(samples),
              'median_ma': round(statistics.median(currents), 1),
              'mean_ma': round(statistics.fmean(currents), 1),
              'min_ma': round(min(currents), 1), 'max_ma': round(max(currents), 1),
              'temp_c': [samples[0]['temp'], samples[-1]['temp']],
              'uv': [samples[0]['uv'], samples[-1]['uv']],
              'charger_online': sorted({s['online'] for s in samples})}
    log.write(json.dumps({'window': result, 'raw': samples}) + '\n')
    log.flush()
    return result


def suspend_stats():
    return {name: read(STATS/name) for name in ('success', 'fail', 'last_failed_dev')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--window', type=int, default=60)
    parser.add_argument('--suspends', type=int, default=3)
    parser.add_argument('--suspend-seconds', type=int, default=30)
    parser.add_argument('--disconnect-timeout', type=int, default=300)
    args = parser.parse_args()
    if not (1 <= args.repeats <= 5 and 20 <= args.window <= 180 and 0 <= args.suspends <= 5
            and 10 <= args.suspend_seconds <= 120):
        parser.error('bounded parameters required')
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {'status': 'RUNNING', 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
               'brightness': {p.parent.name: read(p) for p in Path('/sys/class/backlight').glob('*/brightness')},
               'governor': read(Path('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')),
               'kernel': os.uname().release, 'windows': [], 'suspend': []}
    status_file = args.out/'summary.json'

    def save():
        status_file.write_text(json.dumps(summary, indent=2) + '\n')

    save()
    end = time.monotonic() + args.disconnect_timeout
    while read(CHARGER/'online') != '0' and time.monotonic() < end:
        time.sleep(2)
    if read(CHARGER/'online') != '0':
        summary['status'] = 'CHARGER_STILL_CONNECTED'
        save()
        return 1
    summary['disconnected_at'] = time.strftime('%H:%M:%S')
    time.sleep(30)  # Let the gauge average settle after the input change.
    with (args.out/'samples.jsonl').open('a') as log:
        for repeat in range(1, args.repeats + 1):
            for name, load in (('idle', False), ('load1', True)):
                summary['windows'].append({'repeat': repeat, **window(name, args.window, log, load)})
                save()
                time.sleep(10)
        for cycle in range(1, args.suspends + 1):
            before, start = suspend_stats(), sample()
            rc = subprocess.run(['rtcwake', '-m', 'freeze', '-s', str(args.suspend_seconds)],
                                capture_output=True, text=True, timeout=args.suspend_seconds + 90)
            time.sleep(5)
            after, finish = suspend_stats(), sample()
            summary['suspend'].append({'cycle': cycle, 'rc': rc.returncode, 'before': before, 'after': after,
                                       'success_delta': int(after['success'] or 0) - int(before['success'] or 0),
                                       'uv': [start['uv'], finish['uv']], 'cap': [start['cap'], finish['cap']],
                                       'post_resume_ma': finish['ua'] / 1000, 'temp_c': finish['temp']})
            save()
            time.sleep(10)
    idle = [w['median_ma'] for w in summary['windows'] if w['name'] == 'idle']
    load = [w['median_ma'] for w in summary['windows'] if w['name'] == 'load1']
    disconnected = all(w['charger_online'] == ['0'] for w in summary['windows'])
    suspended = all(s['success_delta'] == 1 and s['rc'] == 0 for s in summary['suspend'])
    summary['idle_median_ma'], summary['load1_median_ma'] = idle, load
    summary['status'] = 'PASS_MATCHED_WINDOWS' if disconnected and suspended else 'FAIL'
    save()
    return 0 if summary['status'].startswith('PASS') else 1


if __name__ == '__main__':
    sys.exit(main())
