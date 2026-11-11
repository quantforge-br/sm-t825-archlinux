#!/usr/bin/env python3
"""Host-only tests for the upstream series classifier."""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("series", HERE / "t825-upstream-series.py")
series = importlib.util.module_from_spec(spec)
spec.loader.exec_module(series)


def patch(files, author="Dev <dev@kernel.org>", trailers="Signed-off-by: Dev <dev@kernel.org>"):
    diffs = "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n" for f in files)
    return (f"From: {author}\nSubject: [PATCH] subsystem: change\n which wraps\n\n"
            f"Body.\n\n{trailers}\n---\n{diffs}")


class Classify(unittest.TestCase):
    def test_classes(self):
        board = "arch/arm64/boot/dts/qcom/msm8996-samsung-gts3l-common.dtsi"
        self.assertEqual(series.classify("0001-a.patch", patch([board]))[0], "t825-specific")
        self.assertEqual(series.classify("0002-a.patch", patch([board, "drivers/x.c"]))[0], "mixed")
        self.assertEqual(series.classify("0010-a.patch", patch(["sound/soc/qcom/apq8096.c"]))[0], "generic")
        self.assertEqual(series.classify("0204-a.patch", patch(["drivers/x.c"]))[0], "excluded")
        self.assertEqual(series.classify("m001-a.patch", patch(["drivers/x.c"]))[0], "excluded")
        self.assertEqual(series.classify("0208-a.patch.disabled", patch(["drivers/x.c"]))[0], "excluded")

    def test_subject_and_topic(self):
        self.assertEqual(series.subject(patch(["x"])), "subsystem: change which wraps")
        self.assertEqual(series.topic(["Documentation/devicetree/bindings/sound/x.yaml"]), "asoc")
        self.assertEqual(series.topic(["drivers/gpu/drm/msm/dsi/x.c"]), "drm-msm")

    def test_blockers(self):
        self.assertEqual(series.blockers(patch(["x"])), [])
        found = series.blockers(patch(["x"], author="P <p@example.com>",
                                      trailers="Signed-off-by: P <p@example.com>\n"
                                               "Co-Authored-By: Bot <noreply@example.org>"))
        self.assertEqual(len(found), 3)


if __name__ == "__main__":
    unittest.main()
