# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure decoder header and batch-timing protocol checks."""
if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")
import ast
import hashlib


def header(data):
    assert data.endswith(b'\n'),'incomplete measurement header'
    words=data.decode('ascii').split();assert len(words)==7 and words[0]=='DECODE'
    width,height,ow,oh,length,elapsed=map(int,words[1:])
    assert 0<width<=8192 and 0<height<=8192 and width*height<=32000000
    assert ow>=width and oh>=height and length==width*height*4 and elapsed>=0
    return {'width':width,'height':height,'original':[ow,oh],'bytes':length,'decode_ms':elapsed/1e6}


def self_test():
    assert header(b'DECODE 2 3 2 3 24 1000000\n')['decode_ms']==1
    for value in [b'DECODE 2 3 2 3 24 1',b'DECODE 0 3 2 3 0 1\n',b'DECODE 8193 1 9000 1 32772 1\n',b'DECODE 2 3 2 3 23 1\n',b'DECODE 2 3 2 3 24 -1\n']:
        try:header(value)
        except AssertionError:pass
        else:raise AssertionError('malformed header accepted')
    assert hashlib.sha256(b'abc').hexdigest()=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


def parse_probe_timing(stderr, inner, repeats, delay, decode_ms):
    lines = stderr.splitlines()

    def value(prefix):
        matches = [line[len(prefix):] for line in lines if line.startswith(prefix)]
        assert len(matches) == 1, (prefix, matches)
        return matches[0]

    ranges = ast.literal_eval(value('BATCH_RANGES_NS '))
    times = ast.literal_eval(value('BATCH_TIMES_NS '))
    sleep = ast.literal_eval(value('OBSERVED_SLEEP_NS '))
    count = int(value('LOOP_COUNT '))
    delay_events = int(value('DELAY_EVENT_COUNT '))
    delay_batch = int(value('DELAY_BATCH_INDEX '))
    delay_completed = int(value('DELAY_COMPLETED_LOADS '))
    argument_count = int(value('ARGUMENT_UTF16_COUNT '))
    argument_hex = value('ARGUMENT_UTF16_HEX ')
    assert isinstance(ranges, list) and len(ranges) == 16
    assert isinstance(times, list) and len(times) == 16
    assert isinstance(sleep, list) and len(sleep) == 2
    assert delay_events in [0, 1], 'delay event placement mismatch'
    assert delay_batch in [-1, 8], 'delay event placement mismatch'
    assert delay_completed >= 0
    assert argument_count >= 0
    assert len(argument_hex) == argument_count * 4, 'argument hex length mismatch'
    assert all(character in '0123456789abcdef' for character in argument_hex), 'invalid argument hex'
    assert all(isinstance(item, list) and len(item) == 2 for item in ranges)
    assert all(type(value) is int and value >= 0 for pair in ranges for value in pair), 'invalid batch range timestamp'
    assert all(isinstance(item, int) and item >= 0 for item in sleep)
    assert all(
        isinstance(item, int) and item > 0 and end >= start and end - start == item
        for item, (start, end) in zip(times, ranges)
    ), 'batch range/timing mismatch'
    for previous, current in zip(ranges, ranges[1:]):
        assert current[0] >= previous[1], (previous, current)
    assert count == 16 * inner * repeats, 'loop count mismatch'
    assert abs(int(round(decode_ms * 1e6 * count)) - sum(times)) <= count + 1, 'header mean differs from batch durations'
    if delay:
        assert delay_events == 1 and delay_batch == 8, 'delay event placement mismatch'
        assert delay_completed == inner * repeats, 'delay completed batch work mismatch'
        assert sleep[1] > sleep[0]
        assert 900_000_000 <= sleep[1] - sleep[0] <= 1_500_000_000, 'observed sleep outside 900..1500ms'
        assert ranges[8][0] <= sleep[0] <= sleep[1] <= ranges[8][1], 'sleep outside declared batch'
    else:
        assert delay_events == 0 and delay_batch == -1 and delay_completed == 0, 'unexpected delay markers'
        assert sleep == [0, 0], 'unexpected sleep interval'
    return (ranges, times, sleep, count, delay_events, delay_batch,
            delay_completed, argument_count, argument_hex)
