#!/usr/bin/env python3
"""Boot one validated normal/audio RAM image and observe its final reset.

Start detached with a timestamped host log. Requires an existing fastboot
session. No reboot request, partition flash, root write or lease extension is
performed. Software recovery does not cover a complete kernel/SoC lockup.
"""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

SERIAL = "957be8c9"

REMOTE = r'''
import hashlib, json, pathlib, subprocess
p = pathlib.Path
def read(name): return p(name).read_text().strip()
def optional(name):
    try: return read(name)
    except OSError as exc: return {'error': str(exc)}
pid = read('/run/t825-recovery/supervisor.pid')
devices = []
for device in sorted(p('/sys/fs/btrfs/bd56cedb-62b6-40a0-b478-b658293d65c0/devices').iterdir()):
    dev = read(device/'dev')
    devices.append({'dev': dev, 'ro': read('/sys/dev/block/'+dev+'/ro')})
print(json.dumps({
 'version': read('/proc/version'), 'boot_id': read('/proc/sys/kernel/random/boot_id'),
 'cmdline': read('/proc/cmdline'), 'pid1': p('/proc/1/cmdline').read_bytes().replace(b'\0',b' ').decode(),
 'mounts': read('/proc/mounts').splitlines(), 'devices': devices,
 'supervisor_pid': pid,
 'supervisor_sha256': hashlib.sha256(p('/proc/'+pid+'/exe').read_bytes()).hexdigest(),
 'supervisor_log': read('/run/t825-recovery/supervisor.log'),
 'handoff_log': read('/run/t825-recovery/direct-init.log'),
 'modules': read('/proc/modules'),
 'asound_cards': optional('/proc/asound/cards'),
 'wcd_port_diagnostics': optional('/sys/module/snd_soc_wcd9335/parameters/port_diagnostics'),
 'dmesg': subprocess.run(['dmesg'], text=True, capture_output=True, timeout=3).stdout,
}))
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_handoff(data, expected_version, supervisor_hash, original_pid):
    if data['version'] != expected_version:
        raise ValueError('running kernel differs from candidate banner')
    if '/run/t825-recovery/postpivot-init' not in data['pid1']:
        raise ValueError('replacement PID 1 unverified')
    if not {'t825.ramdiag', 't825.direct-init', 'panic=10'}.issubset(data['cmdline'].split()):
        raise ValueError('candidate command-line markers missing')
    mounts = [line.split() for line in data['mounts']]
    roots = [m for m in mounts if m[1] == '/']
    if len(roots) != 1 or roots[0][2] != 'btrfs' or 'ro' not in roots[0][3].split(','):
        raise ValueError('root is not read-only Btrfs')
    if not {'rescue=nologreplay', 'nologreplay', 'norecovery'}.intersection(roots[0][3].split(',')):
        raise ValueError('root journal-replay protection unverified')
    if any(m[1] == '/boot' or m[1].startswith('/boot/') for m in mounts):
        raise ValueError('installed boot volume must not be mounted')
    # This tablet's verified root has two Btrfs members. Do not silently accept
    # a one-member view or an unprotected backing block device.
    if len(data['devices']) != 2 or len({d['dev'] for d in data['devices']}) != 2:
        raise ValueError('Btrfs member inventory differs from accepted control')
    if any(d['ro'] != '1' for d in data['devices']):
        raise ValueError('root backing block device is writable')
    if data['supervisor_pid'] != original_pid or data['supervisor_sha256'] != supervisor_hash:
        raise ValueError('original supervisor identity changed')
    if not data['supervisor_log'] or not data['handoff_log']:
        raise ValueError('supervisor/handoff evidence missing')


def run(args, seconds=10, text=None):
    try:
        return subprocess.run(args, input=text, text=True, capture_output=True,
                              timeout=seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(args, 124, '', 'command timed out: '+str(exc))
    except OSError as exc:
        return subprocess.CompletedProcess(args, 127, '', str(exc))


def fastboot_ready():
    result = run(['fastboot', 'devices'], 4)
    if result.returncode:
        return None  # A failed probe does not establish disappearance.
    return any(
        line.split() == [SERIAL, 'fastboot'] for line in result.stdout.splitlines())


def observe_reset(deadline, disappeared, ready=fastboot_ready,
                  now=time.monotonic, sleep=time.sleep, linux_ready=None):
    while now() < deadline:
        present = ready()
        if present and disappeared:
            return True, disappeared
        if present is False:
            disappeared = True
        if disappeared and linux_ready is not None and linux_ready():
            return True, disappeared
        sleep(2)
    return False, disappeared


def is_new_linux_boot(data, original_boot_id):
    uuid = r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}'
    return bool(original_boot_id and re.fullmatch(uuid, original_boot_id)
                and re.fullmatch(uuid, data.get('boot_id', ''))
                and data['boot_id'] != original_boot_id
                and data.get('version', '').startswith('Linux version '))


def probe_new_linux_boot(targets, original_boot_id):
    """Try USB and installed-system networking; never infer reset from SSH alone."""
    if not original_boot_id:
        return None
    for target in dict.fromkeys(targets):
        result = run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=2', target,
                      'cat /proc/sys/kernel/random/boot_id; cat /proc/version'], 3)
        lines = result.stdout.splitlines()
        if result.returncode or len(lines) != 2:
            continue
        data = dict(boot_id=lines[0], version=lines[1], ssh_target=target)
        if is_new_linux_boot(data, original_boot_id):
            return data
    return None


def snapshot_bundle(source, target):
    """Freeze validation inputs, excluding the obsolete extracted root tree."""
    target.mkdir()
    for entry in source.iterdir():
        if entry.is_file():
            shutil.copyfile(entry, target/entry.name)
    shutil.copytree(source/'dtbs', target/'dtbs')


def archive_supervisor_hash(bundle):
    # Read the archive validated against the actual Android image, never a
    # possibly stale extracted root directory.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'image_validator', Path(__file__).with_name('test-t825-readonly-ram-image.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='t825-cycle-archive-') as tmp:
        module.extract(bundle/'initramfs', tmp)
        return sha(Path(tmp)/'usr/local/libexec/t825-recovery-supervisor')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--kind', choices=['normal', 'audio'], required=True)
    parser.add_argument('--source-image', type=Path, help='required normal-r2 source image')
    parser.add_argument('--ssh-target', default='172.16.42.1')
    parser.add_argument('--recovery-ssh-target', default='tabs3')
    parser.add_argument('--audio-probe', action='store_true',
                        help='bounded microphone lifecycle probe; requires --kind audio')
    parser.add_argument('--audio-repetitions', type=int, choices=range(1, 4), default=1,
                        help='1..3 captures in one boot; stop at first fault, unchanged recovery deadline')
    parser.add_argument('--wait-fastboot', type=int, default=0,
                        help='bounded seconds to wait for manual initial entry (0..900)')
    args = parser.parse_args()
    if not 0 <= args.wait_fastboot <= 900:
        parser.error('--wait-fastboot must be between 0 and 900')
    if args.audio_probe and args.kind != 'audio':
        parser.error('--audio-probe requires --kind audio')
    if args.audio_repetitions != 1 and not args.audio_probe:
        parser.error('--audio-repetitions requires --audio-probe')
    try:
        return execute(args)
    except Exception as exc:
        if args.report.is_dir() and not (args.report/'result.json').exists():
            (args.report/'result.json').write_text(json.dumps({
                'status': 'PREFLIGHT_FAILED', 'error': str(exc),
                'diagnostic_pass': False, 'reset_observed': False,
            }, indent=2)+'\n')
        raise


def execute(args):
    repo = Path(os.environ.get('T825_SOURCE_ROOT', Path(__file__).resolve().parents[1]))
    out = args.report.resolve()
    if os.environ.get('T825_READONLY_SNAPSHOT') != '1':
        out.mkdir(mode=0o700, parents=True, exist_ok=False)
        runner = out/'runner'
        runner.mkdir()
        for name in ['t825-readonly-cycle.py', 't825-telnet.py',
                     'test-t825-readonly-ram-image.py', 'test-t825-audiodiag-ram-image.py',
                     't825-audio-ram-probe.py', 't825-audio-mic-phases.py', 't825-validate.py']:
            shutil.copy2(repo/'tools'/name, runner/name)
        (out/'runner.sha256').write_text(''.join(
            sha(p)+'  '+p.name+'\n' for p in sorted(runner.iterdir())))
        os.execve(sys.executable, [sys.executable, str(runner/'t825-readonly-cycle.py'),
                                  *sys.argv[1:]],
                  {**os.environ, 'T825_SOURCE_ROOT': str(repo), 'T825_READONLY_SNAPSHOT': '1'})
    (out/'host.pid').write_text(str(os.getpid())+'\n')
    runner = Path(__file__).resolve().parent
    bundle = out/'bundle'
    # A parent unattended controller may already hold the tablet lock while
    # it invokes this runner for a nested diagnostic. Reuse that ownership;
    # otherwise acquire the lock normally.
    inherited_lock = os.environ.get('T825_READONLY_LOCK_FD')
    lock_context = contextlib.nullcontext() if inherited_lock else \
        (repo/'artifacts/roadmap-7.3/tablet-test.lock').open('w')
    with lock_context as lock:
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot_bundle(args.bundle.resolve(), bundle)
        validator = 'test-t825-audiodiag-ram-image.py' if args.kind == 'audio' else 'test-t825-readonly-ram-image.py'
        command = [sys.executable, str(runner/validator), str(bundle)]
        if args.kind == 'normal':
            if args.source_image is None:
                raise ValueError('--source-image required for normal candidate')
            shutil.copyfile(args.source_image.resolve(), out/'source.img')
            command += ['--source-image', str(out/'source.img')]
        result = run(command, 60)
        (out/'validation.log').write_text(result.stdout+result.stderr)
        if result.returncode:
            raise ValueError('offline image validation failed; no device access')
        image = bundle/('t825-audiodiag-ram.img' if args.kind == 'audio' else 't825-readonly-ram.img')
        banners = re.findall(rb'Linux version [^\x00\n]+', gzip.decompress((bundle/'vmlinuz').read_bytes()))
        if not banners:
            raise ValueError('kernel banner missing')
        version = max(banners, key=len).decode()
        expected_supervisor = archive_supervisor_hash(bundle)
        (out/'bundle.sha256').write_text(''.join(
            sha(p)+'  '+str(p.relative_to(bundle))+'\n'
            for p in sorted(bundle.rglob('*')) if p.is_file()))
        identity = dict(image_sha256=sha(image), expected_version=version,
                        supervisor_sha256=expected_supervisor, serial=SERIAL,
                        kind=args.kind, started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        (out/'identity.json').write_text(json.dumps(identity, indent=2)+'\n')
        wait_deadline = time.monotonic()+args.wait_fastboot
        print('Offline validation passed; waiting for initial fastboot entry.', flush=True)
        while True:
            present = fastboot_ready()
            if present is True or time.monotonic() >= wait_deadline:
                break
            time.sleep(2)
        if present is not True:
            raise ValueError('tablet is not in fastboot; no reboot requested')
        identity_result = run(['fastboot', '-s', SERIAL, 'getvar', 'lk2nd:compatible'], 5)
        (out/'fastboot-identity.txt').write_text(identity_result.stdout+identity_result.stderr)
        if identity_result.returncode or 'lk2nd:compatible: samsung,gts3llte' not in identity_result.stdout+identity_result.stderr:
            raise ValueError('unexpected bootloader identity')
        started = time.monotonic()
        deadline = started+330
        diagnostic = False
        disappeared = False
        error = None
        candidate_boot_id = None
        audio_probe_pass = None
        # Once boot is dispatched, every collector failure still reaches the
        # same final-reset observer. Never reboot out of recovered fastboot.
        try:
            result = run(['fastboot', '-s', SERIAL, 'boot', str(image)], 25)
            (out/'fastboot-boot.txt').write_text(result.stdout+result.stderr)
            if result.returncode:
                raise ValueError('fastboot boot did not report success')
            original_pid = None
            while time.monotonic() < started+90:
                if fastboot_ready() is False:
                    disappeared = True
                command = [sys.executable, str(runner/'t825-telnet.py'), '--host', '172.16.42.1', '--port', '23']
                result = run(command, 5, 'printf "T825_SUPERVISOR_PID=%s\\n" "$(cat /run/t825-recovery/supervisor.pid)"; printf "T825_BOOT_ID=%s\\n" "$(cat /proc/sys/kernel/random/boot_id)"\n')
                (out/'pre-pivot.txt').write_text(result.stdout+result.stderr)
                match = re.search(r'^T825_SUPERVISOR_PID=([0-9]+)\r?$', result.stdout, re.M)
                boot_match = re.search(r'^T825_BOOT_ID=([0-9a-f-]{36})\r?$', result.stdout, re.M)
                if result.returncode == 0 and match and boot_match:
                    original_pid = match[1]
                    candidate_boot_id = boot_match[1]
                    break
                time.sleep(2)
            if not original_pid:
                raise ValueError('initial supervisor marker unavailable')
            result = run(command, 8, 'touch /tmp/continue_boot\n')
            (out/'release.txt').write_text(result.stdout+result.stderr)
            if result.returncode:
                raise ValueError('initramfs release was not acknowledged')
            while time.monotonic() < started+210:
                if fastboot_ready():
                    raise ValueError('reset before handoff acceptance')
                result = run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
                              args.ssh_target, 'sudo -n python3 -'], 8, REMOTE)
                (out/'handoff.txt').write_text(result.stdout+result.stderr)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    verify_handoff(data, version, expected_supervisor, original_pid)
                    (out/'handoff.json').write_text(json.dumps(data, indent=2)+'\n')
                    diagnostic = True
                    break
                time.sleep(2)
            if not diagnostic:
                raise ValueError('post-pivot SSH deadline expired')
            if args.audio_probe:
                audio_probe_pass = False
                config = dict(version=version, boot_id=candidate_boot_id, pid=original_pid,
                              supervisor_hash=expected_supervisor, repetitions=args.audio_repetitions)
                sources = {name: (runner/name).read_text() for name in
                           ('t825-audio-mic-phases.py', 't825-validate.py')}
                # Python source is sent through SSH stdin, never interpolated
                # into a shell command. All inputs come from the frozen runner.
                script = ('CONFIG = '+repr(config)+'\nSOURCES = '+repr(sources)+'\n'
                          +(runner/'t825-audio-ram-probe.py').read_text())
                result = run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
                              args.ssh_target, 'sudo -n python3 -'], 140, script)
                (out/'audio-probe.txt').write_text(result.stdout+result.stderr)
                if result.stdout.strip():
                    probe = json.loads(result.stdout)
                    (out/'audio-probe.json').write_text(json.dumps(probe, indent=2)+'\n')
                    audio_probe_pass = result.returncode == 0 and probe.get('status') == 'PASS'
                if not audio_probe_pass:
                    raise ValueError('audio probe failed or was blocked; inspect audio-probe evidence')
        except Exception as exc:
            error = str(exc)
        linux_recovery = {}
        def recovered_linux():
            # Installed Linux may expose USB before Tailscale. The candidate
            # also exposes USB, so a changed boot ID remains mandatory.
            data = probe_new_linux_boot([args.ssh_target, args.recovery_ssh_target], candidate_boot_id)
            if data is None:
                return False
            linux_recovery.update(data)
            (out/'linux-recovery.json').write_text(json.dumps(data, indent=2)+'\n')
            return True
        recovered, disappeared = observe_reset(deadline, disappeared, linux_ready=recovered_linux)
        decision = dict(diagnostic_pass=diagnostic, fastboot_disappeared=disappeared,
                        reset_destination=('linux' if linux_recovery else 'fastboot') if recovered else 'unverified',
                        candidate_boot_id=candidate_boot_id,
                        audio_probe_pass=audio_probe_pass,
                        unattended_next_ram_cycle=bool(diagnostic and recovered and not linux_recovery and audio_probe_pass is not False),
                        reset_observed=recovered, error=error,
                        elapsed_seconds=round(time.monotonic()-started, 3),
                        status=('PASS_HANDOFF_AUDIO_PROBE_AND_RESET' if args.audio_probe else 'PASS_HANDOFF_AND_RESET')
                               if diagnostic and recovered and audio_probe_pass is not False else 'FAIL',
                        scope='read-only handoff/software reset; optional bounded PCM probe, no acoustic/GPU acceptance')
        (out/'result.json').write_text(json.dumps(decision, indent=2)+'\n')
        for command, name in [(['lsusb'], 'usb-final.txt'), (['fastboot', 'devices'], 'fastboot-final.txt')]:
            result = run(command, 5)
            (out/name).write_text(result.stdout+result.stderr)
        (out/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(out.iterdir())
            if p.is_file() and p.name not in ('SHA256SUMS', 'host.log')))
        print(json.dumps(decision), flush=True)
        return 0 if decision['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
