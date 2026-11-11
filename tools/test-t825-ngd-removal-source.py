#!/usr/bin/env python3
"""Execute experimental NGD removal and stream-disable functions with host stubs.

Checks protocol bytes, ACK handling, bounds, error propagation and transaction
cleanup. Does not validate firmware behavior, concurrency or physical audio.
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
#define BIT(n) (1U << (n))
#define SLIM_MSGQ_BUF_LEN 40
#define SLIM_MSG_MT_DEST_REFERRED_USER 2
#define SLIM_MSG_DEST_LOGICALADDR 0
#define SLIM_LA_MGR 255
#define SLIM_LA_MANAGER 255
#define SLIM_USR_MC_CHAN_CTRL 0x23
#define SLIM_USR_MC_RECONFIG_NOW 0x24
#define SLIM_MSG_MC_BEGIN_RECONFIGURATION 0x40
#define SLIM_MSG_MC_RECONFIGURE_NOW 0x5f
#define EXPORT_SYMBOL_GPL(...)
#define DEFINE_SLIM_BCAST_TXN(n,c,r,l,m) struct slim_msg_txn n = {.mc=c}
struct slim_stream_runtime;
struct slim_controller { int (*disable_stream)(struct slim_stream_runtime *); };
struct slim_device { struct slim_controller *ctrl; u8 laddr; };
struct slim_port { struct { int id; } ch; };
struct slim_stream_runtime { struct slim_device *dev; int num_ports; struct slim_port *ports; };
struct slim_val_inf { u8 *rbuf; const u8 *wbuf; int num_bytes; };
struct slim_msg_txn { int mt,dt,la,mc,rl; u8 tid; struct slim_val_inf *msg; };
static int allocs, transfers, freed, fail_alloc, fail_xfer, silent, ack[2];
static int generic_calls, callback_rc, diagnostic_rc;
static u8 payloads[2][40];
static int sizes[2], opcodes[2];
static int slim_alloc_txn_tid(struct slim_controller *c, struct slim_msg_txn *t) {
    (void)c; allocs++; t->tid = 100 + allocs;
    return allocs == fail_alloc ? -ENOMEM : 0;
}
static void slim_free_txn_tid(struct slim_controller *c, struct slim_msg_txn *t) {
    (void)c; (void)t; freed++;
}
static int qcom_slim_ngd_xfer_msg_sync(struct slim_controller *c, struct slim_msg_txn *t) {
    (void)c;
    assert(transfers < 2 && t->msg->num_bytes <= 36);
    assert(t->rl == t->msg->num_bytes + 4);
    assert(t->mt == 2 && t->dt == 0 && t->la == 255);
    sizes[transfers] = t->msg->num_bytes; opcodes[transfers] = t->mc;
    memcpy(payloads[transfers],t->msg->wbuf,t->msg->num_bytes);
    transfers++; t->rl--; /* Real xfer modifies rl; commit must rebuild it. */
    if (transfers == fail_xfer) return -ETIMEDOUT;
    /* Successful real response handling consumes the TID, including NACK. */
    if (transfers != silent) t->msg->rbuf[0] = ack[transfers-1];
    return 0;
}
static void slim_stream_diag_result(struct slim_stream_runtime *s, void *p,
                                   const char *stage, int mc, int ret) {
    (void)s; (void)p; (void)stage; (void)mc; diagnostic_rc = ret;
}
static int slim_stream_diag_transfer(struct slim_stream_runtime *s, void *p,
                                    struct slim_msg_txn *t, const char *stage) {
    (void)s; (void)p; (void)t; (void)stage; generic_calls++; return 0;
}
static int slim_deactivate_remove_channel(struct slim_stream_runtime *s, struct slim_port *p) {
    (void)s; (void)p; generic_calls++; return 0;
}
static int callback(struct slim_stream_runtime *s) { (void)s; return callback_rc; }
static void reset(void) {
    allocs=transfers=freed=fail_alloc=fail_xfer=silent=generic_calls=0;
    ack[0]=ack[1]=0x20;
    memset(payloads,0,sizeof(payloads));
}
'''

SUFFIX = r'''
int main(void) {
    struct slim_controller ctrl = {0};
    struct slim_device dev = {.ctrl=&ctrl,.laddr=0x23};
    struct slim_port ports[35] = {0};
    struct slim_stream_runtime rt = {.dev=&dev,.num_ports=2,.ports=ports};
    ports[0].ch.id=128; ports[1].ch.id=129;
    int cases=0;
    for (int stage=0; stage<2; stage++) {
        for (int value=0; value<256; value++) {
            reset(); ack[stage]=value;
            int rc=qcom_slim_ngd_disable_stream(&rt);
            bool ok=(value & 0x20)!=0;
            assert(rc==(ok ? 0 : -EIO));
            assert(transfers==(!ok && stage==0 ? 1 : 2));
            assert(allocs==transfers && freed==0);
            assert(opcodes[0]==0x23 && sizes[0]==4);
            assert(!memcmp(payloads[0],(u8[]){0x83,101,128,129},4));
            if (transfers==2) {
                assert(opcodes[1]==0x24 && sizes[1]==2);
                assert(!memcmp(payloads[1],(u8[]){102,0x23},2));
            }
            cases++;
        }
    }
    for (int stage=1; stage<=2; stage++) {
        reset(); fail_alloc=stage;
        assert(qcom_slim_ngd_disable_stream(&rt)==-ENOMEM);
        assert(transfers==stage-1 && freed==0); cases++;
        reset(); fail_xfer=stage;
        assert(qcom_slim_ngd_disable_stream(&rt)==-ETIMEDOUT);
        assert(transfers==stage && freed==1); cases++;
        reset(); silent=stage;
        assert(qcom_slim_ngd_disable_stream(&rt)==-EIO);
        assert(transfers==stage && freed==0); cases++;
    }
    for (int i=0; i<3; i++) {
        reset(); rt.num_ports=(int[]){-1,0,35}[i];
        assert(qcom_slim_ngd_disable_stream(&rt)==-EINVAL);
        assert(allocs==0 && transfers==0); cases++;
    }
    reset(); rt.num_ports=2; rt.ports=NULL;
    assert(qcom_slim_ngd_disable_stream(&rt)==-EINVAL);
    assert(allocs==0); cases++;
    rt.ports=ports;
    for (int i=0; i<2; i++) {
        reset(); rt.num_ports=i ? 34 : 1;
        assert(qcom_slim_ngd_disable_stream(&rt)==0);
        assert(sizes[0]==rt.num_ports+2 && transfers==2); cases++;
    }
    rt.num_ports=2;
    for (int i=0; i<3; i++) {
        reset(); ctrl.disable_stream=i ? callback : NULL;
        callback_rc=i==2 ? -EIO : 0;
        assert(slim_stream_disable(&rt)==callback_rc);
        assert(generic_calls==(i==2 ? 0 : 4));
        if (i) assert(diagnostic_rc==callback_rc);
        cases++;
    }
    printf("{\"status\":\"PASS\",\"cases\":%d,\"ack_byte_cases\":512}\n",cases);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ngd', type=Path)
    parser.add_argument('stream', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    ngd, stream = args.ngd.read_text(), args.stream.read_text()
    assert 'if (channel_removal)\n\t\tctrl->ctrl.disable_stream = qcom_slim_ngd_disable_stream;' in ngd
    assert 'static bool channel_removal;' in ngd
    assert 'module_param(channel_removal, bool, 0444);' in ngd
    removal = ngd[ngd.index('static int qcom_slim_ngd_remove_xfer('):ngd.index('static int qcom_slim_ngd_get_laddr(')]
    disable = stream[stream.index('int slim_stream_disable('):stream.index('EXPORT_SYMBOL_GPL(slim_stream_disable);')]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    harness = args.output_dir/'ngd-removal-harness.c'
    constants = '\n'.join(re.findall(r'^#define SLIM_NGD_(?:ACK_SUCCESS|CHAN_REMOVE)[^\n]*', ngd, re.M))
    assert len(constants.splitlines()) == 2
    harness.write_text(PREFIX + constants + '\n' + removal + disable + SUFFIX)
    with tempfile.TemporaryDirectory(prefix='t825-ngd-removal-') as tmp:
        binary = str(Path(tmp)/'test')
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(harness),'-o',binary],check=True,timeout=30)
        result = json.loads(subprocess.check_output([binary],text=True,timeout=10))
    result.update(ngd_sha256=hashlib.sha256(ngd.encode()).hexdigest(),
                  stream_sha256=hashlib.sha256(stream.encode()).hexdigest(),
                  scope=__doc__.strip(), hardware_accepted=False)
    (args.output_dir/'removal-tests.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
