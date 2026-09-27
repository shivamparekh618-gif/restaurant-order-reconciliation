-- Pass 1: the POS check carries the platform order id (after normalization).
INSERT INTO matches (platform_order_id, check_id, match_method, time_gap_s, amount_gap_cents)
SELECT d.platform_order_id,
       p.check_id,
       'exact_ref',
       ABS(p.opened_ts - d.placed_ts),
       ABS(p.subtotal_cents - d.subtotal_cents)
FROM delivery_orders d
JOIN pos_checks p
  ON p.ext_ref = d.platform_order_id
 AND p.channel = 'DELIVERY';
