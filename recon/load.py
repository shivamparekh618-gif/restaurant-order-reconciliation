"""Read the raw exports, clean them, and load them into SQLite.

Cleaning decisions are logged in a data-quality summary instead of being
applied silently, so a manager can see what was changed and why.
"""

import csv
import re
import sqlite3

from . import config
from .timeutil import parse_platform_ts, parse_pos_ts

REF_CODE = re.compile(r"^(?:DP)?[\s-]*([0-9A-F]{6})$")


def to_cents(text):
    text = text.strip().replace("$", "").replace(",", "")
    return int(round(float(text) * 100))


def normalize_ref(text):
    """Map the ways staff type a platform order ID onto one form.

    'DP-8F3A21', 'dp-8f3a21', '8F3A21' and 'DP 8F3A21' all become 'DP-8F3A21'.
    Anything else is treated as unusable and returns None.
    """
    match = REF_CODE.match(text.strip().upper())
    return f"DP-{match.group(1)}" if match else None


def normalize_channel(text):
    return text.strip().upper().replace(" ", "_")


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load(conn, delivery_path=config.DELIVERY_FILE, pos_path=config.POS_FILE):
    quality = {}
    conn.executescript((config.SQL_DIR / "01_schema.sql").read_text())

    raw_delivery = read_csv(delivery_path)
    seen, rows, dupes = set(), [], 0
    for r in raw_delivery:
        if r["platform_order_id"] in seen:
            dupes += 1
            continue
        seen.add(r["platform_order_id"])
        rows.append((
            r["platform_order_id"],
            parse_platform_ts(r["placed_at"]),
            parse_platform_ts(r["promised_at"]),
            parse_platform_ts(r["delivered_at"]),
            r["status"].strip().lower(),
            r["items"],
            to_cents(r["subtotal"]),
            to_cents(r["total"]),
        ))
    conn.executemany("INSERT INTO delivery_orders VALUES (?,?,?,?,?,?,?,?)", rows)
    quality["platform_rows_raw"] = len(raw_delivery)
    quality["platform_duplicate_rows_dropped"] = dupes

    raw_pos = read_csv(pos_path)
    rows, refs_present, refs_fixed, dollar_signs = [], 0, 0, 0
    for r in raw_pos:
        raw_ref = r["external_ref"].strip()
        ref = normalize_ref(raw_ref) if raw_ref else None
        if raw_ref:
            refs_present += 1
            if ref and ref != raw_ref:
                refs_fixed += 1
        dollar_signs += "$" in r["total"]
        rows.append((
            r["check_id"],
            parse_pos_ts(r["opened_at"]),
            normalize_channel(r["order_channel"]),
            ref,
            r["items"],
            to_cents(r["subtotal"]),
            to_cents(r["total"]),
            1 if r["voided"].strip().upper() == "Y" else 0,
        ))
    conn.executemany("INSERT INTO pos_checks VALUES (?,?,?,?,?,?,?,?)", rows)
    delivery_checks = [row for row in rows if row[2] == "DELIVERY"]
    quality["pos_rows_raw"] = len(raw_pos)
    quality["pos_delivery_checks"] = len(delivery_checks)
    quality["pos_delivery_checks_with_ref"] = refs_present
    quality["pos_refs_normalized"] = refs_fixed
    quality["pos_amounts_with_dollar_sign"] = dollar_signs
    return quality


def connect():
    return sqlite3.connect(":memory:")
