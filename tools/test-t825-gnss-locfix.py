#!/usr/bin/env python3
"""Host tests for the QMI LOC fix client encoding, redaction and fix tracking."""
import importlib.util
import struct
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('locfix', Path(__file__).with_name('t825-gnss-locfix.py'))
locfix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locfix)


class LocFixTest(unittest.TestCase):
    def test_round_trip(self):
        body = locfix.tlv(0x01, struct.pack('<I', 0)) + locfix.tlv(0x10, struct.pack('<d', -23.5)) + \
            locfix.tlv(0x11, struct.pack('<d', -46.6)) + locfix.tlv(0x12, struct.pack('<f', 12.0))
        message = locfix.encode(4, 7, locfix.IND_POSITION, body)
        msg_type, txn, msg_id, tlvs = locfix.decode(message)
        self.assertEqual((msg_type, txn, msg_id), (4, 7, 0x24))
        self.assertEqual(locfix.position(tlvs), (0, -23.5, -46.6, 12.0))

    def test_header_layout(self):
        self.assertEqual(locfix.encode(0, 1, 0x22, b'\x01\x01\x00\x01'),
                         bytes([0, 1, 0, 0x22, 0, 4, 0, 1, 1, 0, 1]))

    def test_mask_position_sentences(self):
        gga = '$GPGGA,123519,2330.123,S,04636.456,W,1,08,0.9,545.4,M,46.9,M,,*47'
        masked = locfix.mask_nmea(gga)
        self.assertNotIn('2330.123', masked)
        self.assertNotIn('04636.456', masked)
        self.assertIn(',1,08,', masked)
        gsv = '$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75'
        self.assertEqual(locfix.mask_nmea(gsv), gsv.split('*')[0])

    def test_nmea_text_strips_padding(self):
        self.assertEqual(locfix.nmea_text(b'\x10$GPGSV,1,1,00*79\r\n\0'), '$GPGSV,1,1,00*79')

    def test_tracker(self):
        tracker = locfix.Tracker(sustain=20, max_gap=5)
        tracker.gsv('$GPGSV,2,1,08,01,40,083,46,02,17,308,,12,07,344,39,14,22,228,45*75')
        tracker.gsv('$GPGSV,2,2,08,15,40,083,30*75')
        self.assertEqual(tracker.sv_view, {'GP': 8})
        self.assertEqual(tracker.sv_snr['GP'], [46, 39, 45, 30])
        for when in (0, 4, 8):
            tracker.fix(when)
        tracker.fix(20)  # gap > 5 s restarts the window
        self.assertFalse(tracker.sustained())
        for when in range(24, 44, 4):
            tracker.fix(when)
        self.assertTrue(tracker.sustained())
        self.assertEqual(tracker.first_fix, 0)


if __name__ == '__main__':
    unittest.main()
