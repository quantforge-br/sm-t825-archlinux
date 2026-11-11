#!/usr/bin/env python3
"""Host test for the bounded cross-driver event ring source.

It exercises disabled behavior, overwrite-oldest wrap, cursor paging,
explicit loss counts and worst-case page formatting;
it does not claim IRQ timing or hardware behavior.
"""
from pathlib import Path
import json
import re
import subprocess
import tempfile

PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
typedef uint64_t u64;
typedef unsigned long ulong;
#define PAGE_SIZE 4096
#define EXPORT_SYMBOL_GPL(x)
#define MODULE_PARM_DESC(x,y)
#define module_param_cb(n,ops,arg,perm) static const void *keep_##n __attribute__((unused)) = (void*)(ops)
#define module_param(...)
#define DEFINE_SPINLOCK(x) int x
#define spin_lock_irqsave(lock, flags) ((void)(lock), (flags)=0)
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))
#define GFP_KERNEL 0
#define kmalloc(size, flags) malloc(size)
#define kmalloc_array(n,size,flags) malloc((n)*(size))
#define kfree(ptr) free(ptr)
#define min_t(type,a,b) ((a)<(b)?(a):(b))
#define READ_ONCE(x) (x)
struct kernel_param { void *arg; };
struct kernel_param_ops { int (*set)(const char *, const struct kernel_param *); int (*get)(char *, const struct kernel_param *); };
static u64 now;
static u64 ktime_get_boottime_ns(void) { return ++now * 1000; }
static int scnprintf(char *b, size_t n, const char *f, ...) {
    va_list ap; va_start(ap, f); int r=vsnprintf(b,n,f,ap); va_end(ap); return r;
}
static size_t strscpy(char *d, const char *s, size_t n) { size_t l=strlen(s); if(n){size_t c=l<n-1?l:n-1;memcpy(d,s,c);d[c]=0;} return l; }
'''
SUFFIX = r'''
static int page(char *output, unsigned long long cursor) {
    struct kernel_param param={.arg=NULL};
    event_cursor=cursor; int n=slim_trace_get(output,&param);
    assert(n>0 && n<PAGE_SIZE); return n;
}
int main(void) {
    char output[PAGE_SIZE]; int n, largest=0;
    event_trace=false; slim_trace_event("disabled",1,2);
    page(output,0);
    assert(strstr(output,"enabled=0 count=0 total=0 dropped=0 first=0 next=0\n"));
    event_trace=true;
    for(int i=0;i<300;i++) slim_trace_event("event",i,-i);
    n=page(output,0);
    assert(strstr(output,"enabled=1 count=36 total=300 dropped=44 first=44 next=80\n"));
    assert(strstr(output,"\n44 ") && strstr(output,"event 44 -44\n"));
    assert(strstr(output,"event 43 -43") == NULL);
    unsigned long long cursor=44, seen=0;
    while(cursor<300) {
        n=page(output,cursor); if(n>largest) largest=n;
        unsigned count, total; unsigned long long dropped, first, next;
        assert(sscanf(output,"enabled=1 count=%u total=%u dropped=%llu first=%llu next=%llu",
                      &count,&total,&dropped,&first,&next)==5);
        assert(total==300 && dropped==0 && first==cursor && next==cursor+count && count>0);
        char *line=strchr(output,'\n')+1;
        for(unsigned i=0;i<count;i++) {
            unsigned long long seq, ns; char tag[32]; int a, b;
            assert(sscanf(line,"%llu %llu %31s %d %d",&seq,&ns,tag,&a,&b)==5);
            assert(seq==cursor+i && a==(int)seq && b==-(int)seq && !strcmp(tag,"event"));
            line=strchr(line,'\n')+1; seen++;
        }
        cursor=next;
    }
    assert(seen==256);
    page(output,400);
    assert(strstr(output,"count=0 total=300 dropped=0 first=300 next=300\n"));
    for(int i=0;i<36;i++) slim_trace_event("tag-with-thirty-one-characters!",-2147483647-1,-2147483647-1);
    n=page(output,300); if(n>largest) largest=n;
    assert(strstr(output,"count=36 total=336 dropped=0 first=300 next=336\n"));
    printf("{\"status\":\"PASS\",\"records\":336,\"capacity\":256,\"overwritten_before_cursor\":44,\"paged_records\":256,\"largest_page_bytes\":%d}\n",largest);
}
'''

def main():
    parser=__import__('argparse').ArgumentParser()
    parser.add_argument('source',type=Path);parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args(); source=args.source.read_text()
    start=source.index('static bool event_trace;');end=source.index('static void slim_stream_diag_result',start)
    block=source[start:end]
    assert 'SLIM_TRACE_CAPACITY 256' in block and 'module_param_cb(event_records' in block and 'event_cursor' in block
    args.output_dir.mkdir(parents=True,exist_ok=True); harness=args.output_dir/'event-trace-harness.c'
    harness.write_text('#include <stdarg.h>\n'+PREFIX+block+SUFFIX)
    with tempfile.TemporaryDirectory(prefix='t825-event-trace-') as tmp:
        binary=str(Path(tmp)/'test'); subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(harness),'-o',binary],check=True,timeout=30)
        result=json.loads(subprocess.check_output([binary],text=True,timeout=10))
    result.update(source_sha256=__import__('hashlib').sha256(source.encode()).hexdigest(),scope=__doc__.strip(),hardware_accepted=False)
    (args.output_dir/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__': main()
