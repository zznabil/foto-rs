# SPDX-License-Identifier: GPL-3.0-or-later
"""Positive and representative broken-state controls for release verification."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from check_release import check_checksums, safe_members

ROOT=Path(__file__).resolve().parents[1]


class ReleaseControls(unittest.TestCase):
    def test_checksums_accept_valid_and_reject_modified_missing_extra_and_traversal(self):
        parent=ROOT/'artifacts/validator-controls';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as name:
            root=Path(name);self.assertTrue(root.resolve().is_relative_to(parent.resolve()))
            (root/'payload.zip').write_bytes(b'known good')
            ledger=hashlib.sha256(b'known good').hexdigest()+'  payload.zip\n'
            (root/'SHA256SUMS.txt').write_text(ledger)
            self.assertEqual(len(check_checksums(root)),1)
            (root/'payload.zip').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'Checksum mismatch'):check_checksums(root)
            (root/'payload.zip').unlink()
            with self.assertRaisesRegex(ValueError,'Missing release'):check_checksums(root)
            (root/'payload.zip').write_bytes(b'known good')
            (root/'extra.exe').write_bytes(b'not listed')
            with self.assertRaisesRegex(ValueError,'Unlisted'):check_checksums(root)
            (root/'extra.exe').unlink()
            (root/'SHA256SUMS.txt').write_text(ledger.replace('payload.zip','../payload.zip'))
            with self.assertRaisesRegex(ValueError,'unsafe'):check_checksums(root)

    def test_archive_paths_accept_relative_and_reject_escape(self):
        for name,valid in [('Foto/readme.txt',True),('../escape.exe',False),('/absolute.exe',False),('C:/drive.exe',False),('Foto\\escape.exe',False)]:
            with self.subTest(name=name):
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w') as archive:archive.writestr(name.replace(chr(92),'/'),b'fixture')
                if chr(92) in name:
                    buffer=io.BytesIO(buffer.getvalue().replace(name.replace(chr(92),'/').encode(),name.encode()))
                with zipfile.ZipFile(buffer) as archive:
                    if valid:self.assertEqual(safe_members(archive),[name])
                    else:
                        with self.assertRaisesRegex(ValueError,'Unsafe ZIP'):safe_members(archive)


if __name__=='__main__':unittest.main()
