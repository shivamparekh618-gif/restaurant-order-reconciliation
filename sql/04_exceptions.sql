-- One row per platform order with its matched POS check (if any).
CREATE VIEW order_view AS
SELECT d.*,
       m.check_id,
       m.match_method,
       p.opened_ts,
       p.subtotal_cents AS pos_subtotal_cents,
       p.total_cents    AS pos_total_cents,
       p.voided         AS pos_voided,
       p.items          AS pos_items
FROM delivery_orders d
LEFT JOIN matches m    ON m.platform_order_id = d.platform_order_id
LEFT JOIN pos_checks p ON p.check_id = m.check_id;

-- Every exception gets a dollar figure so they can be ranked on one scale.
CREATE TABLE exceptions AS

-- Customer paid through the platform, but the order never reached the POS.
-- Sales are under-reported and, often, the kitchen never saw the ticket.
SELECT 'MISSING_IN_POS' AS exception_type,
       platform_order_id, NULL AS check_id, placed_ts AS event_ts,
       total_cents AS dollars_at_risk_cents,
       'Delivered on platform, no POS check found' AS detail
FROM order_view
WHERE status = 'delivered' AND check_id IS NULL

UNION ALL
-- Platform cancelled the order, but the POS check is still live: food may have
-- been made for nothing and POS sales are over-stated.
SELECT 'CANCELLED_NOT_VOIDED', platform_order_id, check_id, placed_ts,
       pos_total_cents,
       'Cancelled on platform, POS check ' || check_id || ' not voided'
FROM order_view
WHERE status = 'cancelled' AND check_id IS NOT NULL AND pos_voided = 0

UNION ALL
-- Both systems have the order but disagree on the subtotal.
SELECT 'PRICE_MISMATCH', platform_order_id, check_id, placed_ts,
       ABS(subtotal_cents - pos_subtotal_cents),
       printf('Platform $%.2f vs POS $%.2f', subtotal_cents / 100.0, pos_subtotal_cents / 100.0)
FROM order_view
WHERE status = 'delivered' AND check_id IS NOT NULL
  AND ABS(subtotal_cents - pos_subtotal_cents) > :price_tol_cents

UNION ALL
-- Delivered well past the promised time. Only part of the order value is at
-- risk (a refund or credit), so it is scaled by an assumed refund rate.
SELECT 'LATE_DELIVERY', platform_order_id, check_id, placed_ts,
       CAST(ROUND(total_cents * :late_refund_rate) AS INTEGER),
       printf('%d min past promised time', (delivered_ts - promised_ts) / 60)
FROM order_view
WHERE status = 'delivered' AND delivered_ts - promised_ts > :late_threshold_s

UNION ALL
-- Rung in as a delivery order, but no platform order exists: a mis-keyed
-- channel, a phone order, or a test ticket.
SELECT 'POS_ONLY_DELIVERY', NULL, p.check_id, p.opened_ts,
       p.total_cents,
       'Delivery-channel POS check with no platform order'
FROM pos_checks p
WHERE p.channel = 'DELIVERY' AND p.voided = 0
  AND p.check_id NOT IN (SELECT check_id FROM matches);
