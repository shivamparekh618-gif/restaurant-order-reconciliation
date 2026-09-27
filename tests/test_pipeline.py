import csv
import tempfile
import unittest
from pathlib import Path

from recon import config, generate
from recon.evaluate import evaluate
from recon.load import connect, load, normalize_ref, to_cents
from recon.match import match
from recon.prioritize import build_exceptions, prioritize
from recon.timeutil import parse_pos_ts

PLATFORM_FIELDS = ["platform_order_id", "placed_at", "promised_at", "delivered_at", "status",
                   "items", "subtotal", "tax", "total"]
POS_FIELDS = ["check_id", "opened_at", "terminal", "order_channel", "external_ref", "items",
              "subtotal", "tax", "total", "voided"]


def write_csv(path, fields, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(fields, row)))


class CleaningTests(unittest.TestCase):
    def test_reference_variants_normalize_to_one_form(self):
        for raw in ["DP-8F3A21", "dp-8f3a21", "8F3A21", "DP 8F3A21", " DP-8F3A21 "]:
            self.assertEqual(normalize_ref(raw), "DP-8F3A21", raw)

    def test_garbage_reference_is_rejected(self):
        self.assertIsNone(normalize_ref("table 4"))
        self.assertIsNone(normalize_ref("DP-8F3A2"))

    def test_money_with_dollar_sign(self):
        self.assertEqual(to_cents("$1,234.50"), 123450)
        self.assertEqual(to_cents("12.3"), 1230)

    def test_both_pos_terminal_formats_agree(self):
        self.assertEqual(parse_pos_ts("08/03/2026 06:42 PM"), parse_pos_ts("2026-08-03 18:42:00"))


class SmallScenarioTests(unittest.TestCase):
    """Five hand-built orders, one per outcome we care about."""

    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp())
        # POS times are local (UTC-7 in August): 18:00Z == 11:00 AM local.
        write_csv(tmp / "platform.csv", PLATFORM_FIELDS, [
            ("DP-AAAAAA", "2026-08-03T18:00:00Z", "2026-08-03T18:35:00Z", "2026-08-03T18:30:00Z",
             "delivered", "Paneer Wrap", "11.50", "1.09", "12.59"),        # exact ref match
            ("DP-BBBBBB", "2026-08-03T18:10:00Z", "2026-08-03T18:45:00Z", "2026-08-03T19:20:00Z",
             "delivered", "Dal Makhani", "10.00", "0.95", "10.95"),        # fallback match, late
            ("DP-CCCCCC", "2026-08-03T19:00:00Z", "2026-08-03T19:35:00Z", "2026-08-03T19:30:00Z",
             "delivered", "Butter Chicken Plate", "16.00", "1.52", "17.52"),  # never rung in
            ("DP-DDDDDD", "2026-08-03T20:00:00Z", "2026-08-03T20:35:00Z", "",
             "cancelled", "Samosa (2)", "6.00", "0.57", "6.57"),           # cancelled, not voided
            ("DP-EEEEEE", "2026-08-03T21:00:00Z", "2026-08-03T21:35:00Z", "2026-08-03T21:30:00Z",
             "delivered", "Chicken Tikka Bowl", "13.50", "1.28", "14.78"),  # price mismatch
        ])
        write_csv(tmp / "pos.csv", POS_FIELDS, [
            ("CHK-1", "08/03/2026 11:01 AM", "T1", "Delivery", "dp-aaaaaa", "Paneer Wrap", "11.50", "1.09", "12.59", "N"),
            ("CHK-2", "2026-08-03 11:13:00", "T2", "DELIVERY", "", "Dal Makhani", "$10.00", "0.95", "$10.95", "N"),
            ("CHK-3", "08/03/2026 11:05 AM", "T1", "Dine In", "", "Dal Makhani", "10.00", "0.95", "10.95", "N"),
            ("CHK-4", "08/03/2026 01:01 PM", "T1", "Delivery", "DDDDDD", "Samosa (2)", "6.00", "0.57", "6.57", "N"),
            ("CHK-5", "08/03/2026 02:01 PM", "T1", "Delivery", "DP-EEEEEE", "Chicken Tikka Bowl", "14.50", "1.38", "15.88", "N"),
            ("CHK-6", "08/03/2026 03:30 PM", "T1", "Delivery", "", "Mango Lassi", "5.00", "0.48", "5.48", "N"),
        ])
        cls.conn = connect()
        load(cls.conn, tmp / "platform.csv", tmp / "pos.csv")
        match(cls.conn)
        build_exceptions(cls.conn)
        cls.queue, _ = prioritize(cls.conn)

    def matched(self):
        return dict(self.conn.execute("SELECT platform_order_id, check_id FROM matches").fetchall())

    def flagged(self):
        return {(r["exception_type"], r["platform_order_id"] or r["check_id"]) for r in self.queue}

    def test_exact_and_fallback_matches(self):
        m = self.matched()
        self.assertEqual(m["DP-AAAAAA"], "CHK-1")
        self.assertEqual(m["DP-BBBBBB"], "CHK-2")  # not the dine-in check at a similar time

    def test_every_problem_is_flagged(self):
        self.assertEqual(self.flagged(), {
            ("LATE_DELIVERY", "DP-BBBBBB"),
            ("MISSING_IN_POS", "DP-CCCCCC"),
            ("CANCELLED_NOT_VOIDED", "DP-DDDDDD"),
            ("PRICE_MISMATCH", "DP-EEEEEE"),
            ("POS_ONLY_DELIVERY", "CHK-6"),
        })

    def test_missing_order_outranks_late_delivery(self):
        ranks = {r["exception_type"]: r["rank"] for r in self.queue}
        self.assertLess(ranks["MISSING_IN_POS"], ranks["LATE_DELIVERY"])


class FullRunTests(unittest.TestCase):
    """Run on the generated two-week dataset and score against its answer key."""

    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp())
        delivery, pos, truth = generate.generate()
        for name, rows in [("d.csv", delivery), ("p.csv", pos), ("t.csv", truth)]:
            write_csv(tmp / name, list(rows[0]), [list(r.values()) for r in rows])
        cls.conn = connect()
        load(cls.conn, tmp / "d.csv", tmp / "p.csv")
        match(cls.conn)
        build_exceptions(cls.conn)
        cls.scores = evaluate(cls.conn, tmp / "t.csv")

    def test_matching_quality(self):
        self.assertGreaterEqual(self.scores["match_precision"], 0.99)
        self.assertGreaterEqual(self.scores["match_recall"], 0.99)

    def test_high_value_exceptions_are_all_caught(self):
        for etype in ("MISSING_IN_POS", "CANCELLED_NOT_VOIDED", "LATE_DELIVERY", "POS_ONLY_DELIVERY"):
            s = self.scores["exceptions"][etype]
            self.assertEqual(s["caught"], s["expected"], etype)

    def test_config_weights_cover_every_type(self):
        self.assertEqual(set(self.scores["exceptions"]), set(config.TYPE_WEIGHTS))


if __name__ == "__main__":
    unittest.main()
