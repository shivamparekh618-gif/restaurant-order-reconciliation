"""Look across exceptions for causes a manager can fix once.

The work queue handles orders one at a time. These checks answer the more
useful question: is something upstream producing these exceptions?
"""

from collections import Counter, defaultdict

from .timeutil import to_local


def _items(text):
    return [i.strip() for i in (text or "").split(";") if i.strip()]


def price_mismatch_driver(conn):
    """Which menu item explains the price mismatches, and by how much per unit?"""
    matched = conn.execute("""
        SELECT items, subtotal_cents, pos_subtotal_cents, placed_ts
        FROM order_view
        WHERE status = 'delivered' AND check_id IS NOT NULL
    """).fetchall()
    mismatched = [r for r in matched if abs(r[1] - r[2]) > 50]
    if not mismatched:
        return None

    in_all, in_bad = Counter(), Counter()
    for items, *_ in matched:
        in_all.update(set(_items(items)))
    for items, *_ in mismatched:
        in_bad.update(set(_items(items)))

    rows = []
    for item, n_bad in in_bad.items():
        share_bad = n_bad / len(mismatched)
        share_all = in_all[item] / len(matched)
        rows.append((share_bad / share_all, item, n_bad, share_bad, share_all))
    rows.sort(reverse=True)
    lift, item, n_bad, share_bad, share_all = rows[0]

    # Gap per unit of the suspect item, on mismatched orders that contain it.
    per_unit = Counter()
    first_ts = None
    for items, platform, pos, ts in mismatched:
        qty = _items(items).count(item)
        if qty:
            per_unit[round((pos - platform) / qty)] += 1
            first_ts = ts if first_ts is None else min(first_ts, ts)
    gap_cents, gap_count = per_unit.most_common(1)[0]
    explained = [r for r in mismatched if item in _items(r[0])]
    total_gap = sum(r[2] - r[1] for r in explained)

    # Orders containing the item since the gap first appeared, to project forward.
    since = [r for r in matched if r[3] >= first_ts and item in _items(r[0])]
    days = (max(r[3] for r in matched) - first_ts) / 86400 + 1
    units = sum(_items(r[0]).count(item) for r in since)
    weekly_cents = units / days * 7 * gap_cents

    return {
        "item": item,
        "mismatched_orders": len(mismatched),
        "orders_with_item": n_bad,
        "share_of_mismatches": share_bad,
        "share_of_all_orders": share_all,
        "lift": lift,
        "typical_gap_per_unit": gap_cents / 100,
        "orders_with_that_gap": gap_count,
        "first_seen": to_local(first_ts).strftime("%a %b %d"),
        "gap_so_far": total_gap / 100,
        "projected_weekly": weekly_cents / 100,
        "projected_yearly": weekly_cents * 52 / 100,
        "unexplained_mismatches": len(mismatched) - len(explained),
    }


def _shift(ts):
    local = to_local(ts)
    part = "Lunch" if local.hour < 15 else ("Afternoon" if local.hour < 17 else "Dinner")
    return local.strftime("%a"), part


def hotspot(conn, exception_type):
    """Where do exceptions of one type concentrate, by weekday and shift?"""
    exc = conn.execute("SELECT event_ts FROM exceptions WHERE exception_type = ?", (exception_type,)).fetchall()
    orders = conn.execute("SELECT placed_ts FROM delivery_orders WHERE status = 'delivered'").fetchall()
    if not exc:
        return None
    n_exc, n_orders = Counter(), Counter()
    for (ts,) in exc:
        n_exc[_shift(ts)] += 1
    for (ts,) in orders:
        n_orders[_shift(ts)] += 1
    cells = []
    for key, total in n_orders.items():
        cells.append({
            "day": key[0], "shift": key[1],
            "exceptions": n_exc[key], "orders": total,
            "rate": n_exc[key] / total,
        })
    overall = len(exc) / len(orders)
    top = sorted(cells, key=lambda c: -c["exceptions"])
    focus = [c for c in top if c["rate"] >= 2 * overall and c["exceptions"] >= 3]
    focus_exc = sum(c["exceptions"] for c in focus)
    focus_orders = sum(c["orders"] for c in focus)
    return {
        "total": len(exc),
        "overall_rate": overall,
        "focus": focus,
        "focus_share_of_exceptions": focus_exc / len(exc) if exc else 0,
        "focus_share_of_orders": focus_orders / len(orders),
        "focus_rate": focus_exc / focus_orders if focus_orders else 0,
        "rest_rate": (len(exc) - focus_exc) / (len(orders) - focus_orders),
    }


def by_hour(conn, exception_type):
    counts = defaultdict(lambda: [0, 0])
    for (ts,) in conn.execute("SELECT placed_ts FROM delivery_orders WHERE status = 'delivered'"):
        counts[to_local(ts).hour][1] += 1
    for (ts,) in conn.execute("SELECT event_ts FROM exceptions WHERE exception_type = ?", (exception_type,)):
        counts[to_local(ts).hour][0] += 1
    return {h: tuple(v) for h, v in sorted(counts.items())}


def find_patterns(conn):
    return {
        "price": price_mismatch_driver(conn),
        "missing": hotspot(conn, "MISSING_IN_POS"),
        "late": hotspot(conn, "LATE_DELIVERY"),
        "late_by_hour": by_hour(conn, "LATE_DELIVERY"),
        "missing_by_hour": by_hour(conn, "MISSING_IN_POS"),
    }
