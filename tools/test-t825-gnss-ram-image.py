#!/usr/bin/env python3
"""Validate the private T825 MSS/GNSS RAM image without booting hardware."""
from __future__ import annotations

import gzip
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/roadmap-7.3/gnss-ram-20261108"
DEFAULT_BUNDLE = ARTIFACT / "v63-mss-loc-retry-ro"
IMAGE = pathlib.Path(
    os.environ.get(
        "T825_RAM_IMAGE",
        str(DEFAULT_BUNDLE / "t825-v63.img"),
    )
)
BUNDLE = pathlib.Path(os.environ.get("T825_RAM_BUNDLE", str(DEFAULT_BUNDLE)))
INITRAMFS = BUNDLE / "initramfs"
KERNEL = BUNDLE / "vmlinuz"
BOOT_MEM = 52_428_800
PAGE = 4096
TAGS = 2_097_152
KERNEL_OFFSET = 0x8000


def fail(message: str) -> None:
    raise AssertionError(message)


def cpio_names() -> set[str]:
    proc = subprocess.run(
        ["unzstd", "-c", str(INITRAMFS)],
        check=True,
        stdout=subprocess.PIPE,
    )
    listing = subprocess.run(
        ["cpio", "-it", "--quiet"],
        input=proc.stdout,
        check=True,
        stdout=subprocess.PIPE,
    )
    return set(listing.stdout.decode().splitlines())


def main() -> int:
    for path in (IMAGE, INITRAMFS, KERNEL):
        if not path.is_file():
            fail(f"missing artifact: {path}")

    image = IMAGE.read_bytes()
    image[:8] == b"ANDROID!" or fail("not an Android boot image")
    fields = struct.unpack_from("<10I", image, 8)
    kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr, tags_addr, page_size, _, _ = fields
    kernel_addr == 0x80008000 or fail(f"kernel address {kernel_addr:#x}")
    ramdisk_addr == 0x82200000 or fail(f"ramdisk address {ramdisk_addr:#x}")
    second_size == 0 or fail("unexpected Android second payload")
    second_addr == 0x80F00000 or fail(f"second address {second_addr:#x}")
    tags_addr == 0x82000000 or fail(f"tags address {tags_addr:#x}")
    page_size == PAGE or fail(f"page size {page_size}")
    ramdisk_size == INITRAMFS.stat().st_size or fail("header/initramfs size mismatch")

    ramdisk_offset = ((page_size + kernel_size + PAGE - 1) // PAGE) * PAGE
    image[ramdisk_offset:ramdisk_offset + ramdisk_size] == INITRAMFS.read_bytes() or fail("image/archive contents differ")
    recovery_only = (BUNDLE / "RECOVERY_ONLY").is_file()
    if recovery_only:
        dtb = BUNDLE / "dtbs/msm8996-samsung-gts3llte.dtb"
        state = subprocess.run(["fdtget", "-t", "s", str(dtb), "/soc/remoteproc@2080000", "status"], check=True, capture_output=True, text=True).stdout.strip()
        state == "disabled" or fail("recovery-only image enables MSS")
        dtb.read_bytes() in image[page_size:page_size + kernel_size] or fail("disabled MSS DTB is not embedded")

    cmdline = image[64 : 64 + 512].split(b"\0", 1)[0].decode()
    "t825.mssdiag.hold" in cmdline or fail("independent recovery is not enabled in the image")
    transient_units = (
        "t825-extlinux-restore.service",
        "gts3-firmware.service",
        "rmtfs.service",
        "tqftpserv.service",
        "tqftpserv-populate-readwrite.service",
        "rmtfs-dir.service",
    )
    if "t825.direct-init" not in cmdline:
        for unit in transient_units:
            f"systemd.mask={unit}" in cmdline or fail(f"missing transient mask: {unit}")
    if "systemd.wants=t825-usb-gadget.service" not in cmdline and "t825.mssdiag.keep-usb" not in cmdline:
        "systemd.mask=t825-usb-gadget.service" in cmdline or fail(
            "missing transient USB gadget mask or explicit systemd.wants override"
        )

    kernel_raw = gzip.decompress(KERNEL.read_bytes())
    kernel_payload = image[page_size : page_size + kernel_size]
    kernel_payload.startswith(KERNEL.read_bytes()) or fail("kernel payload prefix mismatch")
    len(kernel_payload) == kernel_size or fail("header/kernel payload size mismatch")
    available = (BOOT_MEM - ramdisk_size) // PAGE * PAGE
    budget = available - TAGS - KERNEL_OFFSET
    len(kernel_raw) > 0 or fail("empty decompressed kernel")
    len(kernel_raw) <= budget or fail(
        f"kernel exceeds lk2nd budget: {len(kernel_raw)} > {budget}"
    )

    names = cpio_names()
    required = {
        "hooks-extra/90-t825-mssdiag-modem.sh",
        "hooks-extra/91-t825-mssdiag-start.sh",
        "hooks-extra/92-t825-mssdiag-services.sh",
        "hooks-cleanup/91-t825-mssdiag-firmware.sh",
        "usr/local/libexec/t825-recovery-supervisor",
        "usr/local/libexec/t825-recovery-arm",
        "hooks-cleanup/90-t825-recovery-runtime.sh",
        "usr/local/sbin/t825-usb-gadget",
        "usr/lib/systemd/system/t825-usb-gadget.service",
        "usr/bin/rmtfs",
        "usr/bin/tqftpserv",
        "usr/bin/qrtr-lookup",
        "usr/bin/qmicli",
        "usr/bin/busybox-extras",
        "usr/lib/libqmi-glib.so.5.12.0",
        "usr/lib/libqrtr.so.1.2",
    }
    missing = required - names
    not missing or fail(f"missing initramfs entries: {sorted(missing)}")
    if "t825.direct-init" in cmdline:
        "usr/local/libexec/t825-direct-init" in names or fail(
            "direct-init command line is missing the transient PID 1 script"
        )
        with tempfile.TemporaryDirectory(prefix="t825-direct-init-") as tmp:
            archive = subprocess.run(
                ["unzstd", "-c", str(INITRAMFS)],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            subprocess.run(
                ["cpio", "-id", "--quiet", "--no-absolute-filenames"],
                cwd=tmp,
                input=archive,
                check=True,
            )
            init2 = pathlib.Path(tmp) / "init_2nd.sh"
            init2_text = init2.read_text()
            'exec switch_root /sysroot "$init"' in init2_text or fail(
                'direct-init must replace PID 1 with switch_root'
            )
            "t825.direct-init" in init2_text or fail(
                "direct-init command line is not wired into init_2nd.sh"
            )
            re.search(
                r'\*" t825\.direct-init "\*\)\s*:\s*;;', init2_text
            ) or fail(
                "direct-init branch must continue into mount_root/switch_root"
            )
            not re.search(
                r'\*" t825\.direct-init "\*\)\s*exit\s+0\s*;;', init2_text
            ) or fail(
                "direct-init branch exits before mount_root/switch_root"
            )
            'mount -o remount,ro /sysroot || fail_halt_boot' in init2_text or fail(
                'direct-init does not enforce a read-only root before cleanup'
            )
            functions = (pathlib.Path(tmp) / 'init_functions.sh').read_text()
            root_mount = re.search(r'^mount_root_partition\(\) \{\n.*?^\}', functions,
                                   re.MULTILINE | re.DOTALL)
            root_mount is not None or fail('missing root mount function')
            body = root_mount[0]
            'busybox blockdev --setro "$t825_root_device" || fail_halt_boot' in body or fail(
                'direct-init does not protect its backing block device'
            )
            'blkid -c /dev/null -t UUID="$t825_root_uuid" -o device' in body or fail(
                'direct-init does not discover all root filesystem members'
            )
            't825_root_mountopts=ro,rescue=nologreplay' in body or fail(
                'direct-init permits Btrfs journal replay'
            )
            not re.search(r'mount .* -o rw', body) or fail(
                'direct-init still mounts the installed root writable'
            )
            not re.search(r'^\s*mount_boot_partition /sysroot/boot', init2_text,
                          re.MULTILINE) or fail('direct-init mounts the installed boot volume')
            direct = (pathlib.Path(tmp) / 'usr/local/libexec/t825-direct-init').read_text()
            'command -v sshd' in direct or fail('direct-init assumes Alpine sshd in the installed Arch root')
    forbidden = sorted(n for n in names if pathlib.PurePosixPath(n).name.startswith("modem.b"))
    not forbidden or fail(f"modem segments embedded in initramfs: {forbidden}")

    if "t825.mssdiag.hold" in cmdline:
        "pmos.debug-shell" in cmdline or fail(
            "hold image does not enable the initial postmarketOS debug shell"
        )
        # The hold image must make the inspection marker before any QRTR/QMI
        # probe, and every probe must be bounded so a missing modem cannot
        # strand the initramfs shell.
        with tempfile.TemporaryDirectory(prefix="t825-ram-image-") as tmp:
            archive = subprocess.run(
                ["unzstd", "-c", str(INITRAMFS)],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            subprocess.run(
                ["cpio", "-id", "--quiet", "--no-absolute-filenames"],
                cwd=tmp,
                input=archive,
                check=True,
            )
            hook = pathlib.Path(tmp) / "hooks-extra/92-t825-mssdiag-services.sh"
            prepare = pathlib.Path(tmp) / "hooks-extra/91-t825-mssdiag-start.sh"
            hook_text = hook.read_text()
            prepare_text = prepare.read_text()
            if not recovery_only:
                marker_at = hook_text.find("/run/t825-mssdiag/hold.log")
                probes_at = hook_text.find("/run/t825-mssdiag/qmi.log")
                marker_at >= 0 or fail("hold image does not create hold.log")
                probes_at > marker_at or fail("hold marker is written after QMI probes")
                hook_text.count("/usr/bin/busybox timeout 5") >= 3 or fail(
                    "hold image does not bound every QRTR/QMI probe"
                )
                "modemst1:modem_fs1" in prepare_text or fail(
                    "rmtfs calibration mapping is missing modemst1"
                )
                "continue-pivot" in hook_text or fail(
                    "hold image does not wait for the continuation marker"
                )
                "/tmp/continue_boot" in hook_text or fail(
                    "hold image does not accept pmos_continue_boot release"
                )
            tree = pathlib.Path(tmp)
            init2_text = (tree / 'init_2nd.sh').read_text()
            for call in ('delete_old_install_partition', 'resize_root_partition',
                         'resize_root_filesystem', 'resize_filesystem_after_mount /sysroot'):
                call not in init2_text.splitlines() or fail(
                    f'diagnostic image still executes installer mutation: {call}'
                )
            init = (tree / "init").read_text()
            arm_call = "/bin/busybox ash /usr/local/libexec/t825-recovery-arm || fail_halt_boot"
            functions = (tree / "init_functions.sh").read_text()
            mount_function = functions[functions.index("mount_proc_sys_dev() {"):functions.index("setup_firmware_path() {")]
            mount_function.index("mount -t tmpfs") < mount_function.index(arm_call) < mount_function.index("modprobe libcomposite") or fail(
                "recovery is not armed before USB module loading"
            )
            init.index("mount_proc_sys_dev\n") < init.index("jump_init_2nd") or fail("stage 2 precedes recovery")
            arm = (tree / "usr/local/libexec/t825-recovery-arm").read_text()
            "t825.mssdiag.hold" in arm or fail("recovery lacks transient cmdline gate")
            "setsid /usr/local/libexec/t825-recovery-supervisor 240" in arm or fail("missing independent recovery process")
            binary = tree / "usr/local/libexec/t825-recovery-supervisor"
            elf = subprocess.run(["readelf", "-hl", str(binary)], check=True, capture_output=True, text=True).stdout
            "AArch64" in elf and "INTERP" not in elf or fail("supervisor is not static AArch64")
            runtime = (tree / "hooks-cleanup/90-t825-recovery-runtime.sh").read_text()
            "> /run/systemd/system/t825-usb-gadget.service" in runtime or fail("USB unit is not carried through /run")
            "ExecStart=/bin/sh /run/t825-recovery/usb-gadget" in runtime or fail("USB unit references the discarded initramfs")
            "sysinit.target.wants" in runtime or fail("USB unit has no direct runtime wants link")
            cleanup = (tree / "hooks-cleanup/91-t825-mssdiag-firmware.sh").read_text()
            "mount --move /run /sysroot/run" in cleanup or fail("/run transfer is missing")
            "mount --bind /run /sysroot/run" in cleanup or fail("/run transfer has no bind fallback")
            "t825-mssdiag-postpivot-watchdog" not in "\n".join(names) or fail("obsolete shell watchdog still packaged")

    print(
        "RAM image validation passed: "
        f"kernel={len(kernel_raw)} kernel-payload={kernel_size} "
        f"initramfs={ramdisk_size} budget={budget}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
