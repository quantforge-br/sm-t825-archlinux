#!/usr/bin/env python3
"""Validate an unaccepted audio-diagnostic RAM image without hardware."""
from pathlib import Path
import gzip, json, re, struct, subprocess, sys, tempfile

def fail(msg): raise AssertionError(msg)
def main(bundle):
    bundle=Path(bundle); image=(bundle/'t825-audiodiag-ram.img').read_bytes();
    (bundle/'NOT_ACCEPTED').is_file() or fail('missing NOT_ACCEPTED marker')
    subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=bundle,check=True,capture_output=True)
    image[:8]==b'ANDROID!' or fail('bad boot magic')
    ks,ka,rs,ra,ss,sa,ta,page,ver,_=struct.unpack_from('<10I',image,8)
    (ka,ra,ss,sa,ta,page,ver)==(0x80008000,0x82200000,0,0x80F00000,0x82000000,4096,0) or fail('bad boot header')
    kernel=(bundle/'vmlinuz').read_bytes(); archive=(bundle/'initramfs').read_bytes()
    dtbs=b''.join((bundle/'dtbs/qcom'/n).read_bytes() for n in ('apq8096-samsung-gts3lwifi.dtb','msm8996-samsung-gts3llte.dtb'))
    image[page:page+ks]==kernel+dtbs or fail('kernel/DTBs not embedded')
    off=(page+ks+page-1)//page*page; image[off:off+rs]==archive or fail('initramfs not embedded')
    cmd=image[64:576].split(b'\0',1)[0].decode(); words=cmd.split()
    for w in ('t825.ramdiag','t825.direct-init','panic=10','snd_soc_wcd9335.port_diagnostics=1'):
        w in words or fail('missing cmdline '+w)
    't825.mssdiag' not in words or fail('MSS diagnostic cmdline leaked')
    fdtget=subprocess.run(['fdtget','-t','s',str(bundle/'dtbs/qcom/msm8996-samsung-gts3llte.dtb'),'/soc/remoteproc@2080000','status'],capture_output=True,text=True,check=True).stdout.strip()
    fdtget=='disabled' or fail('LTE MSS enabled')
    raw=gzip.decompress(kernel); budget=(52428800-rs)//page*page-2097152-32768; len(raw)<=budget or fail('memory budget exceeded')
    with tempfile.TemporaryDirectory(prefix='t825-audio-image-') as tmp:
        tree=Path(tmp)
        data=subprocess.run(['unzstd','-c',str(bundle/'initramfs')],check=True,capture_output=True).stdout
        subprocess.run(['cpio','-id','--quiet','--no-absolute-filenames'],cwd=tree,input=data,check=True)
        release=tree/'usr/lib/modules/7.3.1-t825-audiodiag'; release.is_dir() or fail('audiodiag module tree missing')
        not (tree/'usr/lib/modules/7.3.1-t825').exists() or fail('normal module release leaked')
        module=release/'kernel/sound/soc/codecs/snd-soc-wcd9335.ko.zst'; module.is_file() or fail('instrumented codec module missing')
        if 'slimbus.transaction_diagnostics=1' in words:
            slim=release/'kernel/drivers/slimbus/slimbus.ko.zst'
            slim.is_file() or fail('transaction diagnostic SLIMbus module missing')
            params=subprocess.run(['modinfo','-F','parm',str(slim)],check=True,capture_output=True,text=True).stdout
            'transaction_diagnostics:' in params or fail('SLIMbus module lacks transaction parameter')
            vermagic=subprocess.run(['modinfo','-F','vermagic',str(slim)],check=True,capture_output=True,text=True).stdout
            vermagic.startswith('7.3.1-t825-audiodiag ') or fail('SLIMbus module release mismatch')
        if 'slim_qcom_ngd_ctrl.channel_removal=1' in words:
            'slimbus.transaction_diagnostics=1' in words or fail('NGD removal lacks transaction diagnostics')
            ngd=release/'kernel/drivers/slimbus/slim-qcom-ngd-ctrl.ko.zst'
            params=subprocess.run(['modinfo','-F','parm',str(ngd)],check=True,capture_output=True,text=True).stdout
            'channel_removal:' in params or fail('NGD module lacks removal parameter')
            vermagic=subprocess.run(['modinfo','-F','vermagic',str(ngd)],check=True,capture_output=True,text=True).stdout
            vermagic.startswith('7.3.1-t825-audiodiag ') or fail('NGD module release mismatch')
        if 'slimbus.event_trace=1' in words:
            'slimbus.transaction_diagnostics=1' in words or fail('event trace lacks transaction diagnostics')
            params=subprocess.run(['modinfo','-F','parm',str(slim)],check=True,capture_output=True,text=True).stdout
            'event_trace:' in params or fail('SLIMbus module lacks event trace parameter')
            'event_cursor:' in params or fail('SLIMbus module lacks event cursor parameter')
        dep=(release/'modules.dep').read_text(); 'snd-soc-wcd9335.ko.zst' in dep or fail('module metadata missing codec')
        for component in ('kernel/drivers/remoteproc/qcom_q6v5_pas.ko.zst',
                          'kernel/sound/soc/codecs/snd-soc-rt5508.ko.zst',
                          'kernel/sound/soc/qcom/qdsp6/q6afe-dai.ko.zst',
                          'kernel/sound/soc/qcom/qdsp6/q6asm-dai.ko.zst'):
            (release/component).is_file() or fail('missing audio provider: '+component)
        # Symbol dependencies alone omit providers connected through DT/APR.
        # Check both those explicit providers and their transitive closure.
        for line in dep.splitlines():
            key, values = line.split(':', 1)
            for component in [key, *values.split()]:
                (release/component).is_file() or fail('incomplete module closure: '+component)
        init=(tree/'init_2nd.sh').read_text(); funcs=(tree/'init_functions.sh').read_text()
        for line in ('delete_old_install_partition','resize_root_partition','resize_root_filesystem','resize_filesystem_after_mount /sysroot','wait_boot_partition','mount_boot_partition /sysroot/boot'):
            line not in init.splitlines() or fail('unsafe init operation remains: '+line)
        for cmdx in ('e2fsck -p','fsck.f2fs -p','fsck.vfat -p','fsck.xfs -p'):
            cmdx not in funcs or fail('filesystem repair remains')
        't825_root_mountopts=ro,rescue=nologreplay' in funcs or fail('Btrfs replay not disabled')
        'busybox blockdev --setro "$t825_root_device" || fail_halt_boot' in funcs or fail('member protection missing')
        'busybox blockdev --getro "$t825_root_device"' in funcs or fail('member protection not verified')
        'init="/run/t825-recovery/postpivot-init"' in init or fail('direct PID1 missing')
        'busybox ash /hooks-cleanup/90-t825-readonly-runtime.sh || fail_halt_boot' in init or fail('cleanup fail-closed missing')
        early=funcs.split('mount_proc_sys_dev() {',1)[1].split('\n}',1)[0]
        early.index('run /run || fail_halt_boot') < early.index('t825-recovery-arm') < early.index('modprobe') or fail('recovery armed too late')
        arm=(tree/'usr/local/libexec/t825-recovery-arm').read_text()
        't825.ramdiag' in arm and 't825-recovery-supervisor 240' in arm or fail('recovery deadline missing')
        elf=(tree/'usr/local/libexec/t825-recovery-supervisor').read_bytes()
        elf[:4]==b'\x7fELF' and struct.unpack_from('<H',elf,18)[0]==183 or fail('supervisor is not AArch64')
        cleanup=(tree/'hooks-cleanup/90-t825-readonly-runtime.sh').read_text()
        for step in ('kill -0 "$(cat /run/t825-recovery/supervisor.pid)"','mount --move /run /sysroot/run','mount -o remount,bind,ro /sysroot/usr/lib/modules'):
            step in cleanup or fail('missing recovery handoff step: '+step)
    print(json.dumps({'status':'OFFLINE_AUDIO_IMAGE_PASS_NOT_BOOT_ACCEPTANCE','image_sha256':__import__('hashlib').sha256(image).hexdigest(),'kernel_decompressed':len(raw),'initramfs':rs,'budget':budget,'margin':budget-len(raw),'scope':'no tablet boot, no module load, no audio capture'},indent=2))
if __name__=='__main__': main(sys.argv[1])
