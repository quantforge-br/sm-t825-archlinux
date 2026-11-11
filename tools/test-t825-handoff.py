#!/usr/bin/env python3
"""Host-only regression checks for diagnostic boot safety and log collection."""
import importlib.util
import os
from pathlib import Path
import re
import socket
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


trace = module('handoff_trace', 'install/trace-t825-handoff.py')
guard = module('handoff_guard', 'install/guard-t825-diagnostic-root.py')
telnet = module('handoff_telnet', 'tools/t825-telnet.py')

INIT = '''#!/bin/sh
if [ "$debug_shell" = "y" ]; then
\tdebug_shell
fi
check_keys
mount_subpartitions
run_hooks /hooks-extra
wait_root_partition
delete_old_install_partition
resize_root_partition
unlock_root_partition
resize_root_filesystem
mount_root_partition
resize_filesystem_after_mount /sysroot
mount_boot_partition /sysroot/boot "rw"
run_hooks /hooks-cleanup
exec switch_root /sysroot "$init"
'''
FUNCTIONS = '''mount_root_partition() {
\ttype=btrfs
\tpartition=/dev/mock
\t# btrfs may be using multiple backing block devices, scan for the rest of them
\tif ! mount -t "$type" -o rw"$rootfsopts" "$partition" /sysroot; then
\t\treturn 1
\tfi
\tmount -t "$type" -o rw"$rootfsopts" "$partition" /stowaway
}
'''


class HandoffTests(unittest.TestCase):
    def test_runner_survives_edits_to_live_collector(self):
        # Fake fastboot and collector: no physical device is touched.
        with tempfile.TemporaryDirectory(prefix='t825-snapshot-') as directory:
            project = Path(directory)
            source = project / 'tools'
            source.mkdir()
            shutil.copyfile(ROOT / 'tools/t825-gnss-auto-cycle.sh',
                            source / 't825-gnss-auto-cycle.sh')
            (source / 'test-t825-gnss-ram-image.py').write_text('pass\n')
            (source / 't825-telnet.py').write_text('pass\n')
            collector = source / 't825-gnss-hold-test.sh'
            collector.write_text('''#!/bin/bash
set -eu
mkdir -p "$2"
touch "$2/boot-disconnected" "$2/waiting"
for ((i=0; i<100; i++)); do
    [ ! -e "$2/release" ] || break
    sleep 0.02
done
test -e "$2/release"
echo ORIGINAL > "$2/collector-result"
''')
            commands = project / 'commands'
            commands.mkdir()
            fastboot = commands / 'fastboot'
            fastboot.write_text('''#!/bin/sh
case "$*" in
    devices) printf 'mock-tablet\\tfastboot\\n' ;;
    '-s mock-tablet getvar lk2nd:compatible')
        echo 'lk2nd:compatible: samsung,gts3llte' >&2 ;;
    *) exit 77 ;;
esac
''')
            fastboot.chmod(0o755)
            report = project / 'report'
            env = dict(os.environ, T825_SOURCE_ROOT=str(project),
                       T825_REPORT_DIR=str(report),
                       PATH=str(commands) + os.pathsep + os.environ['PATH'])
            env.pop('T825_RUNNER_SNAPSHOT', None)
            with subprocess.Popen(['bash', str(source / 't825-gnss-auto-cycle.sh'),
                                   str(project / 'mock.img')], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                try:
                    deadline = time.monotonic() + 5
                    while not (report / 'cycle-1/waiting').exists():
                        self.assertIsNone(process.poll())
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.02)
                    collector.write_text("broken ' source\n")
                    (report / 'cycle-1/release').touch()
                    _, error = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, error)
                    self.assertEqual((report / 'cycle-1/collector-result').read_text(),
                                     'ORIGINAL\n')
                    self.assertIn('1\t0\t1\t', (report / 'results.tsv').read_text())
                    subprocess.run(['sha256sum', '-c', str(report / 'runner.sha256')],
                                   check=True, capture_output=True)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()

    def test_trace_is_repeatable_and_rejects_drift(self):
        changed = trace.instrument(INIT)
        self.assertEqual(trace.instrument(changed), changed)
        for stage in ('pre-mount-root', 'post-mount-root', 'post-cleanup', 'pre-switch-root'):
            self.assertIn('trace_handoff_stage ' + stage, changed)
        self.assertIn('exec switch_root /sysroot "$init"', changed)
        self.assertIn('busybox timeout 2', changed)
        with self.assertRaises(ValueError):
            trace.instrument(INIT.replace('mount_root_partition\n', 'unknown\n'))

    def test_guard_prevents_mutations_after_tracing(self):
        init, functions = guard.guard(trace.instrument(INIT), FUNCTIONS, True)
        for call in ('delete_old_install_partition', 'resize_root_partition',
                     'resize_root_filesystem', 'resize_filesystem_after_mount /sysroot'):
            self.assertNotIn(call, init.splitlines())
        self.assertNotIn('-o rw', functions)
        self.assertIn('t825_root_mountopts=ro,rescue=nologreplay', functions)
        self.assertLess(functions.index('busybox blockdev --setro'),
                        functions.index('if ! mount'))
        self.assertIn('mount -o remount,ro /sysroot', init)
        self.assertNotIn('mount_boot_partition /sysroot/boot', init)
        self.assertEqual(guard.guard(init, functions, True), (init, functions))
        with self.assertRaises(ValueError):
            guard.guard(INIT.replace('resize_root_partition\n', ''), FUNCTIONS, True)

    def test_root_write_protection_fails_closed(self):
        _, functions = guard.guard(INIT, FUNCTIONS, True)
        # Execute the actual generated shell with mocked block/mount commands.
        # A failed write-protection ioctl must never reach mount.
        for block_status in (0, 1):
            script = '''
find_root_partition() { partition=/dev/mock; }
get_partition_type() { echo btrfs; }
modprobe() { :; }
btrfs() { :; }
blkid() {
    case "$*" in
        '-s UUID -o value /dev/mock') echo mock-uuid ;;
        '-c /dev/null -t UUID=mock-uuid -o device') printf '/dev/mock\\n/dev/mock2\\n' ;;
        *) exit 77 ;;
    esac
}
mountpoint() { return 1; }
busybox() {
    echo "$*" >&2
    case "$*" in
        'blockdev --setro /dev/mock') return BLOCK_STATUS ;;
        'blockdev --setro /dev/mock2') return 0 ;;
        'blockdev --getro /dev/mock'|'blockdev --getro /dev/mock2') echo 1 ;;
    esac
}
mount() { echo "MOUNT $*"; }
fail_halt_boot() { exit 19; }
rootfsopts=,subvol=/@
''' .replace('BLOCK_STATUS', str(block_status)) + functions + '\nmount_root_partition\n'
            result = subprocess.run(['sh'], input=script, text=True, capture_output=True)
            if block_status:
                self.assertEqual(result.returncode, 19, result.stderr)
                self.assertNotIn('MOUNT ', result.stdout)
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('MOUNT -t btrfs -o ro,rescue=nologreplay,subvol=/@', result.stdout)
                self.assertIn('blockdev --setro /dev/mock2', result.stderr)

    def test_fragmented_telnet_negotiation(self):
        stream = telnet.TelnetStream()
        self.assertEqual(stream.decode(b'a\xff\xfb'), (b'a', b''))
        self.assertEqual(stream.decode(b'\x01b\xff\xff'), (b'b\xff', b'\xff\xfe\x01'))
        self.assertEqual(stream.decode(b'\xff\xfa\x1f\x01\xff\xf0ok'), (b'ok', b''))

    def test_client_waits_for_output_and_returns_remote_status(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(5)
            errors = []

            def serve():
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(5)
                        connection.sendall(b'\xff\xfd\x1fmock # ')
                        command = bytearray()
                        while b'\r\n' not in command:
                            chunk = connection.recv(4096)
                            if not chunk:
                                raise RuntimeError('premature input EOF')
                            command.extend(chunk)
                        token = re.search(rb"'T825_DONE_' '([0-9a-f]+)'", command)[1]
                        connection.sendall(command)
                        for _ in range(8):
                            connection.sendall(b'x' * 4096)
                            time.sleep(0.01)
                        connection.sendall(b'\r\nT825_DONE_' + token + b':7\r\n')
                except Exception as exc:
                    errors.append(exc)

            server = threading.Thread(target=serve)
            server.start()
            result = subprocess.run(
                [sys.executable, str(ROOT / 'tools/t825-telnet.py'), '--host',
                 '127.0.0.1', '--port', str(listener.getsockname()[1]), '--timeout', '5'],
                input=b'echo hello\n', capture_output=True, timeout=8,
            )
            server.join(timeout=6)
            self.assertFalse(server.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertGreaterEqual(result.stdout.count(b'x'), 32768)


if __name__ == '__main__':
    unittest.main()
