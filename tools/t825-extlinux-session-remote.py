#!/usr/bin/env python3
"""Executed through SSH stdin with CONFIG; no persistent helper installation."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

BOOT_DEVICE = '/dev/mmcblk0p45'
BOOT_UUID = 'c5e5c7d5-7019-4c4e-ba93-af3c61a96e1b'


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=8).stdout.strip()


def digest(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('configuration is not a regular file')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rename_checked(source, target, expected):
    # No replacement, including dangling symlinks. The caller holds the host
    # device lock and a remote /run lock; never use mv -f or a restore service.
    if target.exists() or target.is_symlink():
        raise ValueError('rename destination already exists')
    if source.parent.is_symlink() or digest(source) != expected:
        raise ValueError('source identity changed')
    os.rename(source, target)
    fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.sync()
    if digest(target) != expected or source.exists():
        raise ValueError('rename verification failed')


def execute(config):
    import fcntl
    with open('/run/t825-extlinux-session.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if b'samsung,gts3llte' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
            raise ValueError('wrong tablet')
        if Path('/proc/1/comm').read_text().strip() != 'systemd':
            raise ValueError('installed Arch with systemd is required')
        mount = json.loads(command(['findmnt', '-J', '-M', '/boot', '-o', 'SOURCE,FSTYPE,OPTIONS']))['filesystems']
        if len(mount) != 1 or mount[0]['source'] != BOOT_DEVICE or mount[0]['fstype'] != 'ext2':
            raise ValueError('unexpected boot mount')
        if 'rw' not in mount[0]['options'].split(','):
            raise ValueError('installed boot mount is not writable')
        if command(['blkid', '-c', '/dev/null', '-s', 'UUID', '-o', 'value', BOOT_DEVICE]) != BOOT_UUID:
            raise ValueError('wrong cache filesystem')
        conf = Path('/boot/extlinux/extlinux.conf')
        hidden = conf.with_name('extlinux.conf.fastboot')
        if conf.parent.is_symlink() or Path('/boot').is_symlink():
            raise ValueError('symlink in boot path')
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if config['mode'] == 'enter':
            if boot_id != config['boot_id']:
                raise ValueError('boot changed before entry')
            rename_checked(conf, hidden, config['sha256'])
            try:
                command(['systemd-run', '--unit=t825-fastboot-entry', '--on-active=3s',
                         '--timer-property=AccuracySec=1s', '/usr/bin/systemctl', 'reboot'])
            except Exception:
                rename_checked(hidden, conf, config['sha256'])
                raise
            return {'status': 'REBOOT_SCHEDULED', 'sha256': digest(hidden), 'boot_id': boot_id}
        if config['mode'] == 'undo-entry':
            if boot_id != config['boot_id']:
                raise ValueError('refusing undo in a different boot')
            command(['systemctl', 'stop', 't825-fastboot-entry.timer'])
            rename_checked(hidden, conf, config['sha256'])
        if hidden.exists() or hidden.is_symlink():
            raise ValueError('temporary boot filename already exists')
        sha = digest(conf)
        if config.get('sha256') and sha != config['sha256']:
            raise ValueError('restored configuration hash differs')
        return {'sha256': sha, 'content_base64': base64.b64encode(conf.read_bytes()).decode(),
                'boot_id': boot_id, 'version': Path('/proc/version').read_text().strip(),
                'device': BOOT_DEVICE, 'uuid': BOOT_UUID, 'mount': mount[0],
                'temporary_name_absent': True, 'pid1': 'systemd'}


if __name__ == '__main__':
    print(json.dumps(execute(CONFIG)))
