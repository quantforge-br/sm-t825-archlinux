#!/usr/bin/env python3
"""Offline QCA NVM format and mutation-boundary regressions."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('nvm', Path(__file__).with_name('analyze-t825-qca-nvm.py'))
nvm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nvm)


def tag(number, data):
    return struct.pack('<HHII', number, len(data), 0, 0) + data


def tlv(kind, payload):
    return struct.pack('<I', kind | (len(payload) << 8)) + payload


class QcaNvm(unittest.TestCase):
    def compare(self, stock, candidate, address='12:34:56:78:9A:BC'):
        with tempfile.TemporaryDirectory() as tmp:
            s, c = Path(tmp) / 'stock', Path(tmp) / 'candidate'
            s.write_bytes(stock)
            c.write_bytes(candidate)
            return nvm.analyze(s, c, address)

    def pair(self, prefix=b'', wrapped=False):
        stock = tlv(2, prefix + tag(2, bytes.fromhex('ad5a00000000')) + tag(17, b'\x82\x01\x0e'))
        candidate = tlv(2, prefix + tag(2, bytes.fromhex('bc9a78563412')) + tag(17, b'\x82\x01\x0e'))
        return (tlv(4, stock), tlv(4, candidate)) if wrapped else (stock, candidate)

    def test_address_byte_order_and_changed_only_field(self):
        result = self.compare(*self.pair())
        self.assertEqual(result['candidate']['bdaddr_tag']['data_offset'], 16)
        self.assertEqual(result['expected_nvm_payload'], 'bc9a78563412')
        self.assertTrue(result['candidate_address_matches_board'])
        self.assertTrue(result['candidate_changed_only_bdaddr_payload'])
        self.assertFalse(result['cause_proven'])
        self.assertFalse(result['production_fix_accepted'])

    def test_wrapped_and_displaced_tag_use_parsed_offset(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                result = self.compare(*self.pair(tag(6, b'other'), wrapped))
                self.assertEqual(result['candidate']['bdaddr_tag']['data_offset'], 33 + 4 * wrapped)
                self.assertTrue(result['candidate_changed_only_bdaddr_payload'])
                self.assertTrue(result['candidate_address_matches_board'])

    def test_extra_mutation_identical_file_and_wrong_endian_do_not_pass(self):
        stock, candidate = self.pair()
        changed = candidate[:-1] + bytes([candidate[-1] ^ 1])
        self.assertFalse(self.compare(stock, changed)['candidate_changed_only_bdaddr_payload'])
        self.assertFalse(self.compare(stock, stock)['candidate_changed_only_bdaddr_payload'])
        wrong = tlv(2, tag(2, bytes.fromhex('123456789abc')))
        self.assertFalse(self.compare(stock, wrong)['candidate_address_matches_board'])

    def test_malformed_and_ambiguous_inputs_fail(self):
        good, _ = self.pair()
        invalid = [b'', good[:-1], good + b'\x00', tlv(3, b''), tlv(4, b'x'),
                   tlv(2, b'x'), tlv(2, tag(2, b'12345')),
                   tlv(2, tag(6, b'x')), tlv(2, tag(2, b'123456') * 2),
                   tlv(2, struct.pack('<HHII', 2, 20, 0, 0) + b'x')]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                nvm.parse_bytes(data)
        for address in ('1234', '12:34:56:78:9A:ZZ'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.compare(*self.pair(), address=address)

if __name__ == '__main__': unittest.main()
