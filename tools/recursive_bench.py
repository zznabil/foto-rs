"""Paired warm-cache native-window workloads; raw samples, not a speedup verdict."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics as st
import time
from PIL import Image, ImageDraw
import stress_test as t


def percentiles(values):
    """Nearest-rank tails; always retain N and max so small samples stay visible."""
    assert values and all(math.isfinite(v) and v >= 0 for v in values)
    ordered = sorted(values)
    return {'n': len(values), 'median': st.median(values),
            'p95': ordered[math.ceil(.95 * len(values)) - 1],
            'p99': ordered[math.ceil(.99 * len(values)) - 1], 'max': ordered[-1]}


def self_test():
    assert percentiles(list(range(1, 101))) == {
        'n': 100, 'median': 50.5, 'p95': 95, 'p99': 99, 'max': 100}
    assert percentiles([7])['p99'] == 7
    for bad in ([], [float('nan')], [-1]):
        try:
            percentiles(bad)
        except AssertionError:
            pass
        else:
            raise AssertionError(f'accepted invalid samples: {bad}')
    print('RECURSIVE_BENCH_SELF_TEST_PASS')


def assets(output):
    folder = output / 'pressure'
    folder.mkdir()
    # More large images than the decoded cache can hold, with distinct pixel oracles.
    colors = [(230, 20, 30), (20, 220, 40), (30, 40, 230),
              (230, 220, 30), (220, 30, 220), (30, 220, 220), (180, 100, 40)]
    for i, color in enumerate(colors):
        Image.new('RGB', (6000, 4000), color).save(folder / f'photo{i+1}.jpg', quality=94)
    oriented = output / 'oriented'
    oriented.mkdir()
    large = Image.new('RGB', (9000, 4000))
    draw = ImageDraw.Draw(large)
    for box, color in [((0,0,4499,1999),'red'),((4500,0,8999,1999),(0,255,0)),
                       ((0,2000,4499,3999),'blue'),((4500,2000,8999,3999),'yellow')]:
        draw.rectangle(box, fill=color)
    for orientation in range(1,9):
        exif = Image.Exif(); exif[274] = orientation
        large.save(oriented/f'orientation-{orientation}.jpg', quality=94, exif=exif)
    single=oriented/'single';single.mkdir()
    (single/'orientation-6.jpg').write_bytes((oriented/'orientation-6.jpg').read_bytes())
    return folder, colors


def identity_pixel(hwnd, path):
    # Shared corner markers cannot detect a stale image with the current title.
    with Image.open(path) as image:
        target = image.convert('RGB').getpixel((2000, 1600))
    _,_,w,h = t.rect(hwnd, True)
    dpi = t.s.get_dpi(hwnd)/96
    scale = min(w/6000, (h-86*dpi)/4000, 1)
    left, top = (w-6000*scale)/2, 52*dpi+(h-86*dpi-4000*scale)/2
    actual = t.pixel(hwnd, left+2000*scale, top+1600*scale)
    assert all(abs(a-b)<8 for a,b in zip(actual,target)), ('stale image pixels',path.name,actual,target)


def decode_sample(exe, output, label):
    log = output/f'{label}.csv'
    path = output/'oriented/single/orientation-6.jpg'
    process, hwnd, started = t.s.launch(exe,path,log)
    try:
        row = t.s.wait(lambda:t.s.events(log,'image'),'oversized oriented draw',20)[0]
        external = (time.perf_counter()-started)*1000
        # 9000x4000 rotated to 4000x9000, then bounded to the same aspect/limits.
        assert (int(row['width']),int(row['height'])) == (3640,8192),row
        assert t.s.enabled(t.s.get_item(hwnd,103))
        time.sleep(.4)
        _,_,w,h = t.rect(hwnd,True); dpi=t.s.get_dpi(hwnd)/96
        scale=min(w/3640,(h-86*dpi)/8192)
        left,top=(w-3640*scale)/2,52*dpi+(h-86*dpi-8192*scale)/2
        for (x,y),target in zip([(.25,.25),(.75,.25),(.25,.75),(.75,.75)],
                                [(0,0,255),(255,0,0),(255,255,0),(0,255,0)]):
            actual=t.pixel(hwnd,left+x*3640*scale,top+y*8192*scale)
            assert all(abs(a-b)<8 for a,b in zip(actual,target)),(actual,target)
        final=t.resources(process)
        cpu=t.s.cpu_ms(process)
        assert not t.s.events(log,'error') and not t.s.events(log,'graphics_error')
        return {'first_ms':float(row['elapsed_ms']),'external_ms':external,
                'cpu_ms':cpu,'final':final}
    finally:t.s.close(process,hwnd)


def icon_sample(exe, output, label):
    log=output/f'{label}.csv';path=t.ROOT/'tests/fixtures/colors.ico'
    process,hwnd,started=t.s.launch(exe,path,log)
    try:
        row=t.s.wait(lambda:t.s.events(log,'image'),'icon draw')[0]
        external=(time.perf_counter()-started)*1000
        values=[];before=t.s.cpu_ms(process)
        for _ in range(40):
            count=len(t.s.events(log,'image'));t.s.drop_file(hwnd,path)
            t.s.wait(lambda:len(t.s.events(log,'image'))>count,'icon reopen')
            values.append(float(t.s.events(log,'image')[-1]['request_ms']))
        assert not t.s.events(log,'error') and not t.s.events(log,'graphics_error')
        return {'first_ms':float(row['elapsed_ms']),'external_ms':external,
                'cpu_ms':t.s.cpu_ms(process)-before,'final':t.resources(process),'reopen_ms':values}
    finally:t.s.close(process,hwnd)


def directory_sample(exe, output, label):
    folder=output/'directory'
    log=output/f'{label}.csv'
    process,hwnd,started=t.s.launch(exe,folder/'shot00000.png',log)
    try:
        row=t.s.wait(lambda:t.s.events(log,'image'),'directory first draw')[0]
        external=(time.perf_counter()-started)*1000
        t.s.wait(lambda:t.s.enabled(t.s.get_item(hwnd,102)),'10000 entries indexed',20)
        indexed=(time.perf_counter()-started)*1000
        cpu=t.s.cpu_ms(process)
        t.s.key(hwnd,0x23)
        t.s.wait(lambda:t.s.text(hwnd)=='shot09999.png — Foto','large directory last')
        t.center_color(hwnd,(20,220,40))
        assert not t.s.events(log,'error') and not t.s.events(log,'graphics_error')
        return {'first_ms':float(row['elapsed_ms']),'external_ms':external,
                'cpu_ms':cpu,'index_ms':indexed,'final':t.resources(process)}
    finally:t.s.close(process,hwnd)


def sample(exe, output, label, workload, pressure, colors):
    path = (pressure if workload == 'pressure' else t.ROOT / 'artifacts/photos') / 'photo1.jpg'
    log = output / f'{label}.csv'
    process, hwnd, started = t.s.launch(exe, path, log)
    try:
        first = t.s.wait(lambda: t.s.events(log, 'image'), 'first draw')[0]
        external = (time.perf_counter() - started) * 1000
        t.s.wait(lambda: t.s.enabled(t.s.get_item(hwnd, 102)), 'directory ready')
        assert t.s.set_pos(hwnd, None, 40, 40, 1100, 780, 0x14)
        time.sleep(.6)
        baseline = t.resources(process)
        cpu = t.s.cpu_ms(process)
        navigation, interaction = [], []
        position = 0
        sequence = ([1, 2, 1, 0] * 6 if workload == 'browse'
                    else (list(range(1, 7)) + list(range(5, -1, -1)))*2)
        for index in sequence:
            count = len(t.s.events(log, 'image'))
            sent = time.perf_counter()
            t.s.key(hwnd, 0x27 if index > position else 0x25)
            t.s.wait(lambda: len(t.s.events(log, 'image')) > count, 'navigation presentation')
            observed = (time.perf_counter() - sent) * 1000
            row = t.s.events(log, 'image')[-1]
            name = f'photo{index+1}.jpg' if workload == 'pressure' else ['photo1.jpg', 'photo2.jpg', 'photo10.jpg'][index]
            assert t.s.text(hwnd) == name + ' — Foto'
            assert (int(row['width']), int(row['height'])) == (6000, 4000)
            navigation.append({'ms': float(row['request_ms']), 'observed_ms': observed,
                               'cached': row['cached'] == 'true', 'file': name})
            # Pixel capture forces a draw, so perform it AFTER the timed successful draw.
            if workload == 'pressure':
                t.center_color(hwnd, colors[index])
            else:
                t.s.pixel_corners(hwnd)
                identity_pixel(hwnd, path.parent/name)
            position = index
            time.sleep(.2 if workload == 'browse' else .02)
        nav_cpu = t.s.cpu_ms(process) - cpu
        # Synchronous native commands + WM_PAINT, not compositor or physical-input latency.
        update = t.s.api(t.s.user, 'UpdateWindow', t.W.BOOL, t.W.HWND)
        cpu = t.s.cpu_ms(process)
        for command in [104, 108, 109, 105, 103] * 8:
            sent = time.perf_counter()
            t.s.send(hwnd, 0x111, command, 0)
            assert update(hwnd)
            interaction.append((time.perf_counter() - sent) * 1000)
        ui_cpu = t.s.cpu_ms(process) - cpu
        t.s.send(hwnd, 0x111, 103, 0)
        time.sleep(.3)
        if workload == 'pressure':
            t.center_color(hwnd, colors[0])
        else:
            t.s.pixel_corners(hwnd)
        final = t.resources(process)
        before = t.s.cpu_ms(process)
        time.sleep(.3)
        idle = t.s.cpu_ms(process) - before
        assert idle <= 50
        assert final['rss'] < 1024**3
        assert final['gdi'] <= baseline['gdi'] + 4
        assert final['user'] <= baseline['user'] + 4
        assert final['handles'] <= baseline['handles'] + 12
        assert not t.s.events(log, 'error') and not t.s.events(log, 'graphics_error')
        return {'first_ms': float(first['elapsed_ms']), 'external_ms': external,
                'navigation': navigation, 'interaction_ms': interaction,
                'nav_cpu_ms': nav_cpu, 'ui_cpu_ms': ui_cpu, 'idle_cpu_ms': idle,
                'baseline': baseline, 'final': final}
    finally:
        t.s.close(process, hwnd)


def summarize(rows):
    if 'navigation' not in rows[0]:
        return ({'first_ms':percentiles([r['first_ms'] for r in rows]),
                'external_ms':percentiles([r['external_ms'] for r in rows]),
                'cpu_ms':st.median(r['cpu_ms'] for r in rows),
                'resources':{key:st.median(r['final'][key] for r in rows)
                             for key in ['rss','private','peak_rss','handles','gdi','user']}} |
                ({'reopen_ms':percentiles([v for r in rows for v in r['reopen_ms']])}
                 if 'reopen_ms' in rows[0] else {}) |
                ({'index_ms':percentiles([r['index_ms'] for r in rows])}
                 if 'index_ms' in rows[0] else {}))
    return {'first_ms': percentiles([r['first_ms'] for r in rows]),
            'external_ms': percentiles([r['external_ms'] for r in rows]),
            'navigation_ms': percentiles([n['ms'] for r in rows for n in r['navigation']]),
            'observed_navigation_ms': percentiles([n['observed_ms'] for r in rows for n in r['navigation']]),
            'interaction_ms': percentiles([n for r in rows for n in r['interaction_ms']]),
            'cache_hits': sum(n['cached'] for r in rows for n in r['navigation']),
            'nav_cpu_ms': st.median(r['nav_cpu_ms'] for r in rows),
            'ui_cpu_ms': st.median(r['ui_cpu_ms'] for r in rows),
            'idle_cpu_ms': max(r['idle_cpu_ms'] for r in rows),
            'resources': {key: st.median(r['final'][key] for r in rows)
                          for key in ['rss', 'private', 'peak_rss', 'handles', 'gdi', 'user']}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--control', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--pairs', type=int, default=4)
    parser.add_argument('--label')
    parser.add_argument('--workloads',default='browse,pressure,oriented')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    assert args.control and args.candidate and args.label and 2 <= args.pairs <= 20
    workloads=args.workloads.split(',')
    assert workloads and len(workloads)==len(set(workloads)) and set(workloads)<={'browse','pressure','oriented','icon','directory'}
    output = t.ROOT / 'artifacts/recursive' / f'{time.time_ns()}-{args.label}'
    output.mkdir(parents=True)
    pressure, colors = assets(output)
    if 'directory' in workloads:
        folder=output/'directory';folder.mkdir()
        for i in range(10000):(folder/f'shot{i:05}.png').write_bytes(b'bad')
        for name,color in [('shot00000.png',(230,20,30)),('shot09999.png',(20,220,40))]:
            Image.new('RGB',(400,300),color).save(folder/name)
    executables = {'control': args.control.resolve(), 'candidate': args.candidate.resolve()}
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in executables.items()}
    fixtures = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in [pressure, output/'oriented', output/'oriented/single',
                               t.ROOT/'artifacts/photos', t.ROOT/'tests/fixtures'] +
                              ([output/'directory'] if 'directory' in workloads else [])
                for p in folder.iterdir() if p.is_file()}
    report = {'label': args.label, 'hashes': hashes, 'pairs': args.pairs, 'workloads':workloads,'samples': [],
              'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'method': 'Serial alternating AB/BA per workload; warm OS cache; pooled nearest-rank p95/p99; raw per-process rows retained',
              'limits': 'Single Windows 11 machine; synthetic local images; UI timing is synchronous command through paint, not compositor; launch tails have small N; navigation samples within a process are correlated; no human UAT'}
    for pair in range(args.pairs):
        for workload in workloads:
            for kind in (['control', 'candidate'] if pair % 2 == 0 else ['candidate', 'control']):
                label=f'{pair}-{workload}-{kind}'
                row = (directory_sample(executables[kind],output,label) if workload=='directory' else
                       icon_sample(executables[kind],output,label) if workload=='icon' else
                       decode_sample(executables[kind],output,label) if workload=='oriented' else
                       sample(executables[kind], output, label, workload, pressure, colors))
                report['samples'].append({'pair': pair, 'workload': workload, 'kind': kind} | row)
                (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(f'{args.label} {pair+1}/{args.pairs} {workload} {kind}: first={row["first_ms"]:.2f} resources={row["final"]}', flush=True)
    report['summary'] = {workload: {kind: summarize([r for r in report['samples']
                           if r['workload'] == workload and r['kind'] == kind])
                           for kind in executables} for workload in workloads}
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in fixtures.items())
    assert all(hashlib.sha256(executables[k].read_bytes()).hexdigest() == h for k, h in hashes.items())
    assert len(report['samples']) == args.pairs * len(workloads) * 2
    report['verdict'] = 'MEASUREMENT_PASS'
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('REPORT', output/'report.json')
    print('FOTO_RECURSIVE_MEASUREMENT_PASS')


if __name__ == '__main__':
    main()
