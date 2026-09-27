"""Generate two weeks of synthetic delivery-platform and POS data.

The data is fake but the problems in it are the ones that show up in real
restaurant exports:

* the two systems disagree on timezone and timestamp format
* staff type the platform order ID into the POS inconsistently, or not at all
* a tablet that drops orders during the Friday/Saturday dinner rush
* a menu price changed in the POS but never pushed to the platform
* cancelled platform orders that were already rung in and never voided
* a few checks rung as "delivery" that have no platform order
* the platform export repeats some rows

A ground-truth file is written alongside so the matching logic can be scored.
It exists only because the data is synthetic; the pipeline never reads it.
"""

import csv
import random
from datetime import datetime, timedelta, timezone

from . import config
from .timeutil import local_tz

SEED = 42
START_DATE = datetime(2026, 8, 3)  # a Monday
DAYS = 14
TAX_RATE = 0.095

# POS prices. The platform menu is the same except where noted below.
MENU = {
    "Chicken Tikka Bowl": 13.50,
    "Butter Chicken Plate": 16.00,
    "Chana Masala Bowl": 12.00,
    "Paneer Wrap": 11.50,
    "Dal Makhani": 10.00,
    "Samosa (2)": 6.00,
    "Garlic Naan": 3.50,
    "Mango Lassi": 5.00,
}
# The POS raised Chicken Tikka Bowl to $14.50 on day 6, the platform kept $13.50.
PRICE_CHANGE_DAY = 5
PRICE_CHANGE_ITEM = "Chicken Tikka Bowl"
PRICE_CHANGE_NEW_POS_PRICE = 14.50

HOURLY_WEIGHTS = {11: 5, 12: 11, 13: 8, 14: 3, 15: 2, 16: 3, 17: 6, 18: 11, 19: 12, 20: 7, 21: 3}


def _is_rush(dt_local):
    return dt_local.weekday() in (4, 5) and 18 <= dt_local.hour <= 20


def _pick_items(rng):
    n = rng.choices([1, 2, 3, 4, 5], weights=[20, 35, 25, 12, 8])[0]
    return [rng.choice(list(MENU)) for _ in range(n)]


def _price(items, day_index, side):
    total = 0.0
    for item in items:
        price = MENU[item]
        if side == "pos" and item == PRICE_CHANGE_ITEM and day_index >= PRICE_CHANGE_DAY:
            price = PRICE_CHANGE_NEW_POS_PRICE
        total += price
    return round(total, 2)


def _money(value, rng, messy):
    text = f"{value:.2f}"
    return f"${text}" if messy and rng.random() < 0.10 else text


def _pos_timestamp(dt_utc, rng):
    """POS terminal 1 exports US-style 12h time; terminal 2 exports ISO local."""
    local = dt_utc.astimezone(local_tz())
    if rng.random() < 0.2:
        return local.strftime("%Y-%m-%d %H:%M:%S"), "T2"
    return local.strftime("%m/%d/%Y %I:%M %p"), "T1"


def _messy_ref(order_id, rng):
    roll = rng.random()
    code = order_id.split("-")[1]
    if roll < 0.65:
        return order_id
    if roll < 0.70:
        return order_id.lower()
    if roll < 0.73:
        return code
    if roll < 0.75:
        return f"DP {code}"
    return ""


def generate(seed=SEED):
    rng = random.Random(seed)
    tz = local_tz()
    delivery_rows, pos_rows, truth_rows = [], [], []
    used_codes = set()
    # Checks get real IDs at the end, in the order they were opened.
    temp_seq = 0

    def next_check_id():
        nonlocal temp_seq
        temp_seq += 1
        return f"tmp{temp_seq}"

    for day in range(DAYS):
        day_local = START_DATE + timedelta(days=day)
        weekend = day_local.weekday() in (4, 5, 6)
        n_delivery = rng.randint(55, 75) if weekend else rng.randint(38, 55)
        hours = rng.choices(list(HOURLY_WEIGHTS), weights=list(HOURLY_WEIGHTS.values()), k=n_delivery)

        events = []
        for hour in hours:
            local = day_local.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))
            events.append(local.replace(tzinfo=tz))
        events.sort()

        for placed_local in events:
            placed_utc = placed_local.astimezone(timezone.utc)
            code = None
            while code is None or code in used_codes:
                code = "".join(rng.choice("0123456789ABCDEF") for _ in range(6))
            used_codes.add(code)
            order_id = f"DP-{code}"

            items = _pick_items(rng)
            platform_subtotal = _price(items, day, "platform")
            pos_subtotal = _price(items, day, "pos")
            issues = []

            # an item was 86'd and removed from the POS ticket but not the platform order
            if rng.random() < 0.008 and len(items) > 1:
                removed = items[-1]
                pos_subtotal = round(pos_subtotal - MENU[removed], 2)
                issues.append("ITEM_REMOVED")

            rush = _is_rush(placed_local)
            status = "cancelled" if rng.random() < 0.04 else "delivered"
            promised = placed_utc + timedelta(minutes=35)
            delivered = None
            if status == "delivered":
                late_p = 0.22 if rush else 0.05
                if rng.random() < late_p:
                    delivered = promised + timedelta(minutes=rng.randint(17, 42))
                    issues.append("LATE")
                else:
                    delivered = placed_utc + timedelta(minutes=max(18, rng.gauss(30, 4)))

            # Did the order make it into the POS?
            missing_p = 0.12 if rush else 0.012
            in_pos = rng.random() >= missing_p
            if status == "cancelled":
                in_pos = rng.random() < 0.6
            pos_voided = False
            check_id = ""
            if in_pos:
                check_id = next_check_id()
                ref = _messy_ref(order_id, rng)
                delay = rng.randint(20, 150) if ref else rng.randint(60, 360)
                opened = placed_utc + timedelta(seconds=delay)
                ts_text, terminal = _pos_timestamp(opened, rng)
                if status == "cancelled":
                    pos_voided = rng.random() < 0.5
                    if not pos_voided:
                        issues.append("CANCELLED_NOT_VOIDED")
                pos_rows.append({
                    "check_id": check_id,
                    "_opened": opened,
                    "opened_at": ts_text,
                    "terminal": terminal,
                    "order_channel": rng.choice(["Delivery", "DELIVERY", "delivery "]),
                    "external_ref": ref,
                    "items": "; ".join(items if "ITEM_REMOVED" not in issues else items[:-1]),
                    "subtotal": _money(pos_subtotal, rng, True),
                    "tax": _money(round(pos_subtotal * TAX_RATE, 2), rng, True),
                    "total": _money(pos_subtotal + round(pos_subtotal * TAX_RATE, 2), rng, True),
                    "voided": "Y" if pos_voided else "N",
                })
            elif status == "delivered":
                issues.append("MISSING_IN_POS")

            if in_pos and status == "delivered" and abs(pos_subtotal - platform_subtotal) > 0.5:
                issues.append("PRICE_MISMATCH")

            row = {
                "platform_order_id": order_id,
                "placed_at": placed_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "promised_at": promised.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "delivered_at": delivered.strftime("%Y-%m-%dT%H:%M:%SZ") if delivered else "",
                "status": status,
                "items": "; ".join(items),
                "subtotal": f"{platform_subtotal:.2f}",
                "tax": f"{round(platform_subtotal * TAX_RATE, 2):.2f}",
                "total": f"{platform_subtotal + round(platform_subtotal * TAX_RATE, 2):.2f}",
            }
            delivery_rows.append(row)
            # the platform export occasionally repeats a row across pages
            if rng.random() < 0.01:
                delivery_rows.append(dict(row))
                issues.append("DUPLICATE_EXPORT_ROW")
            truth_rows.append({
                "platform_order_id": order_id,
                "check_id": check_id,
                "issues": "|".join(issues),
            })

        # dine-in and takeout checks share the POS export and must be ignored
        for _ in range(rng.randint(45, 70)):
            hour = rng.choices(list(HOURLY_WEIGHTS), weights=list(HOURLY_WEIGHTS.values()))[0]
            local = day_local.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59), tzinfo=tz)
            items = _pick_items(rng)
            subtotal = _price(items, day, "pos")
            opened = local.astimezone(timezone.utc)
            ts_text, terminal = _pos_timestamp(opened, rng)
            pos_rows.append({
                "check_id": next_check_id(),
                "_opened": opened,
                "opened_at": ts_text,
                "terminal": terminal,
                "order_channel": rng.choice(["Dine In", "Takeout"]),
                "external_ref": "",
                "items": "; ".join(items),
                "subtotal": _money(subtotal, rng, True),
                "tax": _money(round(subtotal * TAX_RATE, 2), rng, True),
                "total": _money(subtotal + round(subtotal * TAX_RATE, 2), rng, True),
                "voided": "Y" if rng.random() < 0.01 else "N",
            })

        # a phone order or test ticket rung under the delivery channel
        if rng.random() < 0.5:
            local = day_local.replace(hour=rng.choice([12, 15, 19]), minute=rng.randint(0, 59), tzinfo=tz)
            items = _pick_items(rng)
            subtotal = _price(items, day, "pos")
            opened = local.astimezone(timezone.utc)
            ts_text, terminal = _pos_timestamp(opened, rng)
            check_id = next_check_id()
            pos_rows.append({
                "check_id": check_id,
                "_opened": opened,
                "opened_at": ts_text,
                "terminal": terminal,
                "order_channel": "Delivery",
                "external_ref": "",
                "items": "; ".join(items),
                "subtotal": _money(subtotal, rng, True),
                "tax": _money(round(subtotal * TAX_RATE, 2), rng, True),
                "total": _money(subtotal + round(subtotal * TAX_RATE, 2), rng, True),
                "voided": "N",
            })
            truth_rows.append({"platform_order_id": "", "check_id": check_id, "issues": "POS_ONLY_DELIVERY"})

    pos_rows.sort(key=lambda r: r["_opened"])
    real_ids, seq = {}, 104000
    for row in pos_rows:
        del row["_opened"]
        seq += rng.randint(1, 3)
        real_ids[row["check_id"]] = f"CHK-{seq}"
        row["check_id"] = real_ids[row["check_id"]]
    for row in truth_rows:
        row["check_id"] = real_ids.get(row["check_id"], "")
    return delivery_rows, pos_rows, truth_rows


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    delivery, pos, truth = generate()
    _write(config.DELIVERY_FILE, delivery)
    _write(config.POS_FILE, pos)
    _write(config.TRUTH_FILE, truth)
    print(f"wrote {len(delivery)} platform rows, {len(pos)} POS rows to {config.DATA_DIR}")


if __name__ == "__main__":
    main()
