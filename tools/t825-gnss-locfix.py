#!/usr/bin/env python3
"""Bounded QMI LOC fix session over QRTR for the MSS diagnostic RAM boot.

qmicli releases its QRTR client on exit, which also ends a LOC session, so a
started session cannot be followed from a second qmicli process. This client
keeps one socket for the whole session: register events, start a periodic
session, log position/NMEA/engine indications, stop and exit within --seconds.
It never sets the operation mode, engine lock, NV items or assistance data.
Coordinates are rounded to two decimals and NMEA position fields are masked.
"""
import argparse
import json
import socket
import struct
import sys
import time

AF_QIPCRTR = getattr(socket, 'AF_QIPCRTR', 42)
QRTR_PORT_CTRL = 0xfffffffe
QRTR_TYPE_NEW_SERVER, QRTR_TYPE_NEW_LOOKUP = 4, 10
LOC_SERVICE = 16
MSG_REGISTER_EVENTS, MSG_START, MSG_STOP = 0x0021, 0x0022, 0x0023
IND_POSITION, IND_SV, IND_NMEA, IND_ENGINE, IND_FIX_STATE = 0x24, 0x25, 0x26, 0x27, 0x28
# Position report, GNSS SV info, NMEA, inject-time request, engine state, fix session state.
EVENT_MASK = 0x1 | 0x2 | 0x4 | 0x10 | 0x80 | 0x100
SESSION_ID = 1
POSITION_SENTENCES = {'GGA': (2, 4), 'RMC': (3, 5), 'GLL': (1, 3), 'GNS': (2, 4)}


def tlv(kind, value):
    return struct.pack('<BH', kind, len(value)) + value


def encode(msg_type, txn, msg_id, tlvs=b''):
    return struct.pack('<BHHH', msg_type, txn, msg_id, len(tlvs)) + tlvs


def decode(data):
    if len(data) < 7:
        raise ValueError('short QMI message')
    msg_type, txn, msg_id, length = struct.unpack_from('<BHHH', data)
    body, tlvs, offset = data[7:7 + length], {}, 0
    while offset + 3 <= len(body):
        kind, size = struct.unpack_from('<BH', body, offset)
        tlvs[kind] = body[offset + 3:offset + 3 + size]
        offset += 3 + size
    return msg_type, txn, msg_id, tlvs


def mask_nmea(sentence):
    """Hide coordinates in position sentences; keep satellite sentences intact."""
    fields = sentence.split(',')
    kind = fields[0][-3:] if fields and fields[0].startswith('$') else ''
    for index in POSITION_SENTENCES.get(kind, ()):
        if index < len(fields) and fields[index]:
            fields[index] = fields[index][:2] + 'xx'
    return ','.join(fields).split('*')[0]


def nmea_text(raw):
    text = raw.rstrip(b'\0').decode('ascii', 'replace')
    start = text.find('$')
    return text[start:].strip() if start >= 0 else ''


class Tracker:
    """Sustained fix: successful reports with no gap longer than max_gap."""

    def __init__(self, sustain, max_gap=10.0):
        self.sustain, self.max_gap = sustain, max_gap
        self.first_fix = self.window = self.last = None
        self.fixes = 0
        self.sv_view = {}
        self.sv_snr = {}

    def fix(self, when):
        self.fixes += 1
        if self.first_fix is None:
            self.first_fix = when
        if self.last is None or when - self.last > self.max_gap:
            self.window = when
        self.last = when

    def sustained(self):
        return self.window is not None and self.last - self.window >= self.sustain

    def gsv(self, sentence):
        fields = sentence.split('*')[0].split(',')
        if len(fields) < 4 or not fields[0].endswith('GSV'):
            return
        talker = fields[0][1:3]
        if fields[3].isdigit():
            self.sv_view[talker] = int(fields[3])
        if fields[2] == '1':
            self.sv_snr[talker] = []
        for index in range(7, len(fields), 4):
            if fields[index].isdigit():
                self.sv_snr.setdefault(talker, []).append(int(fields[index]))


def position(tlvs):
    status = struct.unpack('<I', tlvs[0x01])[0] if len(tlvs.get(0x01, b'')) == 4 else None
    lat = struct.unpack('<d', tlvs[0x10])[0] if len(tlvs.get(0x10, b'')) == 8 else None
    lon = struct.unpack('<d', tlvs[0x11])[0] if len(tlvs.get(0x11, b'')) == 8 else None
    hunc = struct.unpack('<f', tlvs[0x12])[0] if len(tlvs.get(0x12, b'')) == 4 else None
    return status, lat, lon, hunc


class Client:
    def __init__(self, log):
        self.log, self.txn = log, 0
        self.sock = socket.socket(AF_QIPCRTR, socket.SOCK_DGRAM)
        self.node = self.sock.getsockname()[0]
        self.service = None
        self.pending = []

    def lookup(self, timeout=10):
        self.sock.sendto(struct.pack('<5I', QRTR_TYPE_NEW_LOOKUP, LOC_SERVICE, 0, 0, 0),
                         (self.node, QRTR_PORT_CTRL))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.sock.settimeout(max(0.1, end - time.monotonic()))
            data, _ = self.sock.recvfrom(65536)
            if len(data) < 20:
                continue
            cmd, service, instance, node, port = struct.unpack_from('<5I', data)
            if cmd != QRTR_TYPE_NEW_SERVER:
                continue
            if service == 0 and node == 0 and port == 0:
                break
            if service == LOC_SERVICE and self.service is None:
                self.service = (node, port)
                self.log(f'LOOKUP service=16 instance={instance:#x} node={node} port={port}')
        if self.service is None:
            raise RuntimeError('LOC service not found on the QRTR bus')

    def request(self, msg_id, tlvs=b'', timeout=10):
        self.txn = self.txn % 0xffff + 1
        self.sock.sendto(encode(0, self.txn, msg_id, tlvs), self.service)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.sock.settimeout(max(0.1, end - time.monotonic()))
            data, source = self.sock.recvfrom(65536)
            if source != self.service:
                continue
            message = decode(data)
            if message[0] == 2 and message[1] == self.txn and message[2] == msg_id:
                result = message[3].get(0x02, b'')
                code, error = struct.unpack('<HH', result) if len(result) == 4 else (None, None)
                self.log(f'RESPONSE msg={msg_id:#06x} result={code} error={error}')
                if code != 0:
                    raise RuntimeError(f'request {msg_id:#06x} failed: error {error}')
                return message[3]
            self.pending.append(message)
        raise TimeoutError(f'no response to {msg_id:#06x}')

    def indication(self, timeout):
        if self.pending:
            return self.pending.pop(0)
        self.sock.settimeout(timeout)
        try:
            data, source = self.sock.recvfrom(65536)
        except socket.timeout:
            return None
        if source != self.service:
            return None
        message = decode(data)
        return message if message[0] == 4 else None


def run(args, log):
    tracker, client, reason = Tracker(args.sustain), Client(log), 'budget'
    begin = time.monotonic()
    deadline = begin + args.seconds
    client.lookup()
    client.request(MSG_REGISTER_EVENTS, tlv(0x01, struct.pack('<Q', EVENT_MASK)))
    client.request(MSG_START, tlv(0x01, bytes([SESSION_ID])) + tlv(0x10, struct.pack('<I', 1)) +
                   tlv(0x12, struct.pack('<I', 1)) + tlv(0x13, struct.pack('<I', 1000)))
    log('STARTED session=1 periodic intermediate=on interval_ms=1000')
    next_stat = begin
    try:
        while time.monotonic() < deadline:
            message = client.indication(1.0)
            now = time.monotonic() - begin
            if message:
                msg_id, tlvs = message[2], message[3]
                if msg_id == IND_POSITION:
                    status, lat, lon, hunc = position(tlvs)
                    if status == 0 and lat is not None and lon is not None:
                        tracker.fix(now)
                    shown = f'lat={lat:.2f} lon={lon:.2f}' if lat is not None and lon is not None else 'lat=- lon=-'
                    hunc_text = f'{hunc:.0f}' if hunc is not None else '-'
                    log(f'POSITION t={now:.1f} status={status} {shown} hunc_m={hunc_text} tlvs={sorted(tlvs)}')
                elif msg_id == IND_NMEA:
                    sentence = nmea_text(tlvs.get(0x01, b''))
                    tracker.gsv(sentence)
                    log(f'NMEA t={now:.1f} {mask_nmea(sentence)}')
                elif msg_id == IND_ENGINE:
                    state = tlvs.get(0x01, b'')
                    log(f'ENGINE t={now:.1f} state={struct.unpack("<I", state)[0] if len(state) == 4 else state.hex()}')
                else:
                    log(f'IND t={now:.1f} msg={msg_id:#06x} tlvs={ {k: len(v) for k, v in tlvs.items()} }')
            if time.monotonic() >= next_stat:
                snr = [value for values in tracker.sv_snr.values() for value in values]
                log(f'STAT t={now:.1f} sv_in_view={tracker.sv_view} sv_with_snr={sum(v > 0 for v in snr)} '
                    f'max_snr={max(snr, default=0)} fixes={tracker.fixes} first_fix={tracker.first_fix}')
                next_stat += 10
            if tracker.sustained():
                reason = 'sustained_fix'
                break
    finally:
        try:
            client.request(MSG_STOP, tlv(0x01, bytes([SESSION_ID])))
        except Exception as exc:  # The session ends with the socket anyway.
            log(f'STOP failed: {exc}')
    snr = [value for values in tracker.sv_snr.values() for value in values]
    return {'reason': reason, 'fixes': tracker.fixes, 'first_fix_s': tracker.first_fix,
            'sustained_s': (tracker.last - tracker.window) if tracker.window is not None else 0,
            'sv_in_view': tracker.sv_view, 'sv_with_snr': sum(v > 0 for v in snr),
            'max_snr': max(snr, default=0), 'elapsed_s': round(time.monotonic() - begin, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--sustain', type=int, default=120)
    parser.add_argument('--log', required=True)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 1800 or not 10 <= args.sustain <= args.seconds:
        parser.error('bounded session required: 30 <= seconds <= 1800, 10 <= sustain <= seconds')
    with open(args.log, 'a', buffering=1) as handle:
        def log(line):
            handle.write(f'{time.strftime("%H:%M:%S")} {line}\n')
        try:
            result = run(args, log)
            log('RESULT ' + json.dumps(result, sort_keys=True))
            status = 0
        except Exception as exc:
            log(f'ERROR {type(exc).__name__}: {exc}')
            status = 1
        log('DONE')
    return status


if __name__ == '__main__':
    sys.exit(main())
