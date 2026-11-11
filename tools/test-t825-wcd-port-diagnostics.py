#!/usr/bin/env python3
"""Run the actual patched port-reader helpers against host register stubs.

Requires --kernel-source pointing to a private Linux tree with patch 0205
applied. This proves opt-in/budget/read-error invariants, not hardware safety
or the cause of the T825 codec fault.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
typedef int atomic_t;
static bool port_diagnostics;
static atomic_t port_diag_budget = 128;
static bool atomic_add_unless(atomic_t *value, int amount, int unless) {
    if (*value == unless) return false;
    *value += amount;
    return true;
}
struct wcd9335_codec { void *if_regmap; void *dev; };
struct wcd9335_slim_ch { unsigned int port; struct wcd9335_slim_ch *next; };
struct wcd_slim_codec_dai_data {
    struct { int direction; } sconfig;
    struct wcd9335_slim_ch *slim_ch_list;
};
#define SNDRV_PCM_STREAM_CAPTURE 1
#define list_for_each_entry(pos, head, member) \
    for ((pos) = *(head); (pos); (pos) = (pos)->next)
static unsigned int reads[4096];
static unsigned int count;
static int fail_register = -1;
static unsigned int records;
static char log_line[1024];
static int regmap_read(void *map, unsigned int address, unsigned int *value) {
    (void)map;
    assert(count < sizeof(reads) / sizeof(reads[0]));
    reads[count++] = address;
    if ((int)address == fail_register) return -EIO;
    *value = address & 0xff;
    return 0;
}
static void dev_info(void *dev, const char *format, ...) {
    va_list args;
    (void)dev;
    va_start(args, format);
    vsnprintf(log_line, sizeof(log_line), format, args);
    va_end(args);
    records++;
}
'''

SUFFIX = r'''
int main(void) {
    struct wcd9335_codec codec = {0};
    /* Default-off must perform no register reads and consume no budget. */
    wcd9335_port_diag(&codec, "off", true, 1);
    assert(count == 0 && records == 0 && port_diag_budget == 128);
    port_diagnostics = true;
    wcd9335_port_diag(&codec, "tx", true, 1);
    assert(count == 4 && records == 1);
    assert(reads[0] == WCD9335_SLIM_PGD_TX_PORT_CFG(1));
    assert(reads[1] == WCD9335_SLIM_PGD_TX_PORT_MULTI_CHNL_0(1));
    assert(reads[2] == WCD9335_SLIM_PGD_TX_PORT_MULTI_CHNL_1(1));
    assert(reads[3] == WCD9335_SLIM_PGD_PORT_INT_TX_EN0);
    /* Errors must remain explicit; zeroed output must not look like a valid read. */
    fail_register = WCD9335_SLIM_PGD_TX_PORT_CFG(1);
    wcd9335_port_diag(&codec, "failed-read", true, 1);
    assert(strstr(log_line, "stage=failed-read"));
    assert(strstr(log_line, "cfg=0 cfg_rc=-5"));
    fail_register = -1;
    count = 0;
    wcd9335_port_diag(&codec, "rx", false, 2);
    assert(count == 3);
    /* Independent downstream mapping: RX2 cfg=0x42, map=0x188.
     * Local IRQ RX indices differ from SLIMbus stream ports 16..28. */
    assert(reads[0] == 0x42);
    assert(reads[1] == 0x188);
    assert(reads[2] == WCD9335_SLIM_PGD_PORT_INT_EN0);
    /* Stream RX port 18 and IRQ RX index 2 must inspect identical addresses. */
    unsigned int irq_addresses[3];
    memcpy(irq_addresses, reads, sizeof(irq_addresses));
    struct wcd9335_slim_ch rx = { .port = 18 };
    struct wcd_slim_codec_dai_data dai = { .slim_ch_list = &rx };
    count = 0;
    wcd9335_stream_diag(&codec, &dai, "rx-stream");
    assert(count == 3 && !memcmp(irq_addresses, reads, sizeof(irq_addresses)));
    assert(strstr(log_line, "dir=RX port=2 "));
    count = 0;
    wcd9335_port_diag(&codec, "rx12", false, 12);
    assert(count == 3 && reads[0] == 0x4c && reads[1] == 0x1b0);
    assert(reads[2] == WCD9335_SLIM_PGD_PORT_INT_EN0 + 1);
    count = 0;
    rx.port = 28;
    wcd9335_stream_diag(&codec, &dai, "rx-stream12");
    assert(count == 3 && reads[0] == 0x4c && reads[1] == 0x1b0);
    assert(reads[2] == WCD9335_SLIM_PGD_PORT_INT_EN0 + 1);
    count = 0;
    rx.port = 1;
    dai.sconfig.direction = SNDRV_PCM_STREAM_CAPTURE;
    wcd9335_stream_diag(&codec, &dai, "tx-stream");
    assert(count == 4 && reads[0] == 0x51 && reads[1] == 0x104);
    /* Upper bank must select the second interrupt-enable byte. */
    count = 0;
    wcd9335_port_diag(&codec, "tx8", true, 8);
    assert(reads[3] == WCD9335_SLIM_PGD_PORT_INT_TX_EN0 + 1);
    for (unsigned int i = 0; i < 200; i++)
        wcd9335_port_diag(&codec, "budget", true, 1);
    assert(port_diag_budget == 0 && records == 128);
    unsigned int final_count = count;
    wcd9335_port_diag(&codec, "exhausted", true, 1);
    assert(count == final_count && records == 128);
    puts("PASS: default-off, configuration addresses, read errors, RX/TX banks and 128-record cap");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-source", type=Path, required=True)
    args = parser.parse_args()
    codec = args.kernel_source / "sound/soc/codecs/wcd9335.c"
    # Build reports archive the exact patched codec files at their top level;
    # accept that layout as well as a complete kernel source tree.
    if not codec.is_file():
        codec = args.kernel_source / "wcd9335.c"
    if not codec.is_file():
        raise SystemExit("missing wcd9335.c under --kernel-source")
    header = codec.with_suffix(".h").read_text()
    source = codec.read_text()
    # Use the real header expressions. No fabricated register offsets in stubs.
    names = ["WCD9335_REG", "WCD9335_SLIM_PGD_TX_PORT_CFG",
             "WCD9335_SLIM_PGD_RX_PORT_CFG", "WCD9335_SLIM_PGD_TX_PORT_MULTI_CHNL_0",
             "WCD9335_SLIM_PGD_TX_PORT_MULTI_CHNL_1", "WCD9335_SLIM_PGD_RX_PORT_MULTI_CHNL_0",
             "WCD9335_SLIM_PGD_PORT_INT_EN0"]
    def macro(text, name):
        return next(line for line in text.splitlines()
                    if re.match(r"#define\s+" + re.escape(name) + r"(?=\s|\()", line))
    macros = [macro(header, name) for name in names]
    macros.append(macro(source, "WCD9335_SLIM_PGD_PORT_INT_TX_EN0"))
    macros.append(macro(source, "WCD9335_RX_START"))
    helpers = function(source, "static bool wcd9335_port_diag_claim(") + "\n" + function(source, "static void wcd9335_port_diag(") + "\n" + function(source, "static void wcd9335_stream_diag(")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / "test.c").write_text(PREFIX + "\n" + "\n".join(macros) + "\n" + helpers + "\n" + SUFFIX)
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-std=c11", str(path / "test.c"),
                        "-o", str(path / "test")], check=True, timeout=30)
        subprocess.run([str(path / "test")], check=True, timeout=5)


if __name__ == "__main__":
    main()
