/* SPDX-License-Identifier: MIT
 * Freestanding AArch64 Linux boot recovery supervisor. No dynamic loader,
 * shell, pathname lookup of commands, or dependency on the root after pivot.
 * Build with tools/build-t825-recovery-supervisor.sh.
 */
typedef unsigned long ulong;
struct timespec { long sec, nsec; };
static long call(long n, long a, long b, long c, long d, long e) {
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x4 __asm__("x4") = e;
    register long x8 __asm__("x8") = n;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x8) : "memory", "cc");
    return x0;
}
static ulong length(const char *s) { ulong n = 0; while (s[n]) ++n; return n; }
static int equal(const char *a, const char *b) { while (*a && *a == *b) { ++a; ++b; } return *a == *b; }
static long number(const char *s) {
    long n = 0;
    if (!*s) return -1;
    for (; *s && *s != '\n'; ++s) {
        if (*s < '0' || *s > '9' || n > 36000000) return -1;
        n = n * 10 + *s - '0';
    }
    return n;
}
static long now(void) {
    struct timespec t;
    if (call(113, 7 /* CLOCK_BOOTTIME */, (long)&t, 0, 0, 0) < 0) return -1;
    return t.sec;
}
static void pause_seconds(long seconds) {
    struct timespec t = { seconds, 0 }, remaining;
    while (call(101, (long)&t, (long)&remaining, 0, 0, 0) == -4) t = remaining;
}
static void emit(long fd, const char *s) {
    ulong count = length(s), done = 0;
    while (done < count) {
        long n = call(64, fd, (long)(s + done), count - done, 0, 0);
        if (n == -4) continue;
        if (n <= 0) break;
        done += n;
    }
}
static void emit_number(long fd, long n) {
    char buf[24]; int i = 23; buf[i] = 0;
    do { buf[--i] = '0' + n % 10; n /= 10; } while (n);
    emit(fd, buf + i);
}
static long open_file(long dir, const char *name, long flags) {
    return call(56, dir, (long)name, flags, 0600, 0);
}
static void stop(long code) { call(93, code, 0, 0, 0, 0); for (;;) {} }
__attribute__((used)) void recovery_start(ulong *stack) {
    long argc = stack[0]; char **argv = (char **)(stack + 1);
    if (argc != 3 && argc != 4) stop(2);
    int dry = argc == 4 && equal(argv[3], "--dry-run");
    if (argc == 4 && !dry) stop(2);
    long seconds = number(argv[1]);
    if (seconds < 1 || seconds > 3600) stop(2);
    long dir = open_file(-100, argv[2], 040000 /* O_DIRECTORY */);
    if (dir < 0) stop(3);
    long log = open_file(dir, "supervisor.log", 1 | 0100 | 02000);
    if (log < 0) stop(3);
    long begin = now(); if (begin < 0) stop(4);
    long end = begin + seconds, hard_end = begin + 3600;
    emit(log, "armed at "); emit_number(log, begin);
    emit(log, " deadline "); emit_number(log, end); emit(log, "\n");
    /* Keep this fd across switch_root; filenames above are relative to tmpfs. */
    long sysrq = dry ? -1 : open_file(-100, "/proc/sysrq-trigger", 1);
    for (;;) {
        long time = now(); if (time < 0) stop(4);
        long lease = open_file(dir, "lease", 0);
        if (lease >= 0) {
            char text[24]; long n = call(63, lease, (long)text, sizeof(text) - 1, 0, 0);
            call(57, lease, 0, 0, 0, 0);
            if (n > 0) {
                text[n] = 0; long candidate = number(text);
                /* Untrusted/stale/oversized leases cannot disable recovery. */
                if (candidate > end && candidate <= time + 120 && candidate <= hard_end)
                    end = candidate;
            }
        }
        if (time >= end) break;
        pause_seconds(1);
    }
    emit(log, "deadline expired at "); emit_number(log, now()); emit(log, "\n");
    if (dry) { emit(log, "dry-run: reboot suppressed\n"); stop(0); }
    /* A successful-but-stalled reboot must still have a fallback. The child
     * remains independent of systemd and uses an already-open procfs fd. */
    if (sysrq >= 0 && call(220, 17 /* SIGCHLD */, 0, 0, 0, 0) == 0) {
        pause_seconds(10);
        emit(log, "reboot stalled: emergency SysRq fallback\n");
        emit(sysrq, "b"); stop(5);
    }
    emit(log, "requesting kernel restart\n");
    long result = call(142, 0xfee1dead, 672274793, 0x01234567, 0, 0);
    emit(log, "kernel restart returned unexpectedly\n");
    if (sysrq >= 0) emit(sysrq, "b");
    stop(result < 0 ? 5 : 6);
}
__asm__(".global _start\n_start:\n mov x0, sp\n bl recovery_start\n b .\n");
