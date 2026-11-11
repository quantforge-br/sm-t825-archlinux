#!/usr/bin/env bash
# Build an AArch64 static Linux supervisor without a target C library.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: build-t825-recovery-supervisor.sh OUTPUT}
linker=${T825_LLD:-/usr/lib/llvm22/bin/ld.lld}
clang --target=aarch64-linux-gnu --ld-path="$linker" -nostdlib -static \
    -ffreestanding -fno-builtin -fno-stack-protector -fno-unwind-tables \
    -fno-asynchronous-unwind-tables -Wl,--build-id=none -Wl,-e,_start \
    -O2 -Wall -Wextra -Werror "$here/tools/t825-recovery-supervisor.c" -o "$out"
