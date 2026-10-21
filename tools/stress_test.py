# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded native-window journey and stress tests. Synthetic files only; requires Pillow.

Run against baselines/v1.0.0/foto.exe before repairs, then dist/foto.exe afterwards.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import random
import platform
import subprocess
import sys
import time
from PIL import Image
import smoke_test as s

ROOT = s.ROOT
get_thread_info = s.api(s.user, "GetGUIThreadInfo", W.BOOL, W.DWORD, C.c_void_p)
show = s.api(s.user, "ShowWindow", W.BOOL, W.HWND, C.c_int)
zoomed = s.api(s.user, "IsZoomed", W.BOOL, W.HWND)
iconic = s.api(s.user, "IsIconic", W.BOOL, W.HWND)
monitor_from_window = s.api(s.user, "MonitorFromWindow", W.HANDLE, W.HWND, W.DWORD)
monitor_info = s.api(s.user, "GetMonitorInfoW", W.BOOL, W.HANDLE, C.c_void_p)
get_handles = s.api(s.kernel, "GetProcessHandleCount", W.BOOL, W.HANDLE, C.POINTER(W.DWORD))
get_gui = s.api(s.user, "GetGuiResources", W.DWORD, W.HANDLE, W.DWORD)
get_memory = s.api(s.kernel, "K32GetProcessMemoryInfo", W.BOOL, W.HANDLE, C.c_void_p, W.DWORD)
set_foreground = s.api(s.user, "SetForegroundWindow", W.BOOL, W.HWND)


class ThreadInfo(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD)] + [(n, W.HWND) for n in
        ["active", "focus", "capture", "menuOwner", "moveSize", "caret"]] + [("caretRect", W.RECT)]


class MonitorInfo(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


class MemoryInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("faults", W.DWORD)] + [(name, C.c_size_t) for name in
        ["peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private"]]


def rect(hwnd, client=False):
    r = W.RECT()
    assert (s.get_rect if client else s.get_window_rect)(hwnd, C.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def focus(hwnd):
    info = ThreadInfo(C.sizeof(ThreadInfo))
    thread = s.get_pid(hwnd, None)
    assert get_thread_info(thread, C.byref(info))
    return info.focus


def resources(process):
    memory = MemoryInfo(C.sizeof(MemoryInfo))
    assert get_memory(process._handle, C.byref(memory), C.sizeof(memory))
    handles = W.DWORD()
    assert get_handles(process._handle, C.byref(handles))
    return {"rss": memory.ws, "private": memory.private, "peak_rss": memory.peak_ws,
            "handles": handles.value, "gdi": get_gui(process._handle, 0), "user": get_gui(process._handle, 1)}


def pixel(hwnd, x, y):
    with s.client_dc(hwnd) as (dc, _, _):
        value = s.get_pixel(dc, round(x), round(y))
        assert value != 0xFFFFFFFF, "Screen pixel unavailable"
        return (value & 255, value >> 8 & 255, value >> 16 & 255)


def center_color(hwnd, target):
    _, _, w, h = rect(hwnd, True)
    dpi = s.get_dpi(hwnd) / 96
    def matches():
        actual = pixel(hwnd, math.floor(w/2), math.floor((52*dpi+h-34*dpi)/2))
        return all(abs(a-b)<5 for a,b in zip(actual,target))
    s.wait(matches,f"native window center pixel {target}",3)


def packed(x, y):
    return (round(x) & 0xFFFF) | ((round(y) & 0xFFFF) << 16)


class Session:
    def __init__(self, suite, name, path=None):
        self.suite = suite
        self.log = suite.output / f"{name}-{suite.serial}.csv"
        suite.serial += 1
        self.process, self.hwnd, _ = s.launch(suite.exe, path, self.log)
        assert s.set_pos(self.hwnd,None,40,40,1100,780,0x14)
        suite.sessions.append(self)
        if path: self.ready(path)

    def ready(self, path):
        s.wait(lambda: s.text(self.hwnd) == f"{path.name} — Foto", f"loaded title {path.name}", 15)
        s.wait(lambda: s.events(self.log, "image") or s.events(self.log, "error"), "decode result", 15)
        assert not s.events(self.log, "graphics_error"), "drawing error"
        time.sleep(.035)

    def drop(self, path, error=False):
        before = len(s.events(self.log, "image")) + len(s.events(self.log, "error"))
        s.drop_file(self.hwnd, path)
        s.wait(lambda: len(s.events(self.log,"image"))+len(s.events(self.log,"error")) > before,
               f"drop decode: {path.name}", 15)
        self.ready(path)
        last = [r for r in s.rows(self.log) if r["event"] in ("image", "error")][-1]
        assert (last["event"] == "error") == error, (path.name, last)

    def close(self):
        if self.process.poll() is None:s.close(self.process, self.hwnd)
        if self in self.suite.sessions:self.suite.sessions.remove(self)


class Suite:
    def __init__(self, options):
        self.exe = options.exe.resolve()
        self.options = options
        self.output = ROOT / "artifacts/hardening" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        self.output.mkdir(parents=True)
        self.serial = 0
        self.results = []
        self.sessions = []
        self.metrics = {}
        self.assets = self.output / "assets"
        self.assets.mkdir()
        self.red, self.green, self.blue = [(240, 20, 30), (20, 230, 40), (30, 40, 240)]
        for i, color in enumerate([self.red, self.green, self.blue]):
            Image.new("RGB", (1600, 1200), color).save(self.assets/f"photo{i+1}.png")
        self.original_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (ROOT/'tests/fixtures').iterdir() if p.is_file()}

    def case(self, name, function):
        started = time.monotonic()
        try:
            function()
            result = {"id": name, "verdict": "PASS"}
        except Exception as error:
            result = {"id": name, "verdict": "FAIL", "error": f"{type(error).__name__}: {error}"}
        finally:
            for session in list(self.sessions):session.close()
        result["seconds"] = round(time.monotonic()-started, 3)
        self.results.append(result)
        self.save()
        print(json.dumps(result, ensure_ascii=True), flush=True)

    def save(self):
        report = {"exe": str(self.exe), "exe_sha256": hashlib.sha256(self.exe.read_bytes()).hexdigest(),
                  "seed": 1701, "options": vars(self.options) | {"exe": str(self.options.exe)},
                  "results": self.results, "metrics": self.metrics,
                  "limits": ["agent-operated journeys; human UAT not performed", "Host: "+platform.platform()+"; Windows 10 not independently tested",
                             "DPI changes are simulated on current monitor", "no installed codec changes"]}
        (self.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

    def j01(self):
        view = Session(self, 'first-use')
        try:
            assert not s.enabled(s.get_item(view.hwnd,103))
            selected = self.output/'café 猫 with spaces.png'
            selected.write_bytes((self.assets/'photo1.png').read_bytes())
            view.drop(selected)
            center_color(view.hwnd,self.red)
            s.command(view.hwnd,100)
            dialog = s.wait(lambda:s.windows(view.process.pid,'#32770'),'picker')[0]
            s.post(dialog,0x10,0,0)
            s.wait(lambda:not s.windows(view.process.pid,'#32770'),'picker closed')
            for _ in range(8): view.drop(selected)
            center_color(view.hwnd,self.red)
            long_path=self.output/'long'/('a'*90)/('b'*90)/('c'*90)/'photo.png'
            extended=Path('\\\\?\\'+str(long_path))
            extended.parent.mkdir(parents=True)
            extended.write_bytes((self.assets/'photo1.png').read_bytes())
            assert len(str(long_path))>260
            view.drop(long_path)
            center_color(view.hwnd,self.red)
        finally:view.close()

    def j02(self):
        folder = self.output/'case-and-order';folder.mkdir()
        for name, color in [('photo1.png',self.red),('photo2.png',self.green),('photo10.png',self.blue)]:
            Image.new('RGB',(400,300),color).save(folder/name)
        (folder/'ignore.txt').write_text('not an image')
        (folder/'directory.png').mkdir()
        view=Session(self,'case',folder/'PHOTO1.PNG')
        try:
            s.wait(lambda:s.enabled(s.get_item(view.hwnd,102)),'folder indexed')
            center_color(view.hwnd,self.red)
            s.key(view.hwnd,0x27)
            s.wait(lambda:s.text(view.hwnd)=='photo2.png — Foto','case-insensitive selection has no duplicate')
            time.sleep(.05);center_color(view.hwnd,self.green)
            s.key(view.hwnd,0x23)
            s.wait(lambda:s.text(view.hwnd)=='photo10.png — Foto','numeric last item')
            time.sleep(.05);center_color(view.hwnd,self.blue)
        finally:view.close()

    def j03(self):
        view=Session(self,'geometry',ROOT/'artifacts/photos/photo1.jpg')
        try:
            s.pixel_corners(view.hwnd)
            s.command(view.hwnd,104);time.sleep(.06)
            _,_,w,h=rect(view.hwnd,True)
            before=pixel(view.hwnd,w/2,h/2)
            s.post(view.hwnd,0x201,1,packed(w/2,h/2))
            s.post(view.hwnd,0x200,1,packed(w/2,h/2+700))
            s.post(view.hwnd,0x202,0,packed(w/2,h/2+700))
            time.sleep(.08)
            after=pixel(view.hwnd,w/2,h/2)
            assert before!=after,('pan did not change pixels',before,after)
            s.command(view.hwnd,103);time.sleep(.05);s.pixel_corners(view.hwnd)
            for _ in range(4):s.key(view.hwnd,0x52)
            time.sleep(.08);s.pixel_corners(view.hwnd)
            _,_,w,h=rect(view.hwnd,True)
            p=W.POINT(w//2,h//2);s.to_screen(view.hwnd,C.byref(p))
            for _ in range(15):s.post(view.hwnd,0x20a,120<<16,packed(p.x,p.y))
            s.command(view.hwnd,103);time.sleep(.1);s.pixel_corners(view.hwnd)
        finally:view.close()

    def j04(self):
        view=Session(self,'window',self.assets/'photo1.png')
        try:
            original=rect(view.hwnd)
            show(view.hwnd,3)
            s.wait(lambda:zoomed(view.hwnd),'maximised')
            info=MonitorInfo(C.sizeof(MonitorInfo))
            assert monitor_info(monitor_from_window(view.hwnd,2),C.byref(info))
            expected=tuple(getattr(info.monitor,n) for n in ['left','top','right','bottom'])
            s.key(view.hwnd,0x7a)
            s.wait(lambda:s.get_style(view.hwnd,-16)&0xc00000==0,'full screen')
            assert rect(view.hwnd)==expected,('full screen bounds',rect(view.hwnd),expected)
            s.key(view.hwnd,0x1b)
            s.wait(lambda:zoomed(view.hwnd),'restored maximised state')
            show(view.hwnd,9);time.sleep(.1)
            assert rect(view.hwnd)==original,('normal placement changed',rect(view.hwnd),original)
            # A held toggle key should not alternate full screen on repeat messages.
            s.key(view.hwnd,0x7a)
            s.wait(lambda:s.get_style(view.hwnd,-16)&0xc00000==0,'first F11')
            s.post(view.hwnd,0x100,0x7a,1|(1<<30));time.sleep(.05)
            assert s.get_style(view.hwnd,-16)&0xc00000==0,'held F11 toggled full screen back off'
            s.key(view.hwnd,0x1b)
            s.wait(lambda:s.get_style(view.hwnd,-16)&0xc00000!=0,'full screen exit')
            show(view.hwnd,6);s.wait(lambda:iconic(view.hwnd),'minimised')
            s.drop_file(view.hwnd,self.assets/'photo2.png')
            s.wait(lambda:s.text(view.hwnd)=='photo2.png — Foto','decode while minimised')
            show(view.hwnd,9);time.sleep(.1);center_color(view.hwnd,self.green)
        finally:view.close()

    def j05(self):
        view=Session(self,'rapid',self.assets/'photo1.png')
        try:
            s.wait(lambda:s.enabled(s.get_item(view.hwnd,102)),'indexed')
            rng=random.Random(1701)
            count=self.options.actions
            for _ in range(count):s.key(view.hwnd,rng.choice([0x25,0x27,0x24,0x23]))
            s.key(view.hwnd,0x23)
            s.wait(lambda:s.text(view.hwnd)=='photo3.png — Foto','latest key wins',20)
            time.sleep(.3);center_color(view.hwnd,self.blue)
            for _ in range(30):s.drop_file(view.hwnd,self.assets/f'photo{rng.randint(1,3)}.png')
            s.drop_file(view.hwnd,self.assets/'photo2.png')
            s.wait(lambda:s.text(view.hwnd)=='photo2.png — Foto','latest drop wins',20)
            time.sleep(.1);center_color(view.hwnd,self.green)
            self.metrics['rapid_navigation_messages']=count
        finally:view.close()

    def j06(self):
        view=Session(self,'errors',self.assets/'photo1.png')
        try:
            bad=self.output/'truncated.png';bad.write_bytes((self.assets/'photo1.png').read_bytes()[:40])
            for path in [bad,self.output/'missing.jpg',ROOT/'tests/fixtures/broken.jpg']:
                view.drop(path,error=True)
                view.drop(self.assets/'photo1.png');center_color(view.hwnd,self.red)
            edited=self.output/'edited.png'
            edited.write_bytes((self.assets/'photo1.png').read_bytes());view.drop(edited)
            edited.write_bytes((self.assets/'photo3.png').read_bytes());view.drop(edited)
            center_color(view.hwnd,self.blue)
            renamed=self.output/'renamed.png';edited.rename(renamed)
            view.drop(edited,error=True);view.drop(renamed);center_color(view.hwnd,self.blue)
            empty=self.output/'zero.png';empty.write_bytes(b'')
            view.drop(empty,error=True)
            disguised=self.output/'image.data';disguised.write_bytes((self.assets/'photo1.png').read_bytes())
            view.drop(disguised);center_color(view.hwnd,self.red)
            locked=self.output/'locked.png';locked.write_bytes((self.assets/'photo1.png').read_bytes())
            create=s.api(s.kernel,'CreateFileW',W.HANDLE,W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE)
            release=s.api(s.kernel,'CloseHandle',W.BOOL,W.HANDLE)
            handle=create(str(locked),0x80000000,0,None,3,0x80,None)
            assert handle and handle!=C.c_void_p(-1).value
            try:view.drop(locked,error=True)
            finally:assert release(handle)
            view.drop(locked);center_color(view.hwnd,self.red)
        finally:view.close()

    def j07(self):
        view=Session(self,'formats')
        try:
            for name in ['colors.png','colors.bmp','colors.tiff','colors.ico','animated.gif',
                         'alpha.png','wide.png']+[f'orientation-{i}.jpg' for i in range(1,9)]:
                view.drop(ROOT/'tests/fixtures'/name)
            view.drop(ROOT/'tests/fixtures/alpha.png')
            center_color(view.hwnd,(108,59,35))
            big=self.output/'large.png'
            Image.new('RGB',(9000,4000),self.green).save(big)
            view.drop(big)
            row=s.events(view.log,'image')[-1]
            assert int(row['width'])<=8192 and int(row['width'])*int(row['height'])<=32_000_000
            center_color(view.hwnd,self.green)
        finally:view.close()

    def j08(self):
        folder=self.output/'large-folder';folder.mkdir()
        for i in range(self.options.folder_entries):(folder/f'shot{i:05}.png').write_bytes(b'bad')
        first=folder/'shot00000.png';last=folder/f'shot{self.options.folder_entries-1:05}.png'
        first.write_bytes((self.assets/'photo1.png').read_bytes());last.write_bytes((self.assets/'photo3.png').read_bytes())
        started=time.monotonic();view=Session(self,'directory',first)
        try:
            center_color(view.hwnd,self.red)
            s.wait(lambda:s.enabled(s.get_item(view.hwnd,102)),'large directory indexed',20)
            self.metrics['directory_entries']=self.options.folder_entries
            self.metrics['directory_first_load_and_index_ms']=round((time.monotonic()-started)*1000,2)
            s.key(view.hwnd,0x23)
            s.wait(lambda:s.text(view.hwnd)==f'{last.name} — Foto','last large-folder image',20)
            time.sleep(.08);center_color(view.hwnd,self.blue)
            for _ in range(10):s.drop_file(view.hwnd,first)
            s.drop_file(view.hwnd,self.assets/'photo2.png')
            s.wait(lambda:s.text(view.hwnd)=='photo2.png — Foto','new folder supersedes scans',20)
            time.sleep(.1);center_color(view.hwnd,self.green)
        finally:view.close()

    def j09(self):
        starts=[]
        for n in range(self.options.cycles):
            started=time.monotonic();view=Session(self,f'cycle{n}',self.assets/'photo1.png')
            center_color(view.hwnd,self.red);view.close();starts.append((time.monotonic()-started)*1000)
        self.metrics['open_close_cycles']=len(starts)
        view=Session(self,'soak',ROOT/'artifacts/photos/photo1.jpg')
        try:
            s.wait(lambda:s.enabled(s.get_item(view.hwnd,102)),'soak folder indexed')
            for _ in range(8):
                s.key(view.hwnd,0x23);time.sleep(.1);s.key(view.hwnd,0x24);time.sleep(.1)
            time.sleep(.5)
            base=resources(view.process);samples=[];deadline=time.monotonic()+self.options.soak_seconds
            n=0;next_sample=time.monotonic()
            while time.monotonic()<deadline:
                s.key(view.hwnd,[0x27,0x25,0x23,0x24][n%4])
                if n%7==0:s.key(view.hwnd,0x52)
                if n%11==0:s.command(view.hwnd,103)
                if n%23==0:s.set_pos(view.hwnd,None,40,40,900+(n%3)*60,650,0x14)
                time.sleep(.05);n+=1
                if time.monotonic()>=next_sample:
                    sample=resources(view.process);samples.append(sample)
                    assert sample['rss'] < 1024**3,'soak guard: process exceeded 1 GiB working set'
                    next_sample=time.monotonic()+5
                    print(f'SOAK {n} actions; RSS {sample["rss"]//1024**2} MiB; GDI {sample["gdi"]}; handles {sample["handles"]}',flush=True)
            s.key(view.hwnd,0x24)
            s.wait(lambda:s.text(view.hwnd)=='photo1.jpg — Foto','soak final selection',20)
            s.command(view.hwnd,103);time.sleep(.5)
            # Navigation resets rotation; if the last action was already first, reset by visiting last.
            last_presented = len(s.events(view.log,'image'))
            s.key(view.hwnd,0x23);s.wait(lambda:s.text(view.hwnd)=='photo10.jpg — Foto','soak last')
            s.wait(lambda:len(s.events(view.log,'image'))>last_presented,'soak last image presentation',20)
            presented = len(s.events(view.log,'image'))
            s.key(view.hwnd,0x24);s.wait(lambda:s.text(view.hwnd)=='photo1.jpg — Foto','soak first')
            # A title changes when selection starts, before an uncached decode and paint.
            s.wait(lambda:len(s.events(view.log,'image'))>presented,'soak final image presentation',20)
            s.pixel_corners(view.hwnd)
            time.sleep(1);final=resources(view.process)
            assert final['gdi']<=base['gdi']+4,('GDI growth',base,final)
            assert final['user']<=base['user']+4,('USER growth',base,final)
            assert final['handles']<=base['handles']+12,('handle growth',base,final)
            assert not s.events(view.log,'graphics_error') and not s.events(view.log,'error')
            before=s.cpu_ms(view.process);time.sleep(1);idle=s.cpu_ms(view.process)-before
            assert idle<=50,('idle CPU ms',idle)
            self.metrics['soak']={'duration_s':self.options.soak_seconds,'actions':n,'baseline':base,
                                  'final':final,'samples':samples,'idle_cpu_ms_over_one_second':idle}
        finally:view.close()

    def j10(self):
        view=Session(self,'keyboard',self.assets/'photo1.png')
        try:
            s.wait(lambda:s.enabled(s.get_item(view.hwnd,102)),'keyboard folder')
            set_foreground(view.hwnd)
            for _ in range(12):
                if focus(view.hwnd)==s.get_item(view.hwnd,102):break
                s.key(focus(view.hwnd) or view.hwnd,9);time.sleep(.03)
            assert focus(view.hwnd)==s.get_item(view.hwnd,102),'Tab cannot reach Next'
            s.key(s.get_item(view.hwnd,102),13)
            s.wait(lambda:s.text(view.hwnd)=='photo2.png — Foto','Enter activates focused Next')
            time.sleep(.05);center_color(view.hwnd,self.green)
            assert all(s.text(s.get_item(view.hwnd,i)) for i in range(100,108))
        finally:view.close()

    def j11(self):
        view=Session(self,'dpi',self.assets/'photo1.png')
        try:
            base=resources(view.process)
            for dpi in [120,144,192,96]*5:
                scale=dpi/96;area=W.RECT(20,20,20+min(round(800*scale),1024),20+round(550*scale))
                s.send(view.hwnd,0x2e0,dpi|(dpi<<16),C.addressof(area))
                # Match a compact desktop even when this test host has a large monitor.
                # Skip WM_WINDOWPOSCHANGING so the old single-row minimum cannot hide clipping.
                assert s.set_pos(view.hwnd,None,area.left,area.top,area.right-area.left,area.bottom-area.top,0x414)
                time.sleep(.03)
                _,_,w,h=rect(view.hwnd,True)
                for i in range(100,108):
                    br=rect(s.get_item(view.hwnd,i));wr=rect(view.hwnd)
                    assert br[0]>=wr[0] and br[2]<=wr[2] and br[1]>=wr[1] and br[3]<=wr[3],('toolbar clipped',dpi,i,br,wr)
            s.send(view.hwnd,0x7e,32,packed(1920,1080))
            s.send(view.hwnd,0x31a,0,0)
            time.sleep(.1);center_color(view.hwnd,self.red)
            final=resources(view.process)
            assert final['gdi']<=base['gdi']+2,('DPI font leak',base,final)
            self.metrics['dpi_simulation']={'messages':20,'baseline_gdi':base['gdi'],'final_gdi':final['gdi']}
        finally:view.close()

    def j12(self):
        result=subprocess.run([sys.executable,str(ROOT/'tools/check_portable.py'),str(self.exe)],capture_output=True,text=True)
        assert result.returncode==0 and 'PORTABLE_DEPENDENCIES_PASS' in result.stdout
        assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in self.original_hashes.items())
        # The baseline's existing-output protection is independently exercised by smoke_test.py.
        self.metrics['fixture_integrity_files']=len(self.original_hashes)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,default=ROOT/'dist/foto.exe')
    parser.add_argument('--only',default='')
    parser.add_argument('--soak-seconds',type=int,default=120)
    parser.add_argument('--actions',type=int,default=2000)
    parser.add_argument('--cycles',type=int,default=30)
    parser.add_argument('--folder-entries',type=int,default=10000)
    options=parser.parse_args()
    assert 0<options.soak_seconds<=600 and 0<options.actions<=8000 and 0<options.cycles<=100
    assert 3<=options.folder_entries<=50000
    suite=Suite(options)
    selected=set(options.only.split(',')) if options.only else {f'J{i:02}' for i in range(1,13)}
    assert selected and selected<={f'J{i:02}' for i in range(1,13)},'Unknown journey ID'
    for i in range(1,13):
        name=f'J{i:02}'
        if name in selected:suite.case(name,getattr(suite,f'j{i:02}'))
    print('REPORT',suite.output/'report.json',flush=True)
    assert not any(r['verdict']!='PASS' for r in suite.results),'Journey failures are recorded in the report'
    print('FOTO_STRESS_PASS',flush=True)


if __name__=='__main__':main()
