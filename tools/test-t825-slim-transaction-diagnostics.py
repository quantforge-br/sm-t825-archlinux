#!/usr/bin/env python3
"""Differential execution of actual original/patched SLIMbus stream functions.

Host stubs inject bus/controller failures. This checks observation semantics,
not NGD firmware completion, timing, physical hardware safety or an audio fix.
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
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef int atomic_t;
#define ATOMIC_INIT(v) (v)
#define module_param(...)
#define MODULE_PARM_DESC(...)
#define EXPORT_SYMBOL_GPL(...)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define GFP_KERNEL 0
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SLIM_DEVICE_MAX_PORTS 32
#define SLIM_LA_MANAGER 0xff
#define SLIM_CHANNEL_CONTENT_FL 1
#define SLIM_SLOT_LEN_BITS 4
#define SLIM_CH_DATA_FMT_NOT_DEFINED 0
#define SLIM_CH_AUX_FMT_NOT_APPLICABLE 0
#define SLIM_PROTO_ISO 0
#define SLIM_PROTO_PUSH 1
#define SLIM_PROTO_PULL 2
#define SLIM_PORT_SINK 0
#define SLIM_PORT_SOURCE 1
#define SLIM_PORT_DISCONNECTED 0
#define SLIM_PORT_UNCONFIGURED 1
#define SLIM_PORT_CONFIGURED 2
#define SLIM_CH_STATE_DISCONNECTED 0
#define SLIM_CH_STATE_ALLOCATED 1
#define SLIM_CH_STATE_ASSOCIATED 2
#define SLIM_CH_STATE_DEFINED 3
#define SLIM_CH_STATE_CONTENT_DEFINED 4
#define SLIM_CH_STATE_ACTIVE 5
#define SLIM_CH_STATE_REMOVED 6
#define SLIM_MSG_MC_CONNECT_SOURCE 16
#define SLIM_MSG_MC_CONNECT_SINK 17
#define SLIM_MSG_MC_DISCONNECT_PORT 18
#define SLIM_MSG_MC_NEXT_DEACTIVATE_CHANNEL 19
#define SLIM_MSG_MC_NEXT_REMOVE_CHANNEL 20
#define SLIM_MSG_MC_NEXT_DEFINE_CONTENT 21
#define SLIM_MSG_MC_NEXT_DEFINE_CHANNEL 22
#define SLIM_MSG_MC_NEXT_ACTIVATE_CHANNEL 23
#define SLIM_MSG_MC_BEGIN_RECONFIGURATION 24
#define SLIM_MSG_MC_RECONFIGURE_NOW 25
struct slim_stream_runtime;
struct slim_controller {
    struct { int superfreq; } *a_framer;
    int (*enable_stream)(struct slim_stream_runtime *);
    int (*disable_stream)(struct slim_stream_runtime *);
};
struct slim_device { struct slim_controller *ctrl; int dev, laddr; };
struct slim_port {
    int id, state, direction;
    struct { int id, state, prrate, data_fmt, aux_fmt, seg_dist; } ch;
};
struct slim_stream_runtime {
    struct slim_device *dev;
    int num_ports, direction, prot;
    unsigned int rate, bps, ratem;
    struct slim_port *ports;
};
struct slim_stream_config {
    unsigned long port_mask;
    unsigned int rate, bps, *chs;
    int direction;
};
struct slim_val_inf { int start_offset, num_bytes; void *rbuf; u8 *wbuf; void *comp; };
struct slim_msg_txn { int mc; struct slim_val_inf *msg; };
#define DEFINE_SLIM_LDEST_TXN(n,c,r,l,m) struct slim_msg_txn n = {c,m}
#define DEFINE_SLIM_BCAST_TXN(n,c,r,l,m) struct slim_msg_txn n = {c,m}
#define kzalloc_objs(t,n) calloc(n,sizeof(t))
#define kfree(p) free(p)
#define hweight32(v) __builtin_popcount((unsigned)(v))
#define for_each_set_bit(i,p,n) for (i=0;i<(n);i++) if ((*(p)) & (1UL<<i))
#define dev_err(...) ((void)0)
static int logs, calls, fail_at, cb_error, callbacks;
static char last_log[1024];
static bool atomic_add_unless(atomic_t *v, int n, int unless) {
    if (*v == unless) return false;
    *v += n; return true;
}
static void dev_info(void *dev, const char *format, ...) {
    (void)dev;
    va_list ap; va_start(ap,format);
    vsnprintf(last_log,sizeof(last_log),format,ap); va_end(ap);
    logs++;
}
static int slim_do_transfer(struct slim_controller *ctrl, struct slim_msg_txn *txn) {
    (void)ctrl;
    int ret = ++calls == fail_at ? -EIO : 0;
    printf("T%d mc=%d rc=%d",calls,txn->mc,ret);
    if (txn->msg) {
        printf(" bytes=");
        for (int i=0;i<txn->msg->num_bytes;i++) printf("%02x",txn->msg->wbuf[i]);
    }
    puts("");
    /* Model an in-place controller rewrite; diagnostics must retain input mc. */
    txn->mc = 99;
    return ret;
}
static int controller_callback(struct slim_stream_runtime *stream) {
    printf("CB ports=%d rc=%d\n",stream->num_ports,cb_error);
    callbacks++;
    return cb_error;
}
'''
SUFFIX = r'''
int main(int argc, char **argv) {
    assert(argc == 4);
    fail_at = atoi(argv[1]);
    int mode = atoi(argv[2]);
    struct { int superfreq; } framer = {4000};
    struct slim_controller ctrl = {0};
    ctrl.a_framer = (void *)&framer;
    cb_error = mode == 2 ? -ETIMEDOUT : 0;
    if (mode) ctrl.enable_stream = ctrl.disable_stream = controller_callback;
    struct slim_device device = {.ctrl=&ctrl, .laddr=3};
    struct slim_stream_runtime stream = {.dev=&device};
    unsigned int channels[] = {128,129};
    struct slim_stream_config config = {.port_mask=3,.rate=48000,.bps=16,.chs=channels,.direction=1};
#ifdef PATCHED
    transaction_diagnostics = atoi(argv[3]);
#else
    (void)argv[3];
#endif
    int prepare = slim_stream_prepare(&stream,&config);
    printf("PREPARE %d ports=%d\n",prepare,stream.num_ports);
    assert(prepare == 0); /* The historical ignored connect error remains ignored. */
    int enable = slim_stream_enable(&stream);
    printf("ENABLE %d states=%d,%d\n",enable,stream.ports[0].ch.state,stream.ports[1].ch.state);
    if (mode == 2) assert(enable == -ETIMEDOUT);
    int disable = slim_stream_disable(&stream);
    printf("DISABLE %d states=%d,%d\n",disable,stream.ports[0].ch.state,stream.ports[1].ch.state);
    int unprepare = slim_stream_unprepare(&stream);
    printf("UNPREPARE %d ports=%d null=%d callbacks=%d\n",unprepare,stream.num_ports,stream.ports==NULL,callbacks);
    assert(unprepare == 0 && stream.ports == NULL && stream.num_ports == 0);
#ifdef PATCHED
    if (!transaction_diagnostics) assert(logs == 0 && transaction_diag_budget == 128);
    else assert(logs == calls + callbacks && transaction_diag_budget == 128-logs);
    /* With the budget exhausted, transfer still occurs and returns its error. */
    transaction_diag_budget = 0;
    transaction_diagnostics = true;
    int previous_logs = logs;
    struct slim_msg_txn txn = {.mc=18};
    fail_at = calls + 1;
    assert(slim_stream_diag_transfer(&stream,NULL,&txn,"budget") == -EIO);
    assert(logs == previous_logs && transaction_diag_budget == 0);
    /* Explicitly test pre-rewrite mc and failures in the emitted record. */
    transaction_diag_budget = 1; txn.mc=18; fail_at=calls+1;
    assert(slim_stream_diag_transfer(&stream,NULL,&txn,"request") == -EIO);
    assert(strstr(last_log,"stage=request") && strstr(last_log,"mc=18 rc=-5"));
    assert(strstr(last_log,"port=-1 channel=-1") && transaction_diag_budget == 0);
#else
    /* Same two transactions for differential comparison. */
    struct slim_msg_txn txn = {.mc=18}; fail_at=calls+1;
    assert(slim_do_transfer(&ctrl,&txn) == -EIO);
    txn.mc=18; fail_at=calls+1;
    assert(slim_do_transfer(&ctrl,&txn) == -EIO);
#endif
    return 0;
}
'''


def transformed(text):
    text = re.sub(r'^#include[^\n]*\n', '', text, flags=re.M)
    # Allocation/free are unrelated to this patch and require kernel list locks.
    for signature in ('struct slim_stream_runtime *slim_stream_allocate(', 'int slim_stream_free('):
        start = text.index(signature)
        end = text.index('\n}\n', start) + 3
        text = text[:start] + text[end:]
    return PREFIX + text + SUFFIX


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--patched', type=Path, required=True)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='slim-stream-differential-') as tmp:
        tmp = Path(tmp)
        for variant, path in (('original', args.original), ('patched', args.patched)):
            cfile = tmp / (variant + '.c')
            cfile.write_text(transformed(path.read_text()))
            command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                       '-Wno-unused-function', '-Wno-unused-variable', '-Wno-sign-compare']
            if variant == 'patched': command += ['-DPATCHED']
            subprocess.run(command + [str(cfile), '-o', str(tmp / variant)], check=True, timeout=30)
        checks = 0
        for mode in range(3):
            for fault in range(21):
                baseline = subprocess.run([str(tmp/'original'), str(fault), str(mode), '0'],
                                          check=True, capture_output=True, timeout=5).stdout
                for enabled in (0, 1):
                    result = subprocess.run([str(tmp/'patched'), str(fault), str(mode), str(enabled)],
                                            check=True, capture_output=True, timeout=5)
                    assert result.stdout == baseline, (mode, fault, enabled, baseline, result.stdout)
                    checks += 1
    report = {'status':'PASS_DIFFERENTIAL_STREAM_DIAGNOSTICS', 'comparisons':checks,
              'original_sha256':hashlib.sha256(args.original.read_bytes()).hexdigest(),
              'patched_sha256':hashlib.sha256(args.patched.read_bytes()).hexdigest(),
              'scope':'actual stream functions with stubbed bus/controller; no firmware or hardware acceptance'}
    encoded = json.dumps(report, indent=2) + '\n'
    if args.output: args.output.write_text(encoded)
    print(encoded, end='')

if __name__ == '__main__': main()
