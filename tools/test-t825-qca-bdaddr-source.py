#!/usr/bin/env python3
"""Run the actual qca_check_bdaddr function with host-only HCI stubs.

This checks address classification, not controller/firmware behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

PREFIX = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
typedef struct { unsigned char b[6]; } bdaddr_t;
static const bdaddr_t zero_address = {{0}};
#define BDADDR_ANY (&zero_address)
#define HCI_OP_READ_BD_ADDR 0x1009
#define HCI_INIT_TIMEOUT 2000
#define HCI_QUIRK_USE_BDADDR_PROPERTY 1
struct hci_dev { bdaddr_t public_addr; bool property; };
struct qca_fw_config { bdaddr_t bdaddr; };
struct hci_rp_read_bd_addr { unsigned char status; bdaddr_t bdaddr; };
struct sk_buff { unsigned int len; unsigned char *data; };
static struct hci_rp_read_bd_addr response;
static struct sk_buff packet;
static int requests, frees, transport_error;
#define IS_ERR(p) ((intptr_t)(p) < 0 && (intptr_t)(p) >= -4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define bt_dev_err(...) ((void)0)
static int bacmp(const bdaddr_t *a, const bdaddr_t *b) { return memcmp(a, b, 6); }
static void hci_set_quirk(struct hci_dev *dev, int quirk) {
    assert(quirk == HCI_QUIRK_USE_BDADDR_PROPERTY); dev->property = true;
}
static void kfree_skb(struct sk_buff *skb) { assert(skb == &packet); frees++; }
static struct sk_buff *__hci_cmd_sync(struct hci_dev *dev, int opcode,
                                     int len, void *data, int timeout) {
    (void)dev; assert(opcode == HCI_OP_READ_BD_ADDR);
    assert(len == 0 && data == NULL && timeout == HCI_INIT_TIMEOUT);
    requests++;
    if (transport_error) return (void *)(intptr_t)transport_error;
    return &packet;
}
'''
SUFFIX = r'''
static void reset(const bdaddr_t *value) {
    response.status = 0; response.bdaddr = *value;
    packet.len = sizeof(response); packet.data = (void *)&response;
    requests = frees = transport_error = 0;
}
int main(void) {
    const bdaddr_t stock = {{0xad, 0x5a, 0, 0, 0, 0}};
    const bdaddr_t board = {{0xbc, 0x9a, 0x78, 0x56, 0x34, 0x12}};
    struct hci_dev dev = {0};
    struct qca_fw_config config = {.bdaddr = stock};
    reset(&stock);
    assert(qca_check_bdaddr(&dev, &config) == 0);
    assert(dev.property && requests == 1 && frees == 1);
    /* Editing NVM also changes config.bdaddr; an equal readback is still default. */
    dev = (struct hci_dev){0}; config.bdaddr = board; reset(&board);
    assert(qca_check_bdaddr(&dev, &config) == 0);
    assert(dev.property && requests == 1 && frees == 1);
    /* A pre-provisioned public_addr bypasses the comparison entirely. */
    dev = (struct hci_dev){.public_addr = board}; reset(&board);
    assert(qca_check_bdaddr(&dev, &config) == 0);
    assert(!dev.property && requests == 0 && frees == 0);
    /* A controller readback differing from the NVM default is treated differently. */
    dev = (struct hci_dev){0}; config.bdaddr = stock; reset(&board);
    assert(qca_check_bdaddr(&dev, &config) == 0);
    assert(!dev.property && requests == 1 && frees == 1);
    reset(&board); transport_error = -ETIMEDOUT;
    assert(qca_check_bdaddr(&dev, &config) == -ETIMEDOUT);
    assert(!dev.property && frees == 0);
    reset(&board); packet.len--;
    assert(qca_check_bdaddr(&dev, &config) == -EIO);
    assert(!dev.property && frees == 1);
    puts("PASS: stock and edited NVM equal-readback cases both require address property; public_addr bypass and error paths verified");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = args.kernel_source / 'drivers/bluetooth/btqca.c'
    raw = source.read_bytes()
    text = raw.decode()
    start = text.index('static int qca_check_bdaddr(')
    end = text.index('\n}\n', start) + 3
    actual = text[start:end]
    with tempfile.TemporaryDirectory(prefix='qca-address-check-') as tmp:
        cfile, binary = Path(tmp) / 'check.c', Path(tmp) / 'check'
        cfile.write_text(PREFIX + actual + SUFFIX)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)], check=True, timeout=30)
        result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
    report = {'source': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'function_sha256': hashlib.sha256(actual.encode()).hexdigest(),
              'status': 'PASS_SOURCE_ADDRESS_CLASSIFICATION', 'output': result.stdout.strip(),
              'controller_readback_observed': False, 'reset_timeout_cause_proven': False,
              'production_fix_accepted': False}
    encoded = json.dumps(report, indent=2) + '\n'
    if args.output: args.output.write_text(encoded)
    print(encoded, end='')

if __name__ == '__main__': main()
