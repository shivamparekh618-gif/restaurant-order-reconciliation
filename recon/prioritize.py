"""Build the exception list and rank it into a work queue."""

from datetime import datetime, time, timedelta

from . import config
from .match import run_sql
from .timeutil import local_tz, to_local

ACTIONS = {
    "MISSING_IN_POS": "Confirm with kitchen whether it was made; ring it in so sales and inventory are right",
    "CANCELLED_NOT_VOIDED": "Void the POS check; check whether food was made and wasted",
    "PRICE_MISMATCH": "Compare platform vs POS menu prices for the items on this order",
    "LATE_DELIVERY": "Check ticket time vs pickup; dispute if the courier was late",
    "POS_ONLY_DELIVERY": "Ask who rang it: phone order, test ticket, or wrong channel",
}


def build_exceptions(conn):
    run_sql(conn, "04_exceptions.sql", {
        "price_tol_cents": config.PRICE_MISMATCH_TOLERANCE_CENTS,
        "late_refund_rate": config.LATE_REFUND_RATE,
        "late_threshold_s": config.LATE_THRESHOLD_SECONDS,
    })


def as_of(conn):
    """The report is written the morning after the last order in the data."""
    last = conn.execute("SELECT MAX(placed_ts) FROM delivery_orders").fetchone()[0]
    day_after = to_local(last).date() + timedelta(days=1)
    return datetime.combine(day_after, time(9), tzinfo=local_tz())


def tier(score):
    for threshold, name in config.TIER_THRESHOLDS:
        if score >= threshold:
            return name
    return config.TIER_THRESHOLDS[-1][1]


def prioritize(conn):
    now = as_of(conn)
    rows = conn.execute("""
        SELECT exception_type, platform_order_id, check_id, event_ts, dollars_at_risk_cents, detail
        FROM exceptions
    """).fetchall()

    queue = []
    for etype, order_id, check_id, ts, cents, detail in rows:
        when = to_local(ts)
        age_days = (now - when).total_seconds() / 86400
        if age_days <= config.FRESH_DAYS:
            recency = config.FRESH_MULTIPLIER
        elif age_days > config.DISPUTE_WINDOW_DAYS:
            recency = config.EXPIRED_MULTIPLIER
        else:
            recency = 1.0
        dollars = cents / 100
        score = dollars * config.TYPE_WEIGHTS[etype] * recency
        queue.append({
            "exception_type": etype,
            "platform_order_id": order_id or "",
            "check_id": check_id or "",
            "when_local": when.strftime("%a %b %d %I:%M %p"),
            "age_days": round(age_days, 1),
            "dollars_at_risk": round(dollars, 2),
            "type_weight": config.TYPE_WEIGHTS[etype],
            "recency_factor": recency,
            "priority_score": round(score, 2),
            "tier": tier(score),
            "detail": detail,
            "next_step": ACTIONS[etype],
        })
    queue.sort(key=lambda r: -r["priority_score"])
    for rank, row in enumerate(queue, 1):
        row["rank"] = rank
    return queue, now
