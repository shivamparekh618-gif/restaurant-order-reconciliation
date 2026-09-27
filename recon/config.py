"""Tunable assumptions for the reconciliation workflow.

Every number here is a guess about how the restaurant operates. They are kept in
one place on purpose: the first conversation with a real manager should be
about whether these values are right, not about the code.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SQL_DIR = ROOT / "sql"
OUTPUT_DIR = ROOT / "output"

DELIVERY_FILE = DATA_DIR / "delivery_platform_orders.csv"
POS_FILE = DATA_DIR / "pos_checks.csv"
TRUTH_FILE = DATA_DIR / "_synthetic_truth.csv"

# The POS exports local wall-clock time; the delivery platform exports UTC.
RESTAURANT_TZ = "America/Los_Angeles"
# Used only if the system has no tz database (e.g. some Windows installs).
FALLBACK_UTC_OFFSET_HOURS = -7

# --- Matching -------------------------------------------------------------
# A POS check without a usable reference can still be matched if it was opened
# close to the platform order time and the subtotal is close.
FALLBACK_WINDOW_SECONDS = 8 * 60
FALLBACK_AMOUNT_TOLERANCE_CENTS = 300

# --- Exception rules ------------------------------------------------------
PRICE_MISMATCH_TOLERANCE_CENTS = 50
LATE_THRESHOLD_SECONDS = 15 * 60
# Share of an order's value we assume is lost (refund/credit) on a late order.
LATE_REFUND_RATE = 0.20

# --- Prioritisation -------------------------------------------------------
# Weight = how confident we are that the dollars flagged are really lost and
# recoverable if someone acts. Missing POS entries are near-certain; a late
# delivery only sometimes turns into a refund.
TYPE_WEIGHTS = {
    "MISSING_IN_POS": 1.0,
    "PRICE_MISMATCH": 1.0,
    "CANCELLED_NOT_VOIDED": 0.8,
    "POS_ONLY_DELIVERY": 0.6,
    "LATE_DELIVERY": 0.5,
}
# Recent exceptions are worth more: staff still remember the shift, and the
# platform still accepts disputes. Both windows are assumptions to confirm
# against the real platform contract and how the team works.
FRESH_DAYS = 3
FRESH_MULTIPLIER = 1.5
DISPUTE_WINDOW_DAYS = 7
EXPIRED_MULTIPLIER = 0.5

TIER_THRESHOLDS = [(20.0, "Act today"), (5.0, "This week"), (0.0, "Monitor")]
