# SPDX-License-Identifier: GPL-3.0-or-later
"""Read complete records from the viewer's concurrently written timing log."""
import csv
import io


def rows(path):
    try:
        data = path.read_bytes()
        complete = data[:data.rfind(b'\n')+1].decode('utf-8')
    except (OSError, UnicodeError):
        return []
    result = list(csv.DictReader(io.StringIO(complete, newline='')))
    if any(None in row or any(value is None for value in row.values()) for row in result):
        raise ValueError('Malformed complete timing record')
    return result
