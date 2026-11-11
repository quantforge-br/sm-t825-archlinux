#!/usr/bin/env python3
"""Authorized extlinux entry, bounded RAM session, and verified Arch return.

Run detached. By default validate a round trip without a diagnostic. An optional
audio bundle performs three captures in one RAM boot before restoration.
Software recovery does not cover complete kernel/SoC lockups.
"""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SERIAL = '957be8c9'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv, timeout=10, source=None):
    try:
        return subprocess.run(argv, input=source, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 124, '', str(exc))


class Session:
    def __init__(self, report, target, runner):
        self.out, self.target, self.runner = report, target, runner

    def call(self, name, argv, timeout=10, source=None):
        result = run(argv, timeout, source)
        with (self.out/(name+'.log')).open('a') as log:
            log.write(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())+'\n')
            log.write(result.stdout+result.stderr+'\nrc='+str(result.returncode)+'\n')
        return result

    def remote(self, config, target=None):
        script = 'CONFIG = '+repr(config)+'\n'+(self.runner/'t825-extlinux-session-remote.py').read_text()
        result = self.call('ssh-'+config['mode'], ['ssh', '-o', 'BatchMode=yes', '-o',
                           'ConnectTimeout=3', target or self.target, 'sudo -n python3 -'], 35, script)
        if result.returncode:
            raise RuntimeError('SSH '+config['mode']+' failed; see log')
        return json.loads(result.stdout)

    def ready(self):
        result = self.call('fastboot-poll', ['fastboot', 'devices'], 4)
        return result.returncode == 0 and any(x.split() == [SERIAL, 'fastboot'] for x in result.stdout.splitlines())

    def wait_fastboot(self, seconds):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            if self.ready():
                result = self.call('fastboot-identity', ['fastboot', '-s', SERIAL, 'getvar', 'lk2nd:compatible'], 5)
                if result.returncode == 0 and 'lk2nd:compatible: samsung,gts3llte' in result.stdout+result.stderr:
                    return True
                raise RuntimeError('fastboot identity mismatch')
            time.sleep(2)
        return False

    def restore(self, image, supervisor_hash, expected_sha):
        if not self.wait_fastboot(45):
            raise RuntimeError('fastboot unavailable for restoration')
        result = self.call('restore-boot', ['fastboot', '-s', SERIAL, 'boot', str(image)], 25)
        if result.returncode:
            raise RuntimeError('restoration RAM boot failed')
        started = time.monotonic()
        telnet = [sys.executable, str(self.runner/'t825-telnet.py'), '--timeout', '6']
        boot_id = None
        while time.monotonic() < started+90:
            result = self.call('restore-marker', telnet, 8,
                               'printf "T825_BOOT_ID=%s\\n" "$(cat /proc/sys/kernel/random/boot_id)"\n')
            match = re.search(r'^T825_BOOT_ID=([0-9a-f-]{36})\r?$', result.stdout, re.M)
            if result.returncode == 0 and match:
                boot_id = match[1]
                break
            time.sleep(2)
        if not boot_id:
            # Still observe the known supervisor's deadline; never dispatch
            # another experiment after loss of diagnostic connectivity.
            self.wait_fastboot(max(1, int(started+300-time.monotonic())))
            raise RuntimeError('restoration debug shell unavailable')
        source = ('EXPECTED_SHA='+expected_sha+'\nEXPECTED_SUPERVISOR='+supervisor_hash+
                  '\nEXPECTED_BOOT_ID='+boot_id+'\n'+(self.runner/'t825-extlinux-restore-ram.sh').read_text())
        result = self.call('restore-rename', [*telnet[:-1], '75'], 80, source)
        restored = result.returncode == 0 and ('T825_EXTLINUX_RESTORED='+expected_sha) in result.stdout
        if not restored:
            self.wait_fastboot(max(1, int(started+300-time.monotonic())))
            raise RuntimeError('restoration not acknowledged; inspect rename log')
        return boot_id


def validate_arch(data, before, ram_id, expected_sha):
    if (data['boot_id'] in (before, ram_id) or data['sha256'] != expected_sha
            or not data['temporary_name_absent'] or data['pid1'] != 'systemd'):
        raise ValueError('final installed Arch state unverified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--restore-bundle', type=Path, required=True)
    parser.add_argument('--source-image', type=Path, required=True)
    parser.add_argument('--audio-bundle', type=Path)
    parser.add_argument('--gnss-image', type=Path,
                        help='MSS/GNSS RAM image (one inspect-hold cycle with read-only modem queries)')
    parser.add_argument('--ssh-target', default='tabs3')
    args = parser.parse_args()
    if args.audio_bundle and args.gnss_image:
        parser.error('choose at most one diagnostic')
    repo = Path(__file__).resolve().parents[1]
    out = args.report.resolve()
    if os.environ.get('T825_SESSION_SNAPSHOT') != '1':
        # A detached launcher may create the directory first so stdout/stderr
        # can be redirected there. Accept only those two launcher metadata
        # files; never resume or overwrite an existing report.
        if out.exists():
            allowed = {'host.log', 'launcher.pid'}
            unexpected = {p.name for p in out.iterdir()} - allowed
            if unexpected:
                raise FileExistsError('report directory is not empty: '+str(sorted(unexpected)))
        else:
            out.mkdir(mode=0o700, parents=True)
        runner = out/'runner'; runner.mkdir()
        for pattern in ('t825-fastboot-session.py', 't825-extlinux-*', 't825-readonly-cycle.py',
                        't825-telnet.py', 'test-t825-readonly-ram-image.py',
                        'test-t825-audiodiag-ram-image.py', 't825-audio-ram-probe.py',
                        't825-audio-mic-phases.py', 't825-validate.py',
                        't825-gnss-auto-cycle.sh', 't825-gnss-hold-test.sh',
                        'test-t825-gnss-ram-image.py'):
            for source in (repo/'tools').glob(pattern):
                shutil.copy2(source, runner/source.name)
        (out/'runner.sha256').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(runner.iterdir())))
        os.execve(sys.executable, [sys.executable, str(runner/Path(__file__).name), *sys.argv[1:]],
                  {**os.environ, 'T825_SESSION_SNAPSHOT': '1', 'T825_SOURCE_ROOT': str(repo)})
    repo = Path(os.environ['T825_SOURCE_ROOT'])
    runner = Path(__file__).parent
    (out/'host.pid').write_text(str(os.getpid())+'\n')
    session = Session(out, args.ssh_target, runner)
    spec = importlib.util.spec_from_file_location('readonly', runner/'t825-readonly-cycle.py')
    cycle = importlib.util.module_from_spec(spec); spec.loader.exec_module(cycle)
    decision = {'status': 'PREFLIGHT_FAILED', 'entry_observed': False, 'restored': False}
    mutated = False
    before = None
    with (repo/'artifacts/roadmap-7.3/tablet-test.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            bundle = out/'restore-bundle'
            cycle.snapshot_bundle(args.restore_bundle.resolve(), bundle)
            shutil.copyfile(args.source_image, out/'source.img')
            result = session.call('restore-validation', [sys.executable, str(runner/'test-t825-readonly-ram-image.py'),
                                 str(bundle), '--source-image', str(out/'source.img')], 60)
            if result.returncode:
                raise ValueError('restoration image failed offline validation')
            supervisor_hash = cycle.archive_supervisor_hash(bundle)
            audio = None
            if args.audio_bundle:
                audio = out/'audio-bundle'
                cycle.snapshot_bundle(args.audio_bundle.resolve(), audio)
                result = session.call('audio-validation', [sys.executable,
                    str(runner/'test-t825-audiodiag-ram-image.py'), str(audio)], 60)
                if result.returncode:
                    raise ValueError('audio image failed offline validation')
            gnss = None
            if args.gnss_image:
                gnss_dir = out/'gnss-bundle'
                shutil.copytree(args.gnss_image.resolve().parent, gnss_dir)
                gnss = gnss_dir/args.gnss_image.name
                result = subprocess.run([sys.executable, str(runner/'test-t825-gnss-ram-image.py')],
                    capture_output=True, text=True, timeout=60,
                    env={**os.environ, 'T825_RAM_IMAGE': str(gnss), 'T825_RAM_BUNDLE': str(gnss_dir)})
                (out/'gnss-validation.log').write_text(result.stdout+result.stderr+'\nrc='+str(result.returncode)+'\n')
                if result.returncode:
                    raise ValueError('GNSS image failed offline validation')
            (out/'inputs.sha256').write_text(''.join(sha(p)+'  '+str(p.relative_to(out))+'\n'
                for p in sorted(out.rglob('*')) if p.is_file() and ('bundle' in str(p.relative_to(out)) or p.name == 'source.img')))
            before = session.remote({'mode': 'inspect'})
            (out/'before.json').write_text(json.dumps(before, indent=2)+'\n')
            original = base64.b64decode(before['content_base64'], validate=True)
            if hashlib.sha256(original).hexdigest() != before['sha256']:
                raise ValueError('host backup hash mismatch')
            (out/'extlinux.conf.original').write_bytes(original)
            print('Preflight passed; requesting guarded remote fastboot entry.', flush=True)
            mutated = True  # A lost SSH acknowledgement must still restore.
            session.remote({'mode': 'enter', 'boot_id': before['boot_id'], 'sha256': before['sha256']})
            if not session.wait_fastboot(100):
                raise RuntimeError('remote fastboot entry deadline expired')
            decision['entry_observed'] = True
            print('Remote fastboot entry verified.', flush=True)
            if audio:
                # The child uses the same lock through an inherited descriptor;
                # it verifies the descriptor rather than opening a second lock.
                command = [sys.executable, str(runner/'t825-readonly-cycle.py'), str(audio), str(out/'audio-cycle'),
                           '--kind', 'audio', '--audio-probe', '--audio-repetitions', '3']
                with (out/'audio-cycle.log').open('w') as log:
                    child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=450,
                        pass_fds=(lock.fileno(),), env={**os.environ,
                        'T825_SESSION_LOCK_FD': str(lock.fileno()),
                        'T825_READONLY_LOCK_FD': str(lock.fileno())})
                decision['diagnostic_rc'] = child.returncode
                decision['diagnostic'] = json.loads((out/'audio-cycle/result.json').read_text())
            if gnss:
                command = ['bash', str(runner/'t825-gnss-auto-cycle.sh'), str(gnss)]
                with (out/'gnss-cycle.log').open('w') as log:
                    child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=520,
                        cwd=repo, pass_fds=(lock.fileno(),), env={**os.environ,
                        'T825_SESSION_LOCK_FD': str(lock.fileno()), 'T825_SOURCE_ROOT': str(repo),
                        'T825_RUNNER_SNAPSHOT': '1', 'T825_REPORT_DIR': str(out/'gnss-cycle'),
                        'T825_AUTO_CYCLES': '1', 'T825_WAIT_SECONDS': '300',
                        'T825_QMI_MODEM_PROBE': '1'})
                decision['diagnostic_rc'] = child.returncode
                tsv = out/'gnss-cycle/results.tsv'
                decision['diagnostic'] = {'kind': 'gnss', 'results': tsv.read_text() if tsv.exists() else None}
            decision['status'] = 'RESTORING'
        except Exception as exc:
            decision['error'] = str(exc)
        finally:
            if mutated and before:
                print('Restoring the original extlinux configuration and observing Arch return.', flush=True)
                try:
                    if not session.ready():
                        # If entry failed but original Linux survived, undo the
                        # rename there. Do not reboot it a second time blindly.
                        try:
                            current = session.remote({'mode': 'undo-entry', 'boot_id': before['boot_id'],
                                                      'sha256': before['sha256']})
                            decision['restored'] = current['sha256'] == before['sha256']
                            decision['status'] = 'ENTRY_FAILED_RESTORED_IN_PLACE'
                        except Exception:
                            pass
                    if not decision['restored']:
                        ram_id = session.restore(bundle/'t825-readonly-ram.img', supervisor_hash, before['sha256'])
                        end = time.monotonic()+300
                        while time.monotonic() < end:
                            try:
                                current = session.remote({'mode': 'verify', 'sha256': before['sha256']})
                                validate_arch(current, before['boot_id'], ram_id, before['sha256'])
                                if current['version'] != before['version']:
                                    raise ValueError('installed kernel changed')
                                (out/'after.json').write_text(json.dumps(current, indent=2)+'\n')
                                decision['restored'] = True
                                break
                            except Exception:
                                time.sleep(4)
                        if not decision['restored']:
                            raise RuntimeError('restored Arch SSH deadline expired')
                        decision['status'] = ('PASS_REMOTE_FASTBOOT_AND_ARCH_RETURN'
                            if decision['entry_observed'] and not decision.get('error') and decision.get('diagnostic_rc', 0) == 0
                            else 'FAIL_DIAGNOSTIC_ARCH_RESTORED')
                except Exception as exc:
                    decision['restoration_error'] = str(exc)
                    decision['status'] = 'RECOVERY_FAILED'
            for name, command in [('usb-final', ['lsusb']), ('fastboot-final', ['fastboot', 'devices'])]:
                session.call(name, command, 5)
            (out/'result.json').write_text(json.dumps(decision, indent=2)+'\n')
            print(json.dumps(decision), flush=True)
    return 0 if decision['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    sys.exit(main())
