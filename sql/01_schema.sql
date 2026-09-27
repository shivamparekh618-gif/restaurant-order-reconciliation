-- All timestamps are stored as UTC epoch seconds and all money as integer cents,
-- so the two systems can be compared directly.

CREATE TABLE delivery_orders (
    platform_order_id TEXT PRIMARY KEY,
    placed_ts         INTEGER NOT NULL,
    promised_ts       INTEGER NOT NULL,
    delivered_ts      INTEGER,            -- NULL when cancelled
    status            TEXT NOT NULL,      -- 'delivered' | 'cancelled'
    items             TEXT,
    subtotal_cents    INTEGER NOT NULL,
    total_cents       INTEGER NOT NULL
);

CREATE TABLE pos_checks (
    check_id        TEXT PRIMARY KEY,
    opened_ts       INTEGER NOT NULL,
    channel         TEXT NOT NULL,        -- 'DELIVERY' | 'DINE_IN' | 'TAKEOUT'
    ext_ref         TEXT,                 -- normalized platform order id, if typed in
    items           TEXT,
    subtotal_cents  INTEGER NOT NULL,
    total_cents     INTEGER NOT NULL,
    voided          INTEGER NOT NULL
);

CREATE INDEX idx_pos_channel_time ON pos_checks (channel, opened_ts);

CREATE TABLE matches (
    platform_order_id TEXT UNIQUE,
    check_id          TEXT UNIQUE,
    match_method      TEXT NOT NULL,      -- 'exact_ref' | 'time_amount'
    time_gap_s        INTEGER,
    amount_gap_cents  INTEGER
);
