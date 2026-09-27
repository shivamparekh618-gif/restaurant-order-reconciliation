"""Run the full workflow: load -> match -> flag -> prioritize -> report.

    python run.py              # use the CSVs in data/
    python run.py --regenerate # rebuild the synthetic data first
"""

import argparse
import csv
import json

from recon import config, generate
from recon.evaluate import evaluate
from recon.load import connect, load
from recon.match import match
from recon.patterns import find_patterns
from recon.prioritize import build_exceptions, prioritize
from recon.report import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--regenerate", action="store_true", help="rebuild the synthetic input data")
    args = parser.parse_args()

    if args.regenerate or not config.DELIVERY_FILE.exists():
        generate.main()

    conn = connect()
    quality = load(conn)
    match_stats = match(conn)
    build_exceptions(conn)
    queue, as_of = prioritize(conn)
    patterns = find_patterns(conn)
    scores = evaluate(conn) if config.TRUTH_FILE.exists() else None

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    with open(config.OUTPUT_DIR / "exception_queue.csv", "w", newline="") as f:
        fields = ["rank", "tier", "priority_score", "exception_type", "platform_order_id", "check_id",
                  "when_local", "age_days", "dollars_at_risk", "type_weight", "recency_factor", "detail", "next_step"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(queue)

    matched = conn.execute("""
        SELECT platform_order_id, check_id, match_method, time_gap_s, amount_gap_cents
        FROM matches ORDER BY platform_order_id
    """).fetchall()
    with open(config.OUTPUT_DIR / "matched_orders.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["platform_order_id", "check_id", "match_method", "time_gap_s", "amount_gap_cents"])
        writer.writerows(matched)

    summary = {"as_of": as_of.isoformat(), "data_quality": quality, "matching": match_stats, "evaluation": scores}
    (config.OUTPUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    report_path = write_report(conn, queue, as_of, quality, match_stats, patterns, scores)

    tiers = {}
    for row in queue:
        tiers.setdefault(row["tier"], [0, 0.0])
        tiers[row["tier"]][0] += 1
        tiers[row["tier"]][1] += row["dollars_at_risk"]
    print(f"Matched {match_stats['exact_ref']} orders by reference, {match_stats['time_amount']} by time + amount")
    print(f"{len(queue)} exceptions:")
    for name in ("Act today", "This week", "Monitor"):
        n, dollars = tiers.get(name, (0, 0.0))
        print(f"  {name:<10} {n:>4}   ${dollars:,.2f} at risk")
    if scores:
        print(f"Match precision {scores['match_precision']:.1%}, recall {scores['match_recall']:.1%} (vs synthetic truth)")
    print(f"Manager view: {report_path}")


if __name__ == "__main__":
    main()
