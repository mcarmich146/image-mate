from __future__ import annotations

import unittest

from backend.app.tasking_names import normalize_tasking_name


class TaskingNameTests(unittest.TestCase):
    def test_prefix_is_canonical_and_idempotent(self):
        self.assertEqual(normalize_tasking_name("site-a"), "Mark - site-a")
        self.assertEqual(normalize_tasking_name("Mark - site-a"), "Mark - site-a")
        self.assertEqual(normalize_tasking_name("Mark — site-a"), "Mark - site-a")
        self.assertEqual(normalize_tasking_name("Mark: site-a"), "Mark - site-a")
        self.assertEqual(normalize_tasking_name("Mark - Mark — site-a"), "Mark - site-a")

    def test_prefix_limit_is_checked_after_normalization(self):
        with self.assertRaises(ValueError):
            normalize_tasking_name("x" * 114)


if __name__ == "__main__":
    unittest.main()
