#!/usr/bin/env python3
"""Execute the pinned NGD transfer function with host-side transport stubs.

Proves local dispatch/return behavior, not DSP protocol semantics, DMA timing,
acknowledgement payload validity, or the cause of a physical codec overflow.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
struct completion { int unused; };
#define DECLARE_COMPLETION_ONSTACK(n) struct completion n = {0}
#define HZ 100
#define dev_err(...) ((void)0)
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
/* Header encoding is outside this harness's dispatch/return scope. */
#define SLIM_MSG_ASM_FIRST_WORD(l, mt, mc, dt, ad) \
    ((void)(mt), (void)(mc), (void)(dt), (void)(ad), (u32)(l))
struct slim_controller { void *dev; };
struct qcom_slim_ngd_ctrl { void *dev; int tx_lock; };
struct slim_val_inf { int num_bytes; const u8 *wbuf; u8 *rbuf; };
struct slim_msg_txn {
    u8 mt, mc, dt, la, tid;
    int rl, ec;
    struct slim_val_inf *msg;
    struct completion *comp;
};
static struct qcom_slim_ngd_ctrl controller;
static int gets, posts, tids, waits, fail;
static u32 packet[64];
static void *dev_get_drvdata(void *dev) { (void)dev; return &controller; }
static u32 *qcom_slim_ngd_tx_msg_get(struct qcom_slim_ngd_ctrl *c,
                                  int len, struct completion *done) {
    (void)c; (void)len; (void)done; gets++;
    return fail == 1 ? NULL : packet;
}
static int slim_alloc_txn_tid(struct slim_controller *c, struct slim_msg_txn *t) {
    (void)c; tids++; t->tid = 7; return fail == 2 ? -ENOMEM : 0;
}
static int qcom_slim_ngd_tx_msg_post(struct qcom_slim_ngd_ctrl *c, u32 *p, int n) {
    (void)c; (void)p; (void)n; posts++; return fail == 3 ? -EIO : 0;
}
static unsigned long wait_for_completion_timeout(struct completion *c, int n) {
    (void)c; (void)n; waits++;
    return ((fail == 4 && waits == 1) || (fail == 5 && waits == 2)) ? 0 : 1;
}
/* These transformed user messages carry the TID in their explicit payload. */
static bool slim_tid_txn(u8 mt, u8 mc) { (void)mt; (void)mc; return false; }
static bool slim_ec_txn(u8 mt, u8 mc) { (void)mt; (void)mc; return false; }
'''

SUFFIX = r'''
int main(void) {
    struct slim_controller ctrl = {0};
    int bypassed = 0, cases = 0;
    /* Enum destination and NULL message make any accidental fallthrough fail.
     * For other messages, the source rejects enum before dereferencing msg. */
    for (int mt = 0; mt < 8; mt++) {
        for (int mc = 0; mc < 128; mc++) {
            struct slim_msg_txn txn = {.mt=mt, .mc=mc, .dt=SLIM_MSG_DEST_ENUMADDR};
            int rc = qcom_slim_ngd_xfer_msg(&ctrl, &txn);
            bool bypass = mt == 0 && mc >= 0x40 && mc <= 0x5f;
            assert(rc == (bypass ? 0 : -EPROTONOSUPPORT));
            assert(gets == 0 && posts == 0 && tids == 0 && waits == 0);
            bypassed += bypass; cases++;
        }
    }
    assert(bypassed == 32);
    const int core[] = {0x10, 0x11, 0x14};
    const int user[] = {0x2c, 0x2d, 0x2e};
    const int returns[] = {0, -ENOMEM, -ENOMEM, -EIO, -ETIMEDOUT, -ETIMEDOUT};
    for (int i = 0; i < 3; i++) {
        for (fail = 0; fail < 6; fail++) {
            u8 data[] = {1, 129};
            struct slim_val_inf msg = {.num_bytes=2, .wbuf=data};
            struct slim_msg_txn txn = {.mt=SLIM_MSG_MT_CORE, .mc=core[i],
                .dt=SLIM_MSG_DEST_LOGICALADDR, .la=3, .rl=6, .msg=&msg};
            gets = posts = tids = waits = 0;
            int rc = qcom_slim_ngd_xfer_msg(&ctrl, &txn);
            assert(rc == returns[fail]);
            assert(gets == 1);
            assert(tids == (fail != 1));
            assert(posts == (fail != 1 && fail != 2));
            assert(waits == (fail == 0 || fail == 5 ? 2 : fail == 4 ? 1 : 0));
            if (fail != 1) {
                assert(txn.mt == SLIM_MSG_MT_DEST_REFERRED_USER);
                assert(txn.mc == user[i]);
            }
            /* txn points to expired stack buffers after return; never read them. */
            cases++;
        }
    }
    printf("{\"dispatch_cases\":1024,\"zero_without_transport\":%d,"
           "\"translated_failure_cases\":18,\"total_cases\":%d}\n", bypassed, cases);
}
'''


def extract(source: str) -> str:
    """Take the entire function, without rewriting its conditions or returns."""
    start = source.index("static int qcom_slim_ngd_xfer_msg(")
    end = source.index("\nstatic int qcom_slim_ngd_xfer_msg_sync(", start)
    return source[start:end]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("header", type=Path)
    parser.add_argument("--hardware-analysis", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, header = args.source.read_text(), args.header.read_text()
    function = extract(source)
    definitions = "\n".join(re.findall(
        r"^#define\s+SLIM_\w+\s+(?:0x[0-9a-fA-F]+|[0-9]+)\s*$",
        header + "\n" + source, re.M))
    generated = PREFIX + "\n" + definitions + "\n" + function + SUFFIX
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    cfile = out / "ngd-transfer-harness.c"
    cfile.write_text(generated)
    with tempfile.TemporaryDirectory(prefix="t825-ngd-source-") as tmp:
        binary = str(Path(tmp) / "harness")
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(cfile), "-o", binary], check=True, timeout=30)
        result = json.loads(subprocess.check_output([binary], text=True, timeout=10))
    result.update({
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "header_sha256": hashlib.sha256(header.encode()).hexdigest(),
        "function_sha256": hashlib.sha256(function.encode()).hexdigest(),
        "scope": __doc__.strip(),
        "production_fix_accepted": False,
    })
    if args.hardware_analysis:
        evidence = json.loads(args.hardware_analysis.read_text())
        classes = []
        for record in evidence["stream_records"]:
            opcode = int(record["mc"])
            if record["stage"] == "controller-enable" and opcode == -1:
                classification = "aggregate-controller-enable"
            elif record["stage"] in ("slim_stream_disable", "slim_deactivate_remove_channel") and 0x40 <= opcode <= 0x5f:
                classification = "core-reconfiguration-bypassed-before-transmission"
            elif record["stage"] in ("slim_connect_port_channel", "slim_disconnect_port") and opcode in (0x10, 0x11, 0x14):
                classification = "translated-user-message-with-completion-waits"
            else:
                raise ValueError(f"Unclassified stream record: {record}")
            classes.append({**record, "dispatch_class": classification})
        result["hardware_records"] = classes
        result["hardware_analysis_sha256"] = hashlib.sha256(args.hardware_analysis.read_bytes()).hexdigest()
        result["hardware_class_counts"] = {
            name: sum(row["dispatch_class"] == name for row in classes)
            for name in sorted({row["dispatch_class"] for row in classes})
        }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
