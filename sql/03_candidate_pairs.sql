-- Pass 2 candidates: for everything still unmatched, pair each platform order with
-- delivery-channel POS checks opened shortly after it with a similar subtotal.
-- A check that was rung in by hand is always opened *after* the platform order,
-- so we allow a small negative gap only to absorb clock drift between systems.
-- The one-to-one assignment is done in Python (recon/match.py).
SELECT d.platform_order_id,
       p.check_id,
       p.opened_ts - d.placed_ts                AS time_gap_s,
       ABS(p.subtotal_cents - d.subtotal_cents) AS amount_gap_cents
FROM delivery_orders d
JOIN pos_checks p
  ON p.channel = 'DELIVERY'
 AND p.opened_ts BETWEEN d.placed_ts - 60 AND d.placed_ts + :window_s
 AND ABS(p.subtotal_cents - d.subtotal_cents) <= :amount_tol_cents
WHERE d.platform_order_id NOT IN (SELECT platform_order_id FROM matches)
  AND p.check_id NOT IN (SELECT check_id FROM matches)
ORDER BY d.platform_order_id;
