"""Match platform orders to POS checks in two passes."""

from . import config

# In the fallback pass, a $1 subtotal gap costs the same as a 2-minute time gap.
DOLLAR_COST_IN_MINUTES = 2.0


def run_sql(conn, name, params=None):
    sql = (config.SQL_DIR / name).read_text()
    for statement in sql.split(";"):
        if statement.strip():
            conn.execute(statement, params or {})


def match(conn):
    run_sql(conn, "02_exact_match.sql")

    sql = (config.SQL_DIR / "03_candidate_pairs.sql").read_text()
    candidates = conn.execute(sql, {
        "window_s": config.FALLBACK_WINDOW_SECONDS,
        "amount_tol_cents": config.FALLBACK_AMOUNT_TOLERANCE_CENTS,
    }).fetchall()

    def cost(row):
        _, _, gap_s, gap_cents = row
        return abs(gap_s) / 60 + (gap_cents / 100) * DOLLAR_COST_IN_MINUTES

    # Greedy one-to-one assignment: take the closest pair first, then the next
    # closest pair whose order and check are both still free.
    used_orders, used_checks, fallback = set(), set(), []
    for order_id, check_id, gap_s, gap_cents in sorted(candidates, key=cost):
        if order_id in used_orders or check_id in used_checks:
            continue
        used_orders.add(order_id)
        used_checks.add(check_id)
        fallback.append((order_id, check_id, "time_amount", abs(gap_s), gap_cents))

    conn.executemany("INSERT INTO matches VALUES (?,?,?,?,?)", fallback)

    counts = dict(conn.execute("SELECT match_method, COUNT(*) FROM matches GROUP BY 1").fetchall())
    return {
        "exact_ref": counts.get("exact_ref", 0),
        "time_amount": counts.get("time_amount", 0),
        "candidate_pairs": len(candidates),
    }
