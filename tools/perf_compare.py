# SPDX-License-Identifier: GPL-3.0-or-later
"""Serial paired native-viewer benchmark. Synthetic inputs; no cache flushing or policy changes."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics as st
import time
import stress_test as t


def sample(exe, output, label, empty=False):
    empty_stats = {}
    if empty:
        empty_log = output / f'{label}-empty.csv'
        process, hwnd, _ = t.s.launch(exe, None, empty_log)
        try:
            time.sleep(.3)
            empty_stats = {'empty_first_ms':float(t.s.events(empty_log,'window')[0]['elapsed_ms']),
                           'empty_rss':t.resources(process)['rss'],
                           'empty_private':t.resources(process)['private'],
                           'empty_cpu_ms':t.s.cpu_ms(process)}
            assert not t.s.events(empty_log,'graphics_error')
        finally:t.s.close(process,hwnd)

    log = output / f'{label}.csv'
    process, hwnd, started = t.s.launch(exe, t.ROOT/'artifacts/photos/photo1.jpg', log)
    try:
        first = t.s.wait(lambda: t.s.events(log, 'image'), 'first photo')[0]
        external = (time.perf_counter()-started)*1000
        t.s.wait(lambda: t.s.enabled(t.s.get_item(hwnd, 102)), 'folder ready')
        time.sleep(.6)
        t.s.pixel_corners(hwnd)
        baseline = t.resources(process)
        cpu = t.s.cpu_ms(process)
        navigation = []
        # Three photos, both directions, with enough time for adjacent prefetch.
        for index, name in [(1,'photo2.jpg'),(2,'photo10.jpg'),(1,'photo2.jpg'),(0,'photo1.jpg')]*3:
            count = len(t.s.events(log, 'image'))
            t.s.command(hwnd, 102 if name in ('photo2.jpg','photo10.jpg') and index > sample.position else 101)
            t.s.wait(lambda: len(t.s.events(log, 'image')) > count, 'navigation draw')
            row = t.s.events(log, 'image')[-1]
            t.s.wait(lambda: t.s.text(hwnd).startswith(name+' '), 'selected filename')
            navigation.append({'ms':float(row['request_ms']), 'cached':row['cached']=='true'})
            sample.position = index
            time.sleep(.2)
        elapsed_cpu = t.s.cpu_ms(process)-cpu
        t.s.pixel_corners(hwnd)
        time.sleep(.3)
        final = t.resources(process)
        before = t.s.cpu_ms(process); time.sleep(.3)
        idle = t.s.cpu_ms(process)-before
        assert not t.s.events(log,'graphics_error') and not t.s.events(log,'error')
        return empty_stats | {'first_ms':float(first['elapsed_ms']), 'external_ms':external,
                'nav_median_ms':st.median(x['ms'] for x in navigation),
                'nav_p95_ms':sorted(x['ms'] for x in navigation)[-1],
                'cache_hits':sum(x['cached'] for x in navigation), 'navigation':navigation,
                'cpu_ms':elapsed_cpu, 'idle_cpu_ms_300ms':idle,
                'baseline':baseline, 'final':final}
    finally:
        sample.position = 0
        t.s.close(process, hwnd)


sample.position = 0


def summary(rows):
    result = {key:round(st.median(row[key] for row in rows),3) for key in
              ['first_ms','external_ms','nav_median_ms','nav_p95_ms','cache_hits','cpu_ms','idle_cpu_ms_300ms']}
    for key in ['rss','private','peak_rss','handles','gdi','user']:
        result[key] = st.median(row['final'][key] for row in rows)
    for key in ['empty_first_ms','empty_rss','empty_private','empty_cpu_ms']:
        if key in rows[0]:result[key] = st.median(row[key] for row in rows)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--control',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--pairs',type=int,default=6)
    parser.add_argument('--label',required=True)
    parser.add_argument('--empty',action='store_true')
    args=parser.parse_args()
    assert 2<=args.pairs<=20
    output=t.ROOT/'artifacts/optimization'/f'{time.time_ns()}-{args.label}'
    output.mkdir(parents=True)
    executables={'control':args.control.resolve(),'candidate':args.candidate.resolve()}
    hashes={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in executables.items()}
    fixtures={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (t.ROOT/'artifacts/photos').glob('*.jpg')}
    report={'label':args.label,'hashes':hashes,'pairs':args.pairs,'empty_window_included':args.empty,'samples':[],
            'method':'Serial alternating AB/BA; warm OS cache; 24 MP JPEG; twelve 3-photo moves with 200ms settle; final pixels checked',
            'limits':'Single Windows 11 host; not cold-start or human UAT'}
    for pair in range(args.pairs):
        for kind in (['control','candidate'] if pair%2==0 else ['candidate','control']):
            row=sample(executables[kind],output,f'{pair}-{kind}',args.empty)
            report['samples'].append({'pair':pair,'kind':kind}|row)
            (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(f'{args.label} {pair+1}/{args.pairs} {kind}: first={row["first_ms"]:.1f} nav={row["nav_median_ms"]:.1f} hit={row["cache_hits"]}/12 rss={row["final"]["rss"]//1024**2}MiB',flush=True)
    report['summary']={k:summary([r for r in report['samples'] if r['kind']==k]) for k in executables}
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in fixtures.items())
    assert all(hashlib.sha256(executables[k].read_bytes()).hexdigest()==h for k,h in hashes.items())
    report['verdict']='PASS'
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))
    print('REPORT',output/'report.json')
    print('FOTO_PERF_MEASUREMENT_PASS')


if __name__=='__main__':main()
