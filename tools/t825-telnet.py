#!/usr/bin/env python3
"""Run stdin in a diagnostic shell without closing TCP before output arrives."""
from __future__ import annotations

import argparse
import base64
import secrets
import socket
import sys
import time


class TelnetStream:
    """Minimal stateful IAC decoder; refuse unsupported option negotiation."""

    def __init__(self) -> None:
        self.state = "data"
        self.command = 0

    def decode(self, chunk: bytes) -> tuple[bytes, bytes]:
        data, replies = bytearray(), bytearray()
        for char in chunk:
            if self.state == "data":
                if char == 255:
                    self.state = "iac"
                else:
                    data.append(char)
            elif self.state == "iac":
                if char == 255:
                    data.append(char)
                    self.state = "data"
                elif char in (251, 252, 253, 254):
                    self.command = char
                    self.state = "option"
                elif char == 250:
                    self.state = "subnegotiation"
                else:
                    self.state = "data"
            elif self.state == "option":
                if self.command == 251:
                    replies.extend((255, 254, char))  # WILL -> DONT
                elif self.command == 253:
                    replies.extend((255, 252, char))  # DO -> WONT
                self.state = "data"
            elif self.state == "subnegotiation":
                if char == 255:
                    self.state = "subnegotiation_iac"
            elif self.state == "subnegotiation_iac":
                self.state = "data" if char == 240 else "subnegotiation"
        return bytes(data), bytes(replies)


def run(host: str, port: int, script: bytes, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    token = secrets.token_hex(8)
    marker = f"T825_DONE_{token}:".encode()
    encoded = base64.b64encode(script).decode()
    # The completion marker must not occur verbatim in the echoed command.
    command = (
        f"printf '%s' '{encoded}' | base64 -d | sh; "
        f"printf '\\n%s%s:%s\\n' 'T825_DONE_' '{token}' \"$?\"\r\n"
    ).encode()
    stream = TelnetStream()
    received = bytearray()
    sent = False
    with socket.create_connection((host, port), timeout=min(timeout, 3)) as sock:
        while time.monotonic() < deadline:
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            chunk = sock.recv(65536)
            if not chunk:
                raise RuntimeError("shell disconnected before completion marker")
            data, replies = stream.decode(chunk)
            if replies:
                sock.sendall(replies)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            received.extend(data)
            if not sent and (b"# " in received or b"$ " in received):
                sock.sendall(command)
                sent = True
            normalized = bytes(received).replace(b"\r", b"")
            for line in normalized.split(b"\n")[:-1]:
                if line.startswith(marker):
                    status = line[len(marker):]
                    if status.isdigit():
                        return min(int(status), 255)
    raise TimeoutError("diagnostic command exceeded its absolute deadline")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="172.16.42.1")
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    try:
        return run(args.host, args.port, sys.stdin.buffer.read(), args.timeout)
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"telnet collection failed: {exc}", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
