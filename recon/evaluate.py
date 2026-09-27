"""Score the pipeline against the synthetic ground truth.

This only works because the data is synthetic: the generator records which POS
check really belongs to each platform order and which problems it injected. On
real data there is no answer key, which is why the report shows *how* each
order was matched so a person can spot-check the fuzzy ones.
"""

import csv

from . import config

ISSUE_TO_EXCEPTION = {
    "MISSING_IN_POS": "MISSING_IN_POS",
    "CANCELLED_NOT_VOIDED": "CANCELLED_NOT_VOIDED",
    "PRICE_MISMATCH": "PRICE_MISMATCH",
    "LATE": "LATE_DELIVERY",
    "POS_ONLY_DELIVERY": "POS_ONLY_DELIVERY",
}


def evaluate(conn, truth_path=config.TRUTH_FILE):
    with open(truth_path, newline="") as f:
        truth = list(csv.DictReader(f))

    true_pairs = {(t["platform_order_id"], t["check_id"]) for t in truth if t["platform_order_id"] and t["check_id"]}
    predicted = set(conn.execute("SELECT platform_order_id, check_id FROM matches").fetchall())
    correct = len(true_pairs & predicted)

    by_method = {}
    for method, in conn.execute("SELECT DISTINCT match_method FROM matches"):
        pairs = set(conn.execute(
            "SELECT platform_order_id, check_id FROM matches WHERE match_method = ?", (method,)
        ).fetchall())
        by_method[method] = {"matched": len(pairs), "correct": len(pairs & true_pairs)}

    exc_truth = set()
    for t in truth:
        for issue in filter(None, t["issues"].split("|")):
            if issue in ISSUE_TO_EXCEPTION:
                exc_truth.add((ISSUE_TO_EXCEPTION[issue], t["platform_order_id"] or t["check_id"]))
    exc_pred = {
        (etype, order_id or check_id)
        for etype, order_id, check_id in conn.execute(
            "SELECT exception_type, platform_order_id, check_id FROM exceptions")
    }

    per_type = {}
    for etype in sorted({e for e, _ in exc_truth | exc_pred}):
        t = {k for e, k in exc_truth if e == etype}
        p = {k for e, k in exc_pred if e == etype}
        per_type[etype] = {"expected": len(t), "flagged": len(p), "caught": len(t & p), "false_alarms": len(p - t)}

    return {
        "match_precision": correct / len(predicted) if predicted else 0,
        "match_recall": correct / len(true_pairs) if true_pairs else 0,
        "true_pairs": len(true_pairs),
        "predicted_pairs": len(predicted),
        "by_method": by_method,
        "exceptions": per_type,
    }
