import unittest

import run
from query_observer import item_bytes


class ExpectedEventTest(unittest.TestCase):
    def event(self, nanos):
        return {"type_name": "T", "value": "1", "seq_nr": 1, "occurred_at_ns": str(nanos),
                "manifest": "", "payload": {}}

    def test_floors_to_reader_precision(self):
        self.assertEqual(run.expected_event(self.event(1_234_567), "js")["occurred_at_ns"], "1000000")
        self.assertEqual(run.expected_event(self.event(1_234_567), "java")["occurred_at_ns"], "1234567")

    def test_negative_floors_toward_minus_infinity(self):
        self.assertEqual(run.expected_event(self.event(-1), "js")["occurred_at_ns"], "-1000000")


class ValidateDuplicateTest(unittest.TestCase):
    def test_accepts_optimistic_lock_with_same_head(self):
        run.validate_duplicate({"status": "error", "category": "optimisticLock"}, {"v": 1}, {"v": 1})

    def test_rejects_other_category(self):
        with self.assertRaises(AssertionError):
            run.validate_duplicate({"status": "error", "category": "storage"}, {"v": 1}, {"v": 1})

    def test_rejects_changed_head(self):
        with self.assertRaises(AssertionError):
            run.validate_duplicate({"status": "error", "category": "optimisticLock"}, {"v": 1}, {"v": 2})


class ItemBytesTest(unittest.TestCase):
    def test_counts_names_and_values(self):
        item = {"ab": {"S": "héllo"}, "n": {"N": "12"}, "b": {"B": "AQID"}}
        # 名前 2+1+1、S は UTF-8 で 6、N は (2桁+1)//2+1=2、B は復号後 3。
        self.assertEqual(item_bytes(item), 4 + 6 + 2 + 3)


if __name__ == "__main__":
    unittest.main()
