#!/usr/bin/env python3
"""Parse QCA TLV NVM tags and compare the BDADDR tag with a board address."""
from __future__ import annotations
import argparse, hashlib, json, re, struct
from pathlib import Path

NVM_TYPE = 2
BDADDR_TAG = 2
NVM_HEADER = struct.Struct('<HHII')

def parse_bytes(data: bytes) -> dict:
    if len(data) < 4:
        raise ValueError('short TLV header')
    type_len, = struct.unpack_from('<I', data)
    tlv_type, length = type_len & 0xff, type_len >> 8
    if 4 + length != len(data):
        raise ValueError('outer TLV length does not match file')
    if tlv_type == 4:
        if len(data) < 8:
            raise ValueError('short enclosing header')
        # btqca.c advances one four-byte tlv_type_hdr, not a tag header.
        type_len, = struct.unpack_from('<I', data, 4)
        tlv_type, length = type_len & 0xff, type_len >> 8
        start = 8
    else:
        start = 4
    if tlv_type != NVM_TYPE:
        raise ValueError(f'unexpected TLV type {tlv_type}')
    if start + length > len(data):
        raise ValueError('NVM length exceeds file')
    tags, offset = [], start
    end = start + length
    while offset < end:
        if end - offset < NVM_HEADER.size:
            raise ValueError('incomplete NVM tag header')
        tag_id, tag_len, reserve1, reserve2 = NVM_HEADER.unpack_from(data, offset)
        payload = offset + NVM_HEADER.size
        if payload + tag_len > end:
            raise ValueError(f'tag {tag_id} exceeds NVM length')
        tags.append({
            'tag_id': tag_id, 'tag_len': tag_len,
            'offset': offset, 'data_offset': payload,
            'data_hex': data[payload:payload + tag_len].hex(),
            'reserve1': reserve1, 'reserve2': reserve2,
        })
        offset = payload + tag_len
    addresses = [t for t in tags if t['tag_id'] == BDADDR_TAG]
    if len(addresses) != 1 or addresses[0]['tag_len'] != 6:
        raise ValueError('expected exactly one six-byte BDADDR tag')
    bdaddr = addresses[0]
    return {
        'sha256': hashlib.sha256(data).hexdigest(),
        'size': len(data), 'tlv_type': tlv_type, 'declared_length': length,
        'data_start': start, 'tags': tags,
        'bdaddr_tag': bdaddr,
        'scope': 'first type-2 tag set only',
    }

def parse(path: Path) -> dict:
    return dict(parse_bytes(path.read_bytes()), path=str(path))

def analyze(stock: Path, candidate: Path, expected: str) -> dict:
    stock_data, candidate_data = stock.read_bytes(), candidate.read_bytes()
    s = dict(parse_bytes(stock_data), path=str(stock))
    c = dict(parse_bytes(candidate_data), path=str(candidate))
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', expected):
        raise ValueError('expected a six-byte colon-separated Bluetooth address')
    # QCA NVM stores the Bluetooth address in the little-endian byte order
    # consumed by the firmware; user-facing HCI addresses print the reverse.
    expected_hex = bytes.fromhex(expected.replace(':', ''))[::-1].hex()
    sb, cb = s['bdaddr_tag'], c['bdaddr_tag']
    start = sb['data_offset']
    end = start + sb['tag_len']
    changed_only_address = (
        sb['data_offset'] == cb['data_offset'] and
        len(stock_data) == len(candidate_data) and
        stock_data[:start] == candidate_data[:start] and
        stock_data[end:] == candidate_data[end:] and
        stock_data[start:end] != candidate_data[start:end])
    return {
        'stock': s, 'candidate': c, 'expected_board_address': expected,
        'expected_nvm_payload': expected_hex,
        'stock_bdaddr_payload': sb['data_hex'] if sb else None,
        'candidate_bdaddr_payload': cb['data_hex'] if cb else None,
        'candidate_address_matches_board': bool(cb and cb['data_hex'].lower() == expected_hex),
        'candidate_changed_only_bdaddr_payload': changed_only_address,
        'decision': 'diagnostic-only-address-hypothesis',
        'cause_proven': False,
        'production_fix_accepted': False,
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('stock', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('--address', required=True)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    out = json.dumps(analyze(a.stock, a.candidate, a.address), indent=2) + '\n'
    if a.output: a.output.write_text(out)
    else: print(out, end='')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
