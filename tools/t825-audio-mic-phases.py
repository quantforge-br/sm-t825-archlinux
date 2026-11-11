#!/usr/bin/env python3
"""Split one T825 microphone capture into ALSA lifecycle phases; save no PCM."""
import argparse
import ctypes as C
import errno
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import time

spec = importlib.util.spec_from_file_location("validate", Path(__file__).with_name("t825-validate.py"))
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


EVENT_RECORDS = Path("/sys/module/slimbus/parameters/event_records")
EVENT_CURSOR = Path("/sys/module/slimbus/parameters/event_cursor")
EVENT_HEADER = re.compile(r"enabled=(\d+) count=(\d+) total=(\d+) dropped=(\d+) first=(\d+) next=(\d+)")


def read_event_pages(cursor, records=EVENT_RECORDS, cursor_file=EVENT_CURSOR, max_pages=16):
    """Page the kernel ring from cursor; return contiguous text and next cursor.

    The combined header sums the loss reported by every page, so a reader that
    fell behind the 256-record ring cannot present a gap as complete evidence.
    """
    lines, dropped, start = [], 0, None
    for _ in range(max_pages):
        cursor_file.write_text(f"{cursor}\n")
        page = records.read_text().splitlines()
        match = EVENT_HEADER.fullmatch(page[0]) if page else None
        if not match:
            raise ValueError("malformed audio event page")
        enabled, count, total, lost, first, following = map(int, match.groups())
        body = page[1:]
        if len(body) != count or following != first + count or first != cursor + lost:
            raise ValueError("inconsistent audio event page")
        for index, line in enumerate(body):
            if int(line.split()[0]) != first + index:
                raise ValueError("noncontiguous audio event page")
        dropped += lost
        start = first if start is None else start
        lines.extend(body)
        cursor = following
        if following >= total:
            break
    else:
        raise ValueError("audio event paging did not reach the ring head")
    header = (f"enabled={enabled} count={len(lines)} total={total} dropped={dropped} "
              f"first={start} next={cursor}\n")
    return header + "".join(line + "\n" for line in lines), cursor


def event_head(records=EVENT_RECORDS, cursor_file=EVENT_CURSOR):
    """Return the next sequence; a cursor past the head yields an empty page."""
    cursor_file.write_text(f"{2 ** 63}\n")
    page = records.read_text().splitlines()
    match = EVENT_HEADER.fullmatch(page[0]) if page else None
    if not match or int(match[2]) != 0 or int(match[5]) != int(match[3]):
        raise ValueError("malformed audio event head page")
    return int(match[3])


class Capture:
    """Explicit nonblocking PCM lifecycle; never recover an xrun silently."""
    def __init__(self, library=None):
        self.lib = library if library is not None else C.CDLL("libasound.so.2")
        pointer = C.c_void_p
        definitions = {
            "open": ([C.POINTER(pointer), C.c_char_p, C.c_int, C.c_int], C.c_int),
            "close": ([pointer], C.c_int),
            "hw_params_malloc": ([C.POINTER(pointer)], C.c_int),
            "hw_params_free": ([pointer], None),
            "hw_params_any": ([pointer, pointer], C.c_int),
            "hw_params_set_access": ([pointer, pointer, C.c_int], C.c_int),
            "hw_params_set_format": ([pointer, pointer, C.c_int], C.c_int),
            "hw_params_set_channels": ([pointer, pointer, C.c_uint], C.c_int),
            "hw_params_set_rate_near": ([pointer, pointer, C.POINTER(C.c_uint), C.POINTER(C.c_int)], C.c_int),
            "hw_params_set_period_size_near": ([pointer, pointer, C.POINTER(C.c_ulong), C.POINTER(C.c_int)], C.c_int),
            "hw_params_set_buffer_size_near": ([pointer, pointer, C.POINTER(C.c_ulong)], C.c_int),
            "hw_params": ([pointer, pointer], C.c_int),
            "hw_params_get_rate": ([pointer, C.POINTER(C.c_uint), C.POINTER(C.c_int)], C.c_int),
            "hw_params_get_channels": ([pointer, C.POINTER(C.c_uint)], C.c_int),
            "hw_params_get_period_size": ([pointer, C.POINTER(C.c_ulong), C.POINTER(C.c_int)], C.c_int),
            "hw_params_get_buffer_size": ([pointer, C.POINTER(C.c_ulong)], C.c_int),
            "prepare": ([pointer], C.c_int),
            "start": ([pointer], C.c_int),
            "readi": ([pointer, pointer, C.c_ulong], C.c_long),
            "wait": ([pointer, C.c_int], C.c_int),
            "drop": ([pointer], C.c_int),
            "state": ([pointer], C.c_int),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.lib, "snd_pcm_" + name)
            function.argtypes = args
            function.restype = result
        self.handle = pointer()
        self.opened = False
        self.configuration = {}

    def call(self, name, *args):
        result = getattr(self.lib, "snd_pcm_" + name)(*args)
        if result < 0:
            raise RuntimeError(f"snd_pcm_{name}: {result} ({os.strerror(-result)})")
        return result

    def open(self):
        # CAPTURE=1, NONBLOCK=1; hw interface has no plugin xrun recovery.
        self.call("open", C.byref(self.handle), b"hw:0,2", 1, 1)
        self.opened = True

    def params(self):
        params = C.c_void_p()
        self.call("hw_params_malloc", C.byref(params))
        try:
            self.call("hw_params_any", self.handle, params)
            self.call("hw_params_set_access", self.handle, params, 3)  # RW_INTERLEAVED
            self.call("hw_params_set_format", self.handle, params, 2)  # S16_LE
            self.call("hw_params_set_channels", self.handle, params, 2)
            rate, direction = C.c_uint(48000), C.c_int(0)
            period, buffer = C.c_ulong(4800), C.c_ulong(96000)
            self.call("hw_params_set_rate_near", self.handle, params, C.byref(rate), C.byref(direction))
            self.call("hw_params_set_period_size_near", self.handle, params, C.byref(period), C.byref(direction))
            self.call("hw_params_set_buffer_size_near", self.handle, params, C.byref(buffer))
            self.call("hw_params", self.handle, params)
            channels = C.c_uint()
            self.call("hw_params_get_rate", params, C.byref(rate), C.byref(direction))
            self.call("hw_params_get_channels", params, C.byref(channels))
            self.call("hw_params_get_period_size", params, C.byref(period), C.byref(direction))
            self.call("hw_params_get_buffer_size", params, C.byref(buffer))
            self.configuration = {"rate": rate.value, "channels": channels.value,
                                  "period_frames": period.value, "buffer_frames": buffer.value,
                                  "format": "S16_LE", "access": "RW_INTERLEAVED"}
            if rate.value != 48000 or channels.value != 2 or period.value == 0 or buffer.value < 2 * period.value:
                raise validate.Blocked(f"unsupported diagnostic PCM geometry: {self.configuration}")
            return self.configuration
        finally:
            self.lib.snd_pcm_hw_params_free(params)

    def prepare(self):
        self.call("prepare", self.handle)

    def read(self, frames=48000, timeout=5):
        # Never insert log I/O, metric reduction or sleep between the final read
        # and explicit drop: the actual hardware buffer is only 7680 frames
        # (160 ms at 48 kHz). Reduce in-memory data only after stopping PCM.
        self.call("start", self.handle)
        deadline = time.monotonic() + timeout
        data = bytearray()
        count = 0
        chunk = C.create_string_buffer(4096 * 4)
        while count < frames:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"capture deadline: {count}/{frames} frames")
            requested = min(4096, frames - count)
            result = self.lib.snd_pcm_readi(self.handle, chunk, requested)
            if result == -errno.EAGAIN or result == 0:
                self.call("wait", self.handle, 100)
                continue
            if result < 0:
                raise RuntimeError(f"capture failed: {result} ({os.strerror(-result)}); no recovery attempted")
            if result > requested:
                raise RuntimeError("ALSA returned more frames than requested")
            data.extend(chunk.raw[:result * 4])
            count += result
        # SND_PCM_STATE_RUNNING=3. A post-read xrun must invalidate the capture.
        if self.call("state", self.handle) != 3:
            raise RuntimeError("PCM was not RUNNING after capture")
        return data

    def drop(self):
        self.call("drop", self.handle)

    def close(self):
        if self.opened:
            self.call("close", self.handle)
            self.opened = False


def read_then_drop(capture, prefix, operations):
    """Record call boundaries without log I/O or PCM reduction while active."""
    def operation(name, function):
        record = {"operation": name, "monotonic_start": time.monotonic()}
        try:
            return function()
        except Exception as exc:
            record["error"] = str(exc)
            raise
        finally:
            record["monotonic_end"] = time.monotonic()
            operations.append(record)
    try:
        data = operation(prefix + "-start-read", capture.read)
    finally:
        operation(prefix + "-drop", capture.drop)
    return validate.pcm_metrics(data)


def collect(out, repetitions):
    stages = []
    captures = []
    operations = []
    previous = validate.execute(["dmesg"])["stdout"]
    boot = Path("/proc/sys/kernel/random/boot_id").read_text()
    (out / "boot-id.before").write_text(boot)
    for status in Path("/proc/asound/card0").glob("pcm*/sub*/status"):
        if status.read_text().strip() != "closed":
            raise validate.Blocked(f"active PCM: {status}")

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n")

    # Each capture file starts at the ring head observed before that capture.
    trace_cursor = event_head() if EVENT_RECORDS.is_file() else 0

    def save_event_trace(name):
        nonlocal trace_cursor
        if EVENT_RECORDS.is_file():
            text, trace_cursor = read_event_pages(trace_cursor)
            (out / name).write_text(text)

    def phase(name, operation):
        nonlocal previous
        started = time.clock_gettime(time.CLOCK_BOOTTIME)
        monotonic_start = time.monotonic()
        error = None
        result = None
        try:
            result = operation()
        except Exception as exc:
            error = exc
        monotonic_end = time.monotonic()
        # A deferred IRQ can be observed after its initiating operation; phase
        # attribution describes observation, not a proven causal call site.
        time.sleep(0.1)
        after = validate.execute(["dmesg"])["stdout"]
        (out / f"{name}-kernel.before").write_text(previous)
        (out / f"{name}-kernel.after").write_text(after)
        record = {"phase": name, "boottime_start": started,
                  "boottime_end": time.clock_gettime(time.CLOCK_BOOTTIME),
                  "monotonic_start": monotonic_start, "monotonic_operation_end": monotonic_end,
                  "operation_error": str(error) if error else None}
        try:
            if not previous.strip() or not after.strip():
                raise validate.Blocked("empty kernel capture")
            delta, rotated = validate.kernel_delta(previous, after)
            (out / f"{name}-kernel.delta").write_text(delta)
            record.update(kernel_faults=validate.FAULTS.findall(delta), rotated=rotated)
        except validate.Blocked as exc:
            record["log_error"] = str(exc)
            error = error or exc
        previous = after
        stages.append(record)
        save("stages.json", stages)
        if error:
            raise error
        return result

    def interrupted(signum, unused):
        raise RuntimeError(f"collector interrupted: {signum}")

    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        with validate.UCM() as ucm:
            phase("hifi", lambda: ucm.set("_verb", "HiFi"))
            for repeat in range(1, repetitions + 1):
                prefix = f"mic-{repeat}"
                capture = Capture()
                phase(prefix + "-enable", lambda: ucm.set("_enadev", "Mic"))
                try:
                    phase(prefix + "-open", capture.open)
                    configuration = phase(prefix + "-hw-params", capture.params)
                    save(prefix + "-params.json", configuration)
                    phase(prefix + "-prepare", capture.prepare)
                    def active_interval():
                        try:
                            return read_then_drop(capture, prefix, operations)
                        finally:
                            save("pcm-operations.json", operations)

                    # Keep the read/drop call boundaries without any dmesg I/O
                    # between them. Attribute IRQ observation within the retained
                    # interval using raw timestamps; deferred reports can cross
                    # a boundary and do not establish precise causation.
                    metrics = phase(prefix + "-active-interval", active_interval)
                    captures.append({"repeat": repeat, **metrics})
                    save("captures.json", captures)
                finally:
                    try:
                        phase(prefix + "-close", capture.close)
                    finally:
                        phase(prefix + "-disable", lambda: ucm.set("_disdev", "Mic"))
                save_event_trace(prefix + "-event-records.txt")
                # Do not repeat an observed kernel fault or ambiguous capture.
                if any(row.get("kernel_faults") or row.get("log_error") for row in stages):
                    break
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    after_boot = Path("/proc/sys/kernel/random/boot_id").read_text()
    (out / "boot-id.after").write_text(after_boot)
    passed = (boot == after_boot and len(captures) == repetitions
              and not any(row.get("kernel_faults") or row.get("log_error") for row in stages))
    save("decision.json", {"status": "PASS" if passed else "FAIL", "media_saved": False,
                          "scope": "PCM delivery and observed lifecycle phase; not acoustic acceptance or precise IRQ causation",
                          "captures_completed": len(captures), "requested": repetitions,
                          "boot_unchanged": boot == after_boot})
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=1, choices=range(1, 4))
    args = parser.parse_args()
    if os.geteuid() != 0 or b"samsung,gts3llte\0" not in Path("/proc/device-tree/compatible").read_bytes():
        parser.error("requires root on the SM-T825 inside a bounded restoration unit")
    # The host wrapper creates the private report and arms mixer restoration.
    # Refuse standalone use without that snapshot.
    if not (args.output / "mixer-before.state").is_file() or not (args.output / "restoration-armed").is_file():
        parser.error("use the host wrapper with independent restoration armed")
    try:
        return collect(args.output, args.repetitions)
    except Exception as exc:
        (args.output / "collector-error.txt").write_text(str(exc) + "\n")
        (args.output / "decision.json").write_text(json.dumps({
            "status": "BLOCKED" if isinstance(exc, validate.Blocked) else "FAIL",
            "reason": str(exc), "media_saved": False,
        }, indent=2) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
