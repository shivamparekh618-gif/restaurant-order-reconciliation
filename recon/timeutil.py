from datetime import datetime, timedelta, timezone

from . import config


def local_tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(config.RESTAURANT_TZ)
    except Exception:  # no tz database available
        return timezone(timedelta(hours=config.FALLBACK_UTC_OFFSET_HOURS))


POS_FORMATS = ("%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S")


def parse_platform_ts(text):
    """Platform timestamps are ISO-8601 UTC, e.g. 2026-08-03T18:42:10Z."""
    if not text:
        return None
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def parse_pos_ts(text):
    """POS timestamps are local time in one of two formats depending on the terminal."""
    text = text.strip()
    for fmt in POS_FORMATS:
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return int(naive.replace(tzinfo=local_tz()).timestamp())
    raise ValueError(f"unrecognised POS timestamp: {text!r}")


def to_local(epoch):
    return datetime.fromtimestamp(epoch, tz=local_tz())
