#!/usr/bin/env python3
"""Bounded volatile microphone probe under an already-armed RAM-boot supervisor.

Invoked over stdin by the frozen host cycle with CONFIG and SOURCES dictionaries.
Never enable it on installed Linux. No media samples leave the capture process.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time


def check_gate(data, expected, now, *, preparing=False):
    if data['version'] != expected['version'] or '-audiodiag ' not in data['version']:
        raise ValueError('requires the exact audio-diagnostic kernel')
    if data['boot_id'] != expected['boot_id']:
        raise ValueError('boot changed before audio probe')
    if data['pid'] != expected['pid'] or data['supervisor_hash'] != expected['supervisor_hash']:
        raise ValueError('independent supervisor identity mismatch')
    if '/run/t825-recovery/postpivot-init' not in data['pid1']:
        raise ValueError('not the direct diagnostic PID 1')
    mounts = [line.split() for line in data['mounts']]
    if not any(m[1] == '/run' and m[2] == 'tmpfs' for m in mounts):
        raise ValueError('/run is not volatile tmpfs')
    roots = [m for m in mounts if m[1] == '/']
    if len(roots) != 1 or roots[0][2] != 'btrfs' or not {'ro', 'rescue=nologreplay'}.issubset(roots[0][3].split(',')):
        raise ValueError('root protection is not verified')
    if any(m[1] == '/boot' or m[1].startswith('/boot/') for m in mounts):
        raise ValueError('installed boot volume mounted')
    if len(data['member_ro']) != 2 or any(value != '1' for value in data['member_ro']):
        raise ValueError('both Btrfs members must be protected')
    if not preparing and data['port_diagnostics'] not in ('Y', '1'):
        raise ValueError('instrumented codec module is not active')
    if (not preparing and data.get('transaction_requested') and
            data.get('transaction_diagnostics') not in ('Y', '1')):
        raise ValueError('SLIMbus transaction instrumentation is not active')
    if (not preparing and data.get('removal_requested') and
            data.get('channel_removal') not in ('Y', '1')):
        raise ValueError('NGD channel removal experiment is not active')
    if (not preparing and data.get('event_trace_requested') and
            (not str(data.get('event_trace') or '').strip()
             or str(data.get('event_trace')).strip() in ('0', 'N'))):
        raise ValueError('audio event trace is not active')
    match = re.fullmatch(r'armed at [0-9]+ deadline ([0-9]+)\s*', data['supervisor_log'])
    if not match or not (160 if preparing else 100) <= int(match[1])-now <= 240:
        raise ValueError('insufficient or unexpected independent recovery deadline')


def evidence():
    def read(path): return Path(path).read_text().strip()
    pid = read('/run/t825-recovery/supervisor.pid')
    os.kill(int(pid), 0)
    members = Path('/sys/fs/btrfs/bd56cedb-62b6-40a0-b478-b658293d65c0/devices')
    return dict(version=read('/proc/version'), boot_id=read('/proc/sys/kernel/random/boot_id'),
                pid=pid, supervisor_hash=hashlib.sha256(Path('/proc/'+pid+'/exe').read_bytes()).hexdigest(),
                pid1=Path('/proc/1/cmdline').read_bytes().replace(b'\0', b' ').decode(),
                mounts=read('/proc/mounts').splitlines(),
                member_ro=[read(member/'ro') for member in members.iterdir()],
                port_diagnostics=(read('/sys/module/snd_soc_wcd9335/parameters/port_diagnostics')
                                  if Path('/sys/module/snd_soc_wcd9335/parameters/port_diagnostics').is_file() else None),
                transaction_requested=transaction_requested(),
                transaction_diagnostics=(read('/sys/module/slimbus/parameters/transaction_diagnostics')
                                          if Path('/sys/module/slimbus/parameters/transaction_diagnostics').is_file() else None),
                removal_requested=removal_requested(),
                channel_removal=(read('/sys/module/slim_qcom_ngd_ctrl/parameters/channel_removal')
                                 if Path('/sys/module/slim_qcom_ngd_ctrl/parameters/channel_removal').is_file() else None),
                event_trace=(read('/sys/module/slimbus/parameters/event_records')
                             if Path('/sys/module/slimbus/parameters/event_records').is_file() else None),
                supervisor_log=read('/run/t825-recovery/supervisor.log'))


def command(argv, out, label, timeout):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        (out/(label+'.stdout')).write_text(result.stdout)
        (out/(label+'.stderr')).write_text(result.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        (out/(label+'.stderr')).write_text('command exceeded its deadline\n')
        return 124


MODULES = ('snd_soc_rt5508', 'snd_soc_wcd9335', 'apr', 'q6afe_dai',
           'q6asm_dai', 'slim_qcom_ngd_ctrl', 'snd_soc_apq8096', 'qcom_q6v5_pas')


def firmware_inventory(base):
    """Validate installed split MDT assets without extracting or changing them."""
    inventory = {}
    # PAS binds both enabled ADSP and SLPI nodes; validate both before loading.
    for stem in ('adsp', 'slpi'):
        mdt = base/(stem+'.mdt')
        data = mdt.read_bytes()
        if len(data) < 52 or data[:6] != b'\x7fELF\x01\x01':
            raise ValueError('unexpected ELF32 little-endian MDT: '+str(mdt))
        offset = struct.unpack_from('<I', data, 28)[0]
        size, count = struct.unpack_from('<HH', data, 42)
        if size != 32 or not 1 <= count <= 128 or offset+size*count > len(data):
            raise ValueError('invalid MDT program headers: '+str(mdt))
        inventory[str(mdt)] = hashlib.sha256(data).hexdigest()
        for index in range(count):
            filesz = struct.unpack_from('<8I', data, offset+size*index)[4]
            if not filesz:
                continue
            segment = base/(stem+'.b%02d'%index)
            if segment.stat().st_size != filesz:
                raise ValueError('firmware segment size mismatch: '+str(segment))
            inventory[str(segment)] = hashlib.sha256(segment.read_bytes()).hexdigest()
    return inventory


def transaction_requested():
    return 'slimbus.transaction_diagnostics=1' in Path('/proc/cmdline').read_text().split()


def removal_requested():
    return 'slim_qcom_ngd_ctrl.channel_removal=1' in Path('/proc/cmdline').read_text().split()


def removal_active():
    parameter = Path('/sys/module/slim_qcom_ngd_ctrl/parameters/channel_removal')
    return parameter.is_file() and parameter.read_text().strip() in ('1', 'Y')


def event_trace_requested():
    return 'slimbus.event_trace=1' in Path('/proc/cmdline').read_text().split()


def event_trace_active():
    parameter = Path('/sys/module/slimbus/parameters/event_trace')
    return parameter.is_file() and parameter.read_text().strip() not in ('', '0', 'N')


def audio_ready():
    card = Path('/proc/asound/card0/id')
    parameter = Path('/sys/module/snd_soc_wcd9335/parameters/port_diagnostics')
    return (card.is_file() and card.read_text().strip() == 'S3'
            and parameter.is_file() and parameter.read_text().strip() in ('1', 'Y')
            and (not transaction_requested() or transaction_active())
            and (not removal_requested() or removal_active())
            and (not event_trace_requested() or event_trace_active())
            and Path('/dev/snd/pcmC0D2c').exists())


def transaction_active():
    parameter = Path('/sys/module/slimbus/parameters/transaction_diagnostics')
    return parameter.is_file() and parameter.read_text().strip() in ('1', 'Y')


def prepare_audio(out, config):
    check_gate(evidence(), config, time.clock_gettime(time.CLOCK_BOOTTIME), preparing=True)
    mounts = Path('/proc/mounts').read_text().splitlines()
    if not any(len(m := line.split()) > 3 and m[1] == '/usr/lib/modules'
               and m[2] == 'tmpfs' and 'ro' in m[3].split(',') for line in mounts):
        raise ValueError('candidate module tree is not a protected RAM bind mount')
    inventory = firmware_inventory(Path('/usr/lib/firmware/qcom/msm8996/samsung/gts3'))
    (out/'firmware-sha256.json').write_text(json.dumps(inventory, indent=2)+'\n')
    # Avoid installed modprobe install hooks/configuration. Only this explicit
    # provider list and modules.dep dependencies may load; MSS stays disabled.
    deadline = time.monotonic()+45
    try:
        if transaction_requested():
            # Load before codec dependencies can load SLIMbus without options.
            argv = ['modprobe', '-C', '/dev/null', '--ignore-install',
                    'slimbus', 'transaction_diagnostics=1']
            if event_trace_requested():
                argv.append('event_trace=1')
            if command(argv, out, 'load-slimbus', 4) or not transaction_active():
                raise ValueError('SLIMbus transaction instrumentation load failed')
        for name in MODULES:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise ValueError('audio provider initialization deadline expired')
            argv = ['modprobe', '-C', '/dev/null', '--ignore-install', name]
            if name == 'snd_soc_wcd9335': argv.append('port_diagnostics=1')
            if name == 'slim_qcom_ngd_ctrl' and removal_requested():
                if not transaction_requested() or not transaction_active():
                    raise ValueError('NGD removal requires SLIMbus transaction evidence')
                argv.append('channel_removal=1')
            if command(argv, out, 'load-'+name, min(4, remaining)):
                raise ValueError('audio provider load failed: '+name)
            if name == 'slim_qcom_ngd_ctrl' and removal_requested() and not removal_active():
                raise ValueError('NGD channel removal experiment load failed')
        while time.monotonic() < deadline:
            if audio_ready():
                check_gate(evidence(), config, time.clock_gettime(time.CLOCK_BOOTTIME))
                return
            time.sleep(1)
        raise ValueError('ALSA card/codec/capture device readiness deadline expired')
    finally:
        command(['dmesg'], out, 'provider-kernel', 3)


def main(config, sources):
    result = {'status': 'BLOCKED', 'media_saved': False, 'files': {}}
    out = None
    try:
        repetitions = config.get('repetitions', 1)
        if type(repetitions) is not int or repetitions not in (1, 2, 3):
            raise ValueError('capture count must be between one and three')
        result['requested'] = repetitions
        if os.geteuid() != 0 or b'samsung,gts3llte\0' not in Path('/proc/device-tree/compatible').read_bytes():
            raise ValueError('requires root on SM-T825')
        check_gate(evidence(), config, time.clock_gettime(time.CLOCK_BOOTTIME), preparing=True)
        if set(sources) != {'t825-audio-mic-phases.py', 't825-validate.py'}:
            raise ValueError('unexpected collector source inventory')
        # Gate precedes every write. All files are confined to the verified
        # /run tmpfs; the recovery supervisor is never leased or cancelled.
        out = Path(tempfile.mkdtemp(prefix='t825-audio-ram-', dir='/run'))
        for name, content in sources.items():
            (out/name).write_text(content)
        prepare_audio(out, config)
        if command(['alsactl', '-f', str(out/'mixer-before.state'), 'store', '0'], out, 'mixer-store', 8):
            raise ValueError('could not snapshot mixer state')
        # The original static supervisor is independent of SSH and the Python
        # collector. If restoration hangs, its reset still ends this RAM boot.
        (out/'restoration-armed').write_text('Independent RAM reset supervisor verified; local restore follows capture.\n')
        try:
            result['collector_rc'] = command([
                sys.executable, str(out/'t825-audio-mic-phases.py'), '--output', str(out),
                '--repetitions', str(repetitions)
            ], out, 'collector', 45)
        finally:
            result['restore_rc'] = command(['alsactl', '-f', str(out/'mixer-before.state'), 'restore', '0'], out, 'mixer-restore', 8)
            result['restore_store_rc'] = command(['alsactl', '-f', str(out/'mixer-restored.state'), 'store', '0'], out, 'mixer-restored', 8)
        if event_trace_requested():
            trace = Path('/sys/module/slimbus/parameters/event_records')
            if not trace.is_file():
                raise ValueError('audio event trace parameter disappeared')
            spec = importlib.util.spec_from_file_location('mic_phases', out/'t825-audio-mic-phases.py')
            mic_phases = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mic_phases)
            # Whole-run view from sequence 0; early records may be overwritten.
            (out/'event-trace.txt').write_text(mic_phases.read_event_pages(0)[0])
        result['mixer_equal'] = (out/'mixer-before.state').read_bytes() == (out/'mixer-restored.state').read_bytes()
        decision = json.loads((out/'decision.json').read_text())
        result['capture_decision'] = decision
        if removal_requested():
            returns = []
            for trace in sorted(out.glob('mic-*-event-records.txt')):
                text = trace.read_text()
                header = re.search(r'\bcount=(\d+)\b[^\n]*\btotal=(\d+)\b[^\n]*\bdropped=(\d+)', text)
                if not header or int(header[3]) != 0:
                    raise ValueError('NGD event trace lost records')
                returns.extend(int(value) for value in re.findall(
                    r'\b\d+\s+\d+\s+controller-disable\s+-1\s+(-?\d+)', text))
            result['channel_removal_returns'] = returns
            if len(returns) != decision.get('captures_completed') or not returns or any(returns):
                raise ValueError('NGD removal callback success was not observed for every capture')
        result['status'] = 'PASS' if (result['collector_rc'] == result['restore_rc'] == result['restore_store_rc'] == 0
                                      and result['mixer_equal'] and decision.get('status') == 'PASS'
                                      and decision.get('captures_completed') == decision.get('requested') == repetitions
                                      and decision.get('boot_unchanged') is True
                                      and decision.get('media_saved') is False) else 'FAIL'
    except Exception as exc:
        result['reason'] = str(exc)
        if out is not None:
            result['status'] = 'FAIL'
    finally:
        if out is not None:
            # Collector saves metrics and text logs only, never PCM.
            for file in sorted(out.iterdir()):
                if file.is_file() and file.suffix != '.py':
                    result['files'][file.name] = file.read_text(errors='replace')
        print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    if 'CONFIG' not in globals() or 'SOURCES' not in globals():
        raise SystemExit('Use the frozen read-only cycle with --audio-probe')
    raise SystemExit(main(CONFIG, SOURCES))
