#!/usr/bin/env python3
"""Exercise package opt-in isolation without building or contacting hardware."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1] / "pmaports/linux-postmarketos-qcom-msm8996"
RUN = r'''
set -eu
source "$T825_TEST_PACKAGE/APKBUILD"
default_prepare() { touch "$builddir/default_prepare.called"; }
msg() { printf '%s\n' "$*"; }
error() { printf '%s\n' "$*" >&2; }
cd "$builddir"
prepare
'''


class DiagnosticVariants(unittest.TestCase):
    def prepare(self, *, mss=False, audio=False, env_mss=False, env_audio=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        source = root / "src"
        source.mkdir()
        build = source / "linux-7.3.1"
        build.mkdir()
        (source / "config-postmarketos-qcom-msm8996.aarch64").write_text('CONFIG_LOCALVERSION="-t825"\n')
        for name in ("0203-arm64-dts-qcom-gts3llte-enable-mss-diagnostic.patch.disabled",
                     "0205-asoc-wcd9335-port-diagnostics.patch.disabled",
                     "0206-slimbus-stream-transaction-diagnostics.patch.disabled",
                     "0207-slimbus-ngd-channel-removal-experiment.patch.disabled",
                     "0208-slimbus-audio-event-trace.patch.disabled"):
            (source / name).write_text("selected_patch=" + name + "\n")
        start = root / "package"
        start.mkdir()
        if mss:
            (start / ".t825-enable-mss").touch()
        if audio:
            (start / ".t825-enable-audio-diag").touch()
        bins = root / "bin"
        bins.mkdir()
        fake = bins / "patch"
        fake.write_text('#!/bin/sh\ncat >> "$T825_TEST_PATCH_LOG"\n')
        fake.chmod(0o755)
        env = os.environ.copy()
        env.update(T825_TEST_PACKAGE=str(PACKAGE), T825_TEST_PATCH_LOG=str(root / "patch.log"),
                   T825_MSS_DIAGNOSTIC=str(int(env_mss)), T825_AUDIO_DIAGNOSTIC=str(int(env_audio)),
                   srcdir=str(source), startdir=str(start), CARCH="aarch64",
                   PATH=str(bins) + os.pathsep + env["PATH"])
        result = subprocess.run(["bash", "-c", RUN], env=env, capture_output=True, text=True, timeout=5)
        return result, build, (root / "patch.log").read_text() if (root / "patch.log").exists() else ""

    def test_production_preparation_does_not_apply_diagnostics(self):
        result, build, patches = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((build / ".config").read_text(), 'CONFIG_LOCALVERSION="-t825"\n')
        self.assertFalse(patches)

    def test_audio_opt_in_gets_distinct_module_release(self):
        for options in ({"audio": True}, {"env_audio": True}):
            result, build, patches = self.prepare(**options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((build / ".config").read_text(), 'CONFIG_LOCALVERSION="-t825-audiodiag"\n')
            self.assertIn("0205-", patches)
            self.assertIn("0206-", patches)
            self.assertIn("0207-", patches)
            self.assertIn("0208-", patches)
            self.assertNotIn("0203-", patches)

    def test_mss_opt_in_retains_its_separate_release(self):
        for options in ({"mss": True}, {"env_mss": True}):
            result, build, patches = self.prepare(**options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((build / ".config").read_text(), 'CONFIG_LOCALVERSION="-t825-mssdiag"\n')
            self.assertIn("0203-", patches)
            self.assertNotIn("0205-", patches)
            self.assertNotIn("0206-", patches)
            self.assertNotIn("0207-", patches)
            self.assertNotIn("0208-", patches)

    def test_mixed_diagnostics_fail_before_any_source_or_config_preparation(self):
        for options in ({"audio": True, "mss": True}, {"env_audio": True, "env_mss": True},
                        {"audio": True, "env_mss": True}, {"env_audio": True, "mss": True}):
            result, build, patches = self.prepare(**options)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be separate", result.stderr)
            self.assertFalse((build / "default_prepare.called").exists())
            self.assertFalse((build / ".config").exists())
            self.assertFalse(patches)

    def test_diagnostic_patch_is_disabled_and_checksum_bound(self):
        content = (PACKAGE / "APKBUILD").read_text()
        for filename in ("0203-arm64-dts-qcom-gts3llte-enable-mss-diagnostic.patch.disabled",
                         "0205-asoc-wcd9335-port-diagnostics.patch.disabled",
                     "0206-slimbus-stream-transaction-diagnostics.patch.disabled",
                     "0207-slimbus-ngd-channel-removal-experiment.patch.disabled",
                     "0208-slimbus-audio-event-trace.patch.disabled"):
            hashes = re.findall(r"^([a-f0-9]{128})  " + re.escape(filename) + r"$", content, re.MULTILINE)
            self.assertEqual(hashes, [hashlib.sha512((PACKAGE / filename).read_bytes()).hexdigest()])
            self.assertFalse((PACKAGE / filename.removesuffix(".disabled")).exists())


if __name__ == "__main__":
    unittest.main()
