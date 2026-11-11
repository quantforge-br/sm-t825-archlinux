#!/usr/bin/env python3
"""Bounded hardware checks on the tablet; raw camera/microphone data is not saved.

Run as the graphical-session user (sudo -n must work for suspend/kernel logs).
Each run gets a new private evidence directory. Checks are deliberately opt-in:
cameras acquires both cameras, audio opens the microphone, suspend sleeps the
tablet with an RTC alarm, and gpu deliberately hangs the GPU.
"""
import argparse
import array
import ctypes
import fcntl
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class UCM:
    """Keep one libasound use-case manager open across route changes."""
    def __enter__(self):
        self.lib = ctypes.CDLL("libasound.so.2")
        self.lib.snd_use_case_mgr_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p]
        self.lib.snd_use_case_mgr_open.restype = ctypes.c_int
        self.lib.snd_use_case_set.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.lib.snd_use_case_set.restype = ctypes.c_int
        self.lib.snd_use_case_mgr_close.argtypes = [ctypes.c_void_p]
        self.lib.snd_use_case_mgr_close.restype = ctypes.c_int
        self.manager = ctypes.c_void_p()
        rc = self.lib.snd_use_case_mgr_open(ctypes.byref(self.manager), b"hw:0")
        if rc < 0:
            raise RuntimeError(f"UCM open failed: {rc}")
        return self

    def set(self, key, value):
        rc = self.lib.snd_use_case_set(self.manager, key.encode(), value.encode())
        if rc < 0:
            raise RuntimeError(f"UCM {key}={value}: {rc}")

    def __exit__(self, *unused):
        rc = self.lib.snd_use_case_mgr_close(self.manager)
        if rc < 0:
            raise RuntimeError(f"UCM close failed: {rc}")


class Blocked(Exception):
    pass


def execute(argv, timeout=30, required=True):
    if not shutil.which(str(argv[0])):
        raise Blocked(f"missing command: {argv[0]}")
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"command timed out after {timeout}s: {argv[0]}") from e
    result = {"argv": list(map(str, argv)), "rc": p.returncode,
              "stdout": p.stdout.decode(errors="replace"),
              "stderr": p.stderr.decode(errors="replace")}
    if required and p.returncode:
        raise RuntimeError(f"{argv[0]} failed ({p.returncode}): {result['stderr'][-2000:]}")
    return result


def pcm_metrics(data):
    """s16le stereo; retain levels/counts, never microphone samples."""
    if not data or len(data) % 4:
        raise ValueError(f"expected complete stereo s16le frames, got {len(data)} bytes")
    samples = array.array("h", data)
    if sys.byteorder != "little":
        samples.byteswap()
    channels = []
    for offset in (0, 1):
        values = samples[offset::2]
        rms = math.sqrt(sum(v * v for v in values) / len(values))
        channels.append({"rms_dbfs": round(20 * math.log10(max(rms, 1e-12) / 32768), 2),
                         "peak": max(map(abs, values)),
                         "clipped": sum(abs(v) >= 32767 for v in values)})
    return {"frames": len(samples) // 2, "channels": channels}


def camera_frames(log, expected):
    rows = re.findall(r"^\s*([\d.]+) \(([\d.]+) fps\).* seq:\s*(\d+) bytesused:\s*(\d+)", log, re.MULTILINE)
    if len(rows) != expected:
        raise ValueError(f"captured {len(rows)}/{expected} frames")
    sequence = [int(r[2]) for r in rows]
    if any(b != a + 1 for a, b in itertools.pairwise(sequence)):
        raise ValueError("camera sequence has gaps or duplicates")
    if any(int(r[3]) == 0 for r in rows):
        raise ValueError("empty camera buffer")
    elapsed = float(rows[-1][0]) - float(rows[0][0])
    if elapsed <= 0:
        raise ValueError("non-increasing frame timestamps")
    fps = (len(rows) - 1) / elapsed
    if not 27 <= fps <= 33:
        raise ValueError(f"camera outside 30fps tolerance: {fps:.2f}")
    return {"frames": len(rows), "fps": round(fps, 2),
            "first_sequence": sequence[0], "last_sequence": sequence[-1]}


FAULTS = re.compile(r"wcd9335.*(?:overflow|underflow)|Opcode 0x0c03.*failed|ME master split|remoteproc.*crash|Internal error:|Kernel panic|(?:streamdiag|portdiag)[^\n]*\b(?:\w+_)?rc=-[1-9][0-9]*", re.IGNORECASE)


def kernel_delta(before, after):
    """Return only new lines, even when the kernel ring buffer wrapped."""
    if after.startswith(before):
        return after[len(before):], False
    old = before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    # Match the retained suffix including timestamps, rather than comparing
    # timestamp magnitudes: separate records may have identical timestamps.
    # No overlap means some test-time records may have been lost; don't pass.
    if not old:
        raise Blocked("kernel log has no baseline to establish continuity")
    anchors = [i for i, line in enumerate(new) if line == old[-1]]
    if len(anchors) != 1:
        raise Blocked("kernel log continuity lost or ambiguous after ring rotation")
    end = anchors[0] + 1
    if end > len(old) or new[:end] != old[-end:]:
        raise Blocked("kernel log continuity lost after ring rotation")
    return "".join(new[end:]), True


class Checks:
    def __init__(self, out):
        self.out = out
        self.results = []
        self.priv = [] if os.geteuid() == 0 else ["sudo", "-n"]

    def save(self, name, value):
        path = self.out / name
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        path.write_text(value)

    def kernel_log(self):
        return execute(self.priv + ["dmesg"], timeout=10)["stdout"]

    def check(self, name, fn):
        before = self.kernel_log()
        start = datetime.now(UTC).isoformat()
        try:
            evidence = fn()
            status, reason = "PASS", "bounded check passed; see scope in evidence"
        except Blocked as e:
            status, reason, evidence = "BLOCKED", str(e), {}
        except (OSError, RuntimeError, ValueError) as e:
            status, reason, evidence = "FAIL", str(e), {}
        after = self.kernel_log()
        # Retain the baseline to audit continuity after ring-buffer rotation.
        self.save(f"{name}-kernel-before.txt", before)
        try:
            delta, rotated = kernel_delta(before, after)
        except Blocked as exc:
            delta, rotated = "", True
            evidence["kernel_log_gap"] = str(exc)
            if status == "PASS":
                status, reason = "BLOCKED", str(exc)
        if rotated:
            self.save(f"{name}-kernel-full.txt", after)
        self.save(f"{name}-kernel.txt", delta)
        faults = FAULTS.findall(delta)
        if faults:
            status, reason = "FAIL", f"kernel fault observed: {faults}"
            evidence["kernel_faults"] = faults
        if rotated:
            evidence["dmesg_rotated"] = True
            evidence["overlap_verified"] = "kernel_log_gap" not in evidence
        self.results.append({"check": name, "started_utc": start, "status": status,
                             "reason": reason, "evidence": evidence})
        self.save("results.json", self.results)
        print(f"{name}: {status} — {reason}", flush=True)
        return status == "PASS"

    def cameras(self, repetitions, frames):
        metrics = []
        for repeat in range(repetitions):
            for camera in (1, 2):
                result = execute(["cam", "-c", str(camera), "--strict-formats", "--stream",
                                  "width=1280,height=720,role=video", f"--capture={frames}"],
                                 timeout=30, required=False)
                self.save(f"camera-{camera}-{repeat + 1}.json", result)
                if result["rc"]:
                    raise RuntimeError(f"camera {camera} returned {result['rc']}")
                summary = camera_frames(result["stdout"], frames)
                metrics.append({"camera": camera, "repeat": repeat + 1, **summary})
        return {"scope": "stream delivery and frame rate, not image quality/calibration",
                "runs": metrics, "media_saved": False}

    def audio(self, repetitions):
        execute(["wpctl", "status"], timeout=10)
        metrics = []
        for repeat in range(repetitions):
            # Capture one second through the explicit ALSA PipeWire plugin.
            # PCM is held only in memory and reduced to level/count metrics.
            p = subprocess.run(["arecord", "-D", "pipewire", "-t", "raw", "-f", "S16_LE",
                                "-r", "48000", "-c", "2", "-d", "1", "-"],
                               capture_output=True, check=False, timeout=10)
            self.save(f"audio-{repeat + 1}.txt", p.stderr.decode(errors="replace"))
            if p.returncode:
                raise RuntimeError(f"arecord failed ({p.returncode})")
            data = pcm_metrics(p.stdout)
            if data["frames"] != 48000:
                raise ValueError(f"short audio capture: {data['frames']}/48000 frames")
            metrics.append({"repeat": repeat + 1, **data})
        return {"scope": "default microphone stream; not headset routing or acoustic speaker validation",
                "runs": metrics, "media_saved": False}

    def audio_routes(self, repetitions):
        """Isolate UCM enable, PCM transfer and disable with complete kernel deltas."""
        for status in Path('/proc/asound/card0').glob('pcm*/sub*/status'):
            if status.read_text().strip() != 'closed':
                raise Blocked(f"active PCM; preserve current audio session: {status}")
        snapshot = self.out / 'mixer-before.state'
        execute(['alsactl', '-f', str(snapshot), 'store', '0'])
        self.save('ucm-hifi.conf', Path('/usr/share/alsa/ucm2/Samsung/gts3lwifi/HiFi.conf').read_text())
        self.save('alsa-controls-before.txt', execute(['amixer', '-c', '0', 'contents'])['stdout'])
        previous = self.kernel_log()
        rows = []
        stages = []

        def stage(name, operation):
            nonlocal previous
            started = time.clock_gettime(time.CLOCK_BOOTTIME)
            value = operation()
            # Account for deferred IRQ reporting at the phase boundary.
            time.sleep(0.2)
            after = self.kernel_log()
            self.save(f'{name}-kernel-before.txt', previous)
            self.save(f'{name}-kernel-after.txt', after)
            delta, rotated = kernel_delta(previous, after)
            self.save(f'{name}-kernel.txt', delta)
            previous = after
            record = {'stage': name, 'boottime_started': started,
                      'kernel_faults': FAULTS.findall(delta), 'log_rotated': rotated}
            stages.append(record)
            self.save('audio-route-stages.json', stages)
            return value

        old_handlers = {}
        def interrupt(signum, frame):
            raise RuntimeError(f'audio routes interrupted by signal {signum}')
        for sig in (signal.SIGTERM, signal.SIGHUP):
            old_handlers[sig] = signal.signal(sig, interrupt)
        try:
            with UCM() as ucm:
                stage('verb-hifi', lambda: ucm.set('_verb', 'HiFi'))
                for repeat in range(1, repetitions + 1):
                    for device, pcm in (('Speaker', 'hw:0,0'), ('Headphones', 'hw:0,1'), ('Mic', 'hw:0,2')):
                        name = f'route-{repeat}-{device.lower()}'
                        stage(name + '-enable', lambda: ucm.set('_enadev', device))
                        try:
                            def transfer():
                                argv = ['arecord' if device == 'Mic' else 'aplay', '-D', pcm,
                                        '-t', 'raw', '-f', 'S16_LE', '-r', '48000', '-c', '2', '-d', '1', '-']
                                p = subprocess.run(argv, input=None if device == 'Mic' else bytes(192000),
                                                   capture_output=True, timeout=10, check=False)
                                self.save(name + '-pcm.json', {'argv': argv, 'rc': p.returncode,
                                          'stderr': p.stderr.decode(errors='replace')})
                                if p.returncode:
                                    raise RuntimeError(f'{device} transfer failed: {p.returncode}')
                                metrics = pcm_metrics(p.stdout) if device == 'Mic' else {'frames_sent': 48000}
                                if device == 'Mic' and metrics['frames'] != 48000:
                                    raise ValueError(f'short capture: {metrics["frames"]}')
                                return metrics
                            metrics = stage(name + '-transfer', transfer)
                        finally:
                            stage(name + '-disable', lambda: ucm.set('_disdev', device))
                        rows.append({'repeat': repeat, 'device': device, **metrics})
                    print(f'audio routes: cycle {repeat}/{repetitions} completed', flush=True)
        finally:
            try:
                execute(['alsactl', '-f', str(snapshot), 'restore', '0'])
                restored = self.out / 'mixer-restored.state'
                execute(['alsactl', '-f', str(restored), 'store', '0'])
                same = snapshot.read_bytes() == restored.read_bytes()
                self.save('mixer-restoration.json', {'restore_command_succeeded': True, 'exact_state_match': same})
                if not same:
                    raise RuntimeError('ALSA mixer state differs after restoration')
            finally:
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
        return {'scope': 'same UCM context, silent playback and stereo capture delivery; '
                         'not acoustic validation, individual mic isolation or physical CTIA insertion',
                'media_saved': False, 'runs': rows, 'stages': stages, 'mixer_restored': True}

    def gpu(self, binary, repetitions):
        if not binary or not binary.is_file() or not os.access(binary, os.X_OK):
            raise Blocked("--gpu-binary must be the compiled tools/gpuhang.c")
        compositor = execute(["pgrep", "-x", "Hyprland"], required=False)["stdout"].split()
        if len(compositor) != 1:
            raise Blocked("exactly one running Hyprland required")
        pid = compositor[0]
        proc = Path(f"/proc/{pid}/stat")
        starttime = proc.read_text().rsplit(")", 1)[1].split()[19]
        results = []
        for repeat in range(repetitions):
            before = self.kernel_log()
            draw = execute([str(binary), "1"], timeout=15, required=False)
            self.save(f"gpu-hang-{repeat + 1}.json", draw)
            if draw["rc"] or "reset status 0x8253 (GUILTY)" not in draw["stdout"]:
                raise RuntimeError("injected hang did not return a guilty reset")
            short = execute([str(binary), "2000"], timeout=15, required=False)
            self.save(f"gpu-short-{repeat + 1}.json", short)
            if short["rc"] or "reset status 0x0" not in short["stdout"]:
                raise RuntimeError("normal draw failed after recovery")
            if not proc.exists() or proc.read_text().rsplit(")", 1)[1].split()[19] != starttime:
                raise RuntimeError("Hyprland exited or was replaced")
            after = self.kernel_log()
            self.save(f"gpu-kernel-before-{repeat + 1}.txt", before)
            self.save(f"gpu-kernel-after-{repeat + 1}.txt", after)
            delta, _ = kernel_delta(before, after)
            self.save(f"gpu-kernel-{repeat + 1}.txt", delta)
            culprits = re.findall(r"offending task: ([^ (]+)", delta)
            if culprits != [binary.name]:
                raise RuntimeError(f"unexpected GPU culprits: {culprits}")
            results.append({"repeat": repeat + 1, "guilty": True, "normal_draw": True,
                            "hyprland_same_process": True})
        return {"scope": "synthetic reset recovery, not Chromium rasterization root cause",
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "runs": results}

    def suspend(self, seconds, network, peer):
        counter = Path("/sys/power/suspend_stats/success")
        if not counter.is_file():
            raise Blocked("suspend success counter unavailable")
        alarm = Path("/sys/class/rtc/rtc0/wakealarm")
        if not alarm.is_file() or "[s2idle]" not in Path("/sys/power/mem_sleep").read_text():
            raise Blocked("RTC alarm or selected s2idle unavailable")
        existing = execute(self.priv + ["cat", str(alarm)])["stdout"].strip()
        if existing:
            raise Blocked("existing RTC alarm; preserving it and refusing suspend")
        if not Path(f"/sys/class/net/{network}").is_dir():
            raise Blocked(f"network interface absent: {network}")
        before = int(counter.read_text())
        t0 = time.clock_gettime(time.CLOCK_BOOTTIME)
        execute(self.priv + ["rtcwake", "-d", "/dev/rtc0", "-m", "no", "-s", str(seconds)])
        armed = execute(self.priv + ["cat", str(alarm)])["stdout"].strip()
        if not armed.isdigit() or int(armed) <= 0:
            raise RuntimeError("RTC alarm was not armed; refusing suspend")
        try:
            execute(self.priv + ["systemctl", "suspend"], timeout=10)
            # systemctl returns before sleep: only the kernel success counter
            # and a new exit record can prove completion.
            while time.clock_gettime(time.CLOCK_BOOTTIME) - t0 < seconds + 45:
                if int(counter.read_text()) > before:
                    break
                time.sleep(1)
            after = int(counter.read_text())
            if after != before + 1:
                raise RuntimeError(f"expected one completed suspend, counter {before} -> {after}")
            elapsed = time.clock_gettime(time.CLOCK_BOOTTIME) - t0
            if elapsed < seconds - 3:
                raise RuntimeError(f"early wake after {elapsed:.2f}s; requested {seconds}s")
            # NetworkManager reconnection is asynchronous; wait at most 15s.
            deadline = time.monotonic() + 15
            while Path(f"/sys/class/net/{network}/operstate").read_text().strip() != "up":
                if time.monotonic() >= deadline:
                    raise RuntimeError("Wi-Fi did not return to up state")
                time.sleep(1)
            traffic = execute(["ping", "-I", network, "-c", "3", "-W", "2", peer],
                              timeout=10, required=False)
            self.save("suspend-traffic.json", traffic)
            if traffic["rc"]:
                raise RuntimeError("Wi-Fi has no bidirectional ICMP traffic to test peer")
            if not Path("/sys/class/bluetooth/hci0").exists():
                raise RuntimeError("Bluetooth controller disappeared")
            audio = execute(["wpctl", "status"], timeout=10)
            self.save("suspend-audio.txt", audio["stdout"])
            sensors = sorted(p.read_text().strip() for p in Path("/sys/bus/iio/devices").glob("iio:device*/name"))
            for name in ("qcom-smgr-accel", "qcom-smgr-gyro", "qcom-smgr-mag", "qcom-smgr-light"):
                if name not in sensors:
                    raise RuntimeError(f"sensor disappeared: {name}")
            return {"scope": "RTC wake, kernel suspend counter, Wi-Fi ICMP, device/service presence; not acoustic or visual checks",
                    "seconds": round(elapsed, 2), "counter_before": before,
                    "counter_after": after, "traffic_peer": peer}
        finally:
            # The run only owns the alarm it just armed; no previous alarm is removed.
            execute(self.priv + ["rtcwake", "-d", "/dev/rtc0", "-m", "disable"], required=False)


@contextmanager
def validation_lock(uid):
    """Keep the per-user validation lock alive for the whole check."""
    lock_path = Path(f"/run/user/{uid}/t825-validation.lock")
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Blocked("another hardware validation is running") from exc
        yield


def run_checks(args):
    """Run one serialized validation and return its process status."""
    os.umask(0o077)
    uid = os.getuid()
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    with validation_lock(uid):
        args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        c = Checks(args.output)
        c.save("identity.json", {"uname": list(os.uname()),
                                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                                "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        if args.check == "cameras":
            c.check("cameras", lambda: c.cameras(args.repetitions, args.frames))
        elif args.check == "audio":
            c.check("audio", lambda: c.audio(args.repetitions))
        elif args.check == "audio-routes":
            c.check("audio-routes", lambda: c.audio_routes(args.repetitions))
        elif args.check == "gpu":
            c.check("gpu", lambda: c.gpu(args.gpu_binary, args.repetitions))
        else:
            for index in range(args.repetitions):
                if not c.check(f"suspend-{index + 1}", lambda: c.suspend(args.seconds, args.network, args.peer)):
                    break
        hashes = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n"
                  for f in sorted(args.output.iterdir()) if f.is_file()]
        c.save("SHA256SUMS", "".join(hashes))
        return 0 if c.results and all(r["status"] == "PASS" for r in c.results) else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("check", choices=["cameras", "audio", "audio-routes", "suspend", "gpu"])
    p.add_argument("--output", type=Path, required=True, help="new private evidence directory")
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--frames", type=int, default=90)
    p.add_argument("--seconds", type=int, default=20)
    p.add_argument("--network", default="wlp1s0")
    p.add_argument("--peer", help="reachable ICMP peer on the Wi-Fi network (required for suspend)")
    p.add_argument("--gpu-binary", type=Path, help="compiled tools/gpuhang.c (gpu test only)")
    args = p.parse_args()
    if not 1 <= args.repetitions <= 20 or not 30 <= args.frames <= 900 or not 10 <= args.seconds <= 60:
        p.error("repetitions: 1..20, frames: 30..900, seconds: 10..60")
    if args.check == "suspend" and (not args.peer or args.peer.startswith("-")):
        p.error("suspend requires --peer=<reachable-Wi-Fi-peer>")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.network) or args.network in (".", ".."):
        p.error("invalid network interface name")
    model = Path("/proc/device-tree/compatible")
    if not model.is_file() or b"samsung,gts3llte\0" not in model.read_bytes():
        p.error("this checker requires the SM-T825 device tree")
    if os.geteuid() == 0:
        p.error("run as the desktop user; privileged operations use sudo -n")
    try:
        return run_checks(args)
    except Blocked as exc:
        p.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
