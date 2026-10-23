# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
from pathlib import Path
import unittest
from timing_log import rows


class TimingLog(unittest.TestCase):
    def test_every_partial_write_waits_for_complete_record(self):
        header = b'event,elapsed_ms,request_ms,cached,width,height\n'
        record = b'image,100.123,95.123,false,6000,4000\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'timings.csv'
            self.assertEqual(rows(path), [])
            for offset in range(len(header+record)):
                path.write_bytes((header+record)[:offset])
                self.assertEqual(rows(path), [], offset)
            path.write_bytes(header+record)
            self.assertEqual(rows(path)[0]['width'], '6000')
            self.assertEqual(rows(path)[0]['height'], '4000')
            path.write_bytes(header+record+b'image,')
            self.assertEqual(len(rows(path)), 1)
            path.write_bytes(header+b'image,100\n')
            with self.assertRaises(ValueError):
                rows(path)


if __name__ == '__main__':
    unittest.main()
