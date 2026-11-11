#!/usr/bin/env python3
"""Host-only tests for the PM8994 PON snapshot decoder."""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pon", HERE / "analyze-t825-pon.py")
pon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pon)

VALUES = {0x801: 0x04, 0x803: 0x01, 0x804: 0x01, 0x805: 0x01, 0x808: 0x41,
          0x80C: 0x02, 0x854: 0x0F, 0x855: 0x03, 0x856: 0x08}


def snapshot(values=None, extra=""):
    regs = {**VALUES, **(values or {})}
    lines = ["boot_id=a653fa6f-fa9b-4c1d-8a75-d2af4138f407", "kernel=7.3.1-t825"]
    lines += [f"{r:04x}: {regs.get(r, 0):02x}" for r in pon.REQUIRED]
    return "\n".join(lines) + "\n" + extra


class PonDecode(unittest.TestCase):
    def test_live_snapshot(self):
        r = pon.decode(snapshot())
        self.assertEqual(r["pon_generation"], "gen1")
        self.assertEqual(r["poff_reason1_bits"], ["PS_HOLD"])
        self.assertEqual(r["pon_reason1_bits"], ["HARD_RESET", "CBL"])
        self.assertFalse(r["wd_enabled"])
        self.assertFalse(r["last_poff_pmic_watchdog"])
        self.assertEqual((r["wd_s1_timer"], r["wd_s2_timer"]), (15, 3))

    def test_watchdog_attribution(self):
        r = pon.decode(snapshot({0x80C: 0x04, 0x857: 0x80}))
        self.assertTrue(r["last_poff_pmic_watchdog"])
        self.assertFalse(r["last_poff_ps_hold"])
        self.assertTrue(r["wd_enabled"])

    def test_rejects_incomplete_or_unreadable(self):
        text = snapshot()
        with self.assertRaises(ValueError):
            pon.decode(text.replace("0858: 00\n", ""))
        with self.assertRaises(ValueError):
            pon.decode(text.replace("0857: 00", "0857: XX"))
        with self.assertRaises(ValueError):
            pon.decode(snapshot(extra="0859: 00\n"))
        with self.assertRaises(ValueError):
            pon.decode(snapshot({0x804: 0x02}))
        with self.assertRaises(ValueError):
            pon.decode(text.replace("boot_id=", "boot="))


if __name__ == "__main__":
    unittest.main()
