# SPDX-License-Identifier: GPL-3.0-or-later
import json
import unittest
from unittest.mock import patch
from publish_release import get_release


class ReleaseLookup(unittest.TestCase):
    def test_draft_resolves_when_release_by_tag_is_unavailable(self):
        def api(path):
            if path == 'releases/42':
                return {'id':42,'tag_name':'v1.0.4','draft':True}
            raise LookupError('Draft is unavailable through this endpoint')
        selected=json.dumps({'databaseId':42,'tagName':'v1.0.4'})
        with patch('publish_release.subprocess.check_output',return_value=selected):
            release=get_release('v1.0.4','owner/repo',api)
        self.assertTrue(release['draft'])
        self.assertEqual(release['id'],42)

    def test_mismatched_record_is_rejected(self):
        selected=json.dumps({'databaseId':42,'tagName':'v1.0.4'})
        with patch('publish_release.subprocess.check_output',return_value=selected):
            with self.assertRaises(ValueError):
                get_release('v1.0.4','owner/repo',lambda _: {'tag_name':'v9.9.9'})


if __name__ == '__main__':
    unittest.main()
