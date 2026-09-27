"""Write the manager view: a single static HTML page, no dependencies."""

from html import escape

from . import config
from .timeutil import to_local

TOP_N = 15

CSS = """
:root {
  color-scheme: light;
  --bg: #f6f6f4; --card: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #8a8983;
  --rule: #e4e3de; --bar: #2a78d6; --bar-hi: #1c5aa6;
  --today: #b42318; --today-bg: #fdecea; --week: #8a5a00; --week-bg: #fff4d6;
  --monitor: #52514e; --monitor-bg: #eeeeea; --note-bg: #eef4fc;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #111110; --card: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --ink-3: #8f8e86;
    --rule: #2c2c2a; --bar: #3987e5; --bar-hi: #7fb2f0;
    --today: #ff8a80; --today-bg: #3a1714; --week: #f2c14e; --week-bg: #33280c;
    --monitor: #c3c2b7; --monitor-bg: #262624; --note-bg: #16233a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 28px 16px 48px; }
header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 32px 0 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-2); }
.sub { color: var(--ink-2); margin: 0; }
.badge { font-size: 12px; padding: 4px 10px; border-radius: 999px; background: var(--note-bg); color: var(--ink-2); }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 20px; }
.card { background: var(--card); border: 1px solid var(--rule); border-radius: 10px; padding: 14px 16px; }
.kpi .v { font-size: 28px; font-weight: 650; font-variant-numeric: tabular-nums; }
.kpi .l { color: var(--ink-2); font-size: 13px; }
.decisions { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.decision h3 { margin: 0 0 6px; font-size: 15px; }
.decision .n { color: var(--ink-3); font-weight: 600; margin-right: 6px; }
.decision p { margin: 6px 0; color: var(--ink-2); }
.decision .do { color: var(--ink); font-weight: 600; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
.charts h3 { font-size: 14px; margin: 0 0 2px; }
.charts .cap { color: var(--ink-2); font-size: 12px; margin: 0 0 8px; }
svg text { fill: var(--ink-2); font-size: 11px; }
svg .bar { fill: var(--bar); }
svg .bar:hover { fill: var(--bar-hi); }
svg .axis { stroke: var(--rule); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font-size: 12px; color: var(--ink-2); font-weight: 600; background: var(--card); }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
.tier { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.tier.today { color: var(--today); background: var(--today-bg); }
.tier.week { color: var(--week); background: var(--week-bg); }
.tier.monitor { color: var(--monitor); background: var(--monitor-bg); }
.mono { white-space: nowrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.muted { color: var(--ink-2); }
.split { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
dl { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; margin: 0; }
dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
footer { margin-top: 32px; color: var(--ink-3); font-size: 12px; }
"""

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIER_CLASS = {"Act today": "today", "This week": "week", "Monitor": "monitor"}
TYPE_LABEL = {
    "MISSING_IN_POS": "Missing in POS",
    "CANCELLED_NOT_VOIDED": "Cancelled, not voided",
    "PRICE_MISMATCH": "Price mismatch",
    "LATE_DELIVERY": "Late delivery",
    "POS_ONLY_DELIVERY": "POS-only delivery",
}


def money(x):
    return f"${x:,.0f}" if abs(x) >= 100 else f"${x:,.2f}"


def pct(x):
    return f"{x:.0%}" if x >= 0.1 else f"{x:.1%}"


def hour_label(h):
    return f"{(h - 1) % 12 + 1}{'a' if h < 12 else 'p'}"


def bar_chart(by_hour, title, caption):
    """Exception rate by hour of day, as a small single-series bar chart."""
    hours = [h for h, (_, n) in by_hour.items() if n >= 10]
    rates = {h: by_hour[h][0] / by_hour[h][1] for h in hours}
    top = max(rates.values()) or 1
    w, h, left, bottom, top_pad = 460, 170, 34, 22, 16
    plot_w, plot_h = w - left - 8, h - bottom - top_pad
    step = plot_w / len(hours)
    bw = step - 4
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{escape(title)}">']
    for frac in (0, 0.5, 1):
        y = top_pad + plot_h * (1 - frac)
        parts.append(f'<line class="axis" x1="{left}" x2="{w - 8}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{pct(top * frac) if frac else "0"}</text>')
    for i, hr in enumerate(hours):
        n_exc, n = by_hour[hr]
        bh = max(plot_h * rates[hr] / top, 0 if n_exc == 0 else 2)
        x = left + i * step + 2
        y = top_pad + plot_h - bh
        tip = f"{hour_label(hr)}: {n_exc} of {n} orders ({pct(rates[hr])})"
        # Rounded top, square base: draw a rounded rect and cover its bottom corners.
        parts.append(f'<g><title>{tip}</title>'
                     f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4"/>'
                     f'<rect class="bar" x="{x:.1f}" y="{max(y, top_pad + plot_h - 4):.1f}" width="{bw:.1f}" '
                     f'height="{min(bh, 4):.1f}"/></g>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h - 6}" text-anchor="middle">{hour_label(hr)}</text>')
    parts.append("</svg>")
    return f'<div class="card"><h3>{escape(title)}</h3><p class="cap">{escape(caption)}</p>{"".join(parts)}</div>'


def shift_names(cells):
    cells = sorted(cells, key=lambda c: WEEKDAYS.index(c["day"]))
    return " and ".join(f"{c['day']} {c['shift'].lower()}" for c in cells)


def decision_cards(patterns):
    cards = []
    p = patterns["price"]
    if p:
        cards.append(f"""
<div class="card decision"><h3><span class="n">1</span>Update the platform price of {escape(p['item'])}</h3>
<p>{p['orders_with_item']} of {p['mismatched_orders']} price mismatches contain this item, and the POS
charges <b>{money(p['typical_gap_per_unit'])} more per unit</b> on every one of them, starting {p['first_seen']}.
It looks like a POS price change that never reached the platform menu.</p>
<p>{money(p['gap_so_far'])} under-collected so far &middot; about <b>{money(p['projected_weekly'])}/week</b>
(~{money(p['projected_yearly'])}/year) if nothing changes.</p>
<p class="do">Next step: confirm the intended price, then update the platform menu.</p></div>""")
    m = patterns["missing"]
    if m and m["focus"]:
        shifts = shift_names(m["focus"])
        cards.append(f"""
<div class="card decision"><h3><span class="n">2</span>Watch order entry on {escape(shifts)}</h3>
<p>{pct(m['focus_share_of_exceptions'])} of platform orders missing from the POS happened in these shifts,
which carry only {pct(m['focus_share_of_orders'])} of orders. The miss rate there is
<b>{pct(m['focus_rate'])}</b> vs {pct(m['rest_rate'])} the rest of the week.</p>
<p>That pattern points at the order tablet or the person entering orders during the rush,
not at random mistakes.</p>
<p class="do">Next step: ask the closing lead how platform orders reach the kitchen during the rush.</p></div>""")
    late = patterns["late"]
    if late and late["focus"]:
        shifts = shift_names(late["focus"])
        cards.append(f"""
<div class="card decision"><h3><span class="n">3</span>Late deliveries cluster on {escape(shifts)}</h3>
<p><b>{pct(late['focus_rate'])}</b> of orders in these shifts arrived 15+ minutes past the promised
time, vs {pct(late['rest_rate'])} otherwise.</p>
<p>The data can't tell kitchen delay from courier delay: the platform export has no pickup time.</p>
<p class="do">Next step: pull pickup timestamps for these shifts before deciding on staffing or prep times.</p></div>""")
    return "".join(cards)


def queue_table(queue):
    rows = []
    for r in queue[:TOP_N]:
        ref = r["platform_order_id"] or r["check_id"]
        rows.append(f"""<tr>
<td class="num">{r['rank']}</td>
<td><span class="tier {TIER_CLASS[r['tier']]}">{r['tier']}</span></td>
<td>{TYPE_LABEL[r['exception_type']]}<div class="muted">{escape(r['detail'])}</div></td>
<td class="mono">{escape(ref)}</td>
<td>{escape(r['when_local'])}</td>
<td class="num">{money(r['dollars_at_risk'])}</td>
<td class="num">{r['priority_score']:.1f}</td>
<td>{escape(r['next_step'])}</td></tr>""")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>#</th><th>Tier</th><th>Exception</th><th>Order / check</th><th>When</th>
<th style="text-align:right">At risk</th><th style="text-align:right">Score</th><th>Next step</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def type_summary(queue):
    agg = {}
    for r in queue:
        a = agg.setdefault(r["exception_type"], {"n": 0, "usd": 0.0, "today": 0})
        a["n"] += 1
        a["usd"] += r["dollars_at_risk"]
        a["today"] += r["tier"] == "Act today"
    rows = "".join(
        f"<tr><td>{TYPE_LABEL[t]}</td><td class='num'>{a['n']}</td><td class='num'>{a['today']}</td>"
        f"<td class='num'>{money(a['usd'])}</td><td class='num'>{config.TYPE_WEIGHTS[t]}</td></tr>"
        for t, a in sorted(agg.items(), key=lambda kv: -kv[1]["usd"])
    )
    return f"""<div class="table-wrap"><table><thead><tr><th>Exception type</th><th style="text-align:right">Count</th>
<th style="text-align:right">Act today</th><th style="text-align:right">$ at risk</th>
<th style="text-align:right">Weight</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def write_report(conn, queue, as_of, quality, match_stats, patterns, scores):
    n_orders = conn.execute("SELECT COUNT(*) FROM delivery_orders").fetchone()[0]
    n_delivered = conn.execute("SELECT COUNT(*) FROM delivery_orders WHERE status='delivered'").fetchone()[0]
    first, last = conn.execute("SELECT MIN(placed_ts), MAX(placed_ts) FROM delivery_orders").fetchone()
    period = f"{to_local(first):%b %d} – {to_local(last):%b %d, %Y}"
    matched = match_stats["exact_ref"] + match_stats["time_amount"]
    at_risk = sum(r["dollars_at_risk"] for r in queue)
    today = [r for r in queue if r["tier"] == "Act today"]

    kpis = f"""<div class="kpis">
<div class="card kpi"><div class="v">{n_orders}</div><div class="l">platform orders ({n_delivered} delivered)</div></div>
<div class="card kpi"><div class="v">{matched / n_orders:.1%}</div><div class="l">matched to a POS check</div></div>
<div class="card kpi"><div class="v">{money(at_risk)}</div><div class="l">estimated at risk across {len(queue)} exceptions</div></div>
<div class="card kpi"><div class="v">{len(today)}</div><div class="l">exceptions to handle today ({money(sum(r['dollars_at_risk'] for r in today))})</div></div>
</div>"""

    charts = f"""<div class="charts">
{bar_chart(patterns['missing_by_hour'], 'Orders missing from the POS, by hour', 'Share of delivered platform orders with no POS check. Hover a bar for counts.')}
{bar_chart(patterns['late_by_hour'], 'Late deliveries, by hour', 'Share of delivered orders 15+ min past the promised time.')}
</div>"""

    q = quality
    dq = f"""<div class="card"><dl>
<dt>Platform rows in export</dt><dd>{q['platform_rows_raw']}</dd>
<dt>Duplicate platform rows dropped</dt><dd>{q['platform_duplicate_rows_dropped']}</dd>
<dt>POS checks in export (all channels)</dt><dd>{q['pos_rows_raw']}</dd>
<dt>Delivery-channel POS checks</dt><dd>{q['pos_delivery_checks']}</dd>
<dt>…with a platform reference typed in</dt><dd>{q['pos_delivery_checks_with_ref']}</dd>
<dt>…reference needed cleaning (case, prefix)</dt><dd>{q['pos_refs_normalized']}</dd>
<dt>Matched by reference</dt><dd>{match_stats['exact_ref']}</dd>
<dt>Matched by time + amount (fallback)</dt><dd>{match_stats['time_amount']}</dd>
</dl></div>"""
    if scores:
        checks = []
        for t, s in scores["exceptions"].items():
            extra = f" (+{s['false_alarms']} false)" if s["false_alarms"] else ""
            checks.append(f"<dt>{TYPE_LABEL[t]}: caught / planted</dt><dd>{s['caught']} / {s['expected']}{extra}</dd>")
        dq += f"""<div class="card"><p style="margin-top:0"><b>Checked against the synthetic answer key</b></p>
<dl><dt>Match precision</dt><dd>{scores['match_precision']:.1%}</dd>
<dt>Match recall</dt><dd>{scores['match_recall']:.1%}</dd>""" + "".join(checks        ) + """</dl><p class="muted" style="margin-bottom:0">Only possible because the data is generated.
Real data has no answer key, so every fallback match is listed in <span class="mono">output/matched_orders.csv</span>
for spot checks.</p></div>"""

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Delivery Reconciliation</title>
<style>{CSS}</style></head>
<body><main>
<header><div><h1>Delivery order reconciliation</h1>
<p class="sub">Delivery platform vs POS &middot; {period} &middot; as of {as_of:%a %b %d, %I:%M %p}</p></div>
<span class="badge">Portfolio prototype &middot; synthetic data</span></header>
{kpis}
<h2>Decisions for this week</h2>
<div class="decisions">{decision_cards(patterns)}</div>
<h2>Where it happens</h2>
{charts}
<h2>Work queue &middot; top {TOP_N} of {len(queue)}</h2>
{queue_table(queue)}
<p class="muted">Score = dollars at risk &times; type weight &times; recency (1.5&times; if under {config.FRESH_DAYS} days old,
0.5&times; if older than the assumed {config.DISPUTE_WINDOW_DAYS}-day dispute window).
Full list: <span class="mono">output/exception_queue.csv</span>.</p>
<h2>Exceptions by type</h2>
{type_summary(queue)}
<h2>Data quality &amp; matching</h2>
<div class="split">{dq}</div>
<footer>Generated by <span class="mono">python run.py</span>. All orders, prices and IDs are synthetic.</footer>
</main></body></html>
"""
    path = config.OUTPUT_DIR / "manager_view.html"
    path.write_text(html)
    return path
