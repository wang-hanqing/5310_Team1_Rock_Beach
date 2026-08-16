-- =====================================================================
-- Chance card draw logic
-- Run AFTER 01_schema.sql, 05_itinerary_logic.sql (needs v_attendee_downtime)
-- and coupon data loaded.
--
-- v_downtime_chance_cards: the actual "deck" the Draw Chance button pulls
-- from — restaurants/activities that (a) have a coupon attached and
-- (b) fit the attendee's current downtime gap (same fit rules as the
-- plain recommendation views: duration/mealtime window). The Shiny app
-- draws a card with: SELECT * FROM v_downtime_chance_cards
-- WHERE attendee_id = $1 ORDER BY random() LIMIT 1
--
-- sponsor_name is LEFT JOINed in (not every coupon has a sponsor — see
-- 06_load_remaining_data.sql's 7-of-14 sponsor pairing), so it's NULL
-- for unsponsored deals rather than excluding them.
--
-- Uses DROP + CREATE (not CREATE OR REPLACE) because Postgres won't let
-- OR REPLACE reorder/insert columns in the middle of an existing view's
-- column list — only append at the end. DROP first sidesteps that
-- restriction entirely, regardless of where columns get added later.
-- =====================================================================

DROP VIEW IF EXISTS v_downtime_chance_cards;

CREATE VIEW v_downtime_chance_cards AS
SELECT
    d.attendee_id,
    d.day_id,
    d.gap_start,
    d.gap_end,
    d.gap_minutes,
    'restaurant'      AS item_type,
    r.restaurant_id::TEXT AS item_id,
    r.name                AS item_name,
    c.coupon_id,
    c.coupon_desc,
    c.discount_label,
    sp.sponsor_name        AS sponsor_name,
    r.yelp_url              AS item_url,
    ROUND(
        SQRT(
            POWER((r.latitude  - d.stage_lat) * 69.0, 2) +
            POWER((r.longitude - d.stage_lon) * 52.8, 2)
        )::numeric, 1
    ) AS approx_miles_from_stage
FROM v_attendee_downtime d
JOIN restaurant r
  ON (
       (r.cuisine_id IN (1,2,3)
        AND d.gap_minutes >= 30
        AND (
              (d.gap_start::time, d.gap_end::time) OVERLAPS (TIME '11:00', TIME '14:00')
           OR (d.gap_start::time, d.gap_end::time) OVERLAPS (TIME '17:00', TIME '21:00')
            )
       )
       OR
       (r.cuisine_id = 4 AND d.gap_minutes >= 20)
     )
JOIN coupon c ON c.item_type = 'restaurant' AND c.restaurant_id = r.restaurant_id
LEFT JOIN sponsor sp ON sp.sponsor_id = c.sponsor_id

UNION ALL

SELECT
    d.attendee_id,
    d.day_id,
    d.gap_start,
    d.gap_end,
    d.gap_minutes,
    'activity'      AS item_type,
    a.activity_id::TEXT AS item_id,
    a.activity_name     AS item_name,
    c.coupon_id,
    c.coupon_desc,
    c.discount_label,
    sp.sponsor_name  AS sponsor_name,
    NULL               AS item_url,  -- activity has no url field in this schema
    ROUND(
        SQRT(
            POWER((a.latitude  - d.stage_lat) * 69.0, 2) +
            POWER((a.longitude - d.stage_lon) * 52.8, 2)
        )::numeric, 1
    ) AS approx_miles_from_stage
FROM v_attendee_downtime d
JOIN activity a ON a.duration_min <= d.gap_minutes
JOIN coupon c ON c.item_type = 'activity' AND c.activity_id = a.activity_id
LEFT JOIN sponsor sp ON sp.sponsor_id = c.sponsor_id;
