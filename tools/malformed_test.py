# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded malformed-image recovery tests and native accessibility inspection."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time
from types import SimpleNamespace
import stress_test as t


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,default=t.ROOT/'dist/foto.exe')
    parser.add_argument('--samples',type=int,default=200)
    options=parser.parse_args()
    assert 1<=options.samples<=256
    suite=t.Suite(SimpleNamespace(exe=options.exe,only='malformed',soak_seconds=1,cycles=1,actions=1,folder_entries=3))
    view=t.Session(suite,'malformed',suite.assets/'photo1.png')
    rng=random.Random(1847)
    sources=[t.ROOT/'tests/fixtures/colors.png',t.ROOT/'tests/fixtures/orientation-1.jpg']
    originals={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    accepted=rejected=0
    samples=[]
    started=time.monotonic()
    try:
        t.center_color(view.hwnd,suite.red)
        # Positive and negative controls verify that successes and failures are observable.
        invalid=suite.output/'not-an-image.png';invalid.write_bytes(b'not an image')
        view.drop(invalid,error=True)
        view.drop(suite.assets/'photo1.png');t.center_color(view.hwnd,suite.red)
        before=t.resources(view.process)
        for number in range(options.samples):
            source=sources[number%len(sources)];data=bytearray(source.read_bytes())
            mode=(number//len(sources))%4
            if mode==0:data=data[:rng.randrange(33,len(data))]
            elif mode==1:
                # Preserve dimension-bearing headers; mutate a bounded tail instead.
                for _ in range(4):data[rng.randrange(max(41,len(data)*3//4),len(data))]^=1<<rng.randrange(8)
            elif mode==2:data.extend(rng.randbytes(32))
            else:
                offset=rng.randrange(max(41,len(data)*3//4),len(data))
                data[offset:]=b'\0'*(len(data)-offset)
            path=suite.output/f'mutant-{number:03}{source.suffix}'
            path.write_bytes(data)
            old=len(t.s.events(view.log,'image'))+len(t.s.events(view.log,'error'))
            t.s.drop_file(view.hwnd,path)
            def result_ready():
                assert view.process.poll() is None,f'Viewer exited on {path.name}'
                return len(t.s.events(view.log,'image'))+len(t.s.events(view.log,'error'))>old
            t.s.wait(result_ready,f'malformed result {number}',8)
            row=[r for r in t.s.rows(view.log) if r['event'] in ('image','error')][-1]
            if row['event']=='error':rejected+=1
            else:
                accepted+=1
                assert 0<int(row['width'])<=8192 and 0<int(row['height'])<=8192
                assert int(row['width'])*int(row['height'])<=32_000_000
            samples.append({'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),'outcome':row['event']})
            if number%25==0:
                assert t.resources(view.process)['rss']<512*1024**2,'small-image workload exceeded 512 MiB guard'
                print(f'MALFORMED {number+1}/{options.samples}',flush=True)
        view.drop(suite.assets/'photo1.png');t.center_color(view.hwnd,suite.red)
        view.drop(t.ROOT/'artifacts/photos/photo1.jpg')
        t.s.command(view.hwnd,104)
        probe=subprocess.run([str((t.ROOT/'target/release/examples/uia_probe.exe').resolve()),
                              str(view.hwnd),'--invoke-fit'],
                             capture_output=True,text=True,timeout=30)
        (suite.output/'accessibility.txt').write_text(probe.stdout+'\n'+probe.stderr,encoding='utf-8')
        assert probe.returncode==0 and 'FOTO_UIA_PASS' in probe.stdout,(probe.returncode,probe.stderr)
        t.s.pixel_corners(view.hwnd)
        assert not t.s.events(view.log,'graphics_error')
        assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in originals.items())
        after=t.resources(view.process)
        report={'verdict':'PASS','exe_sha256':hashlib.sha256(suite.exe.read_bytes()).hexdigest(),
                'seed':1847,'samples':options.samples,'decoded_or_partially_decoded':accepted,'rejected':rejected,
                'seconds':round(time.monotonic()-started,2),'resources_before':before,'resources_after':after,
                'accessibility':'eight named native buttons with Invoke and enabled keyboard-focus support',
                'pixel_oracle':'PrintWindow client pixels','input_records':samples,
                'limits':'Small dimension-preserving JPEG/PNG mutations; not security certification or human UAT'}
        (suite.output/'malformed-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='input_records'},indent=2))
        print('REPORT',suite.output/'malformed-report.json')
        print('FOTO_MALFORMED_PASS')
    finally:view.close()


if __name__=='__main__':main()
