-- =====================================================================
-- Load remaining base data (restaurant + performance + coupon).
-- =====================================================================

-- ---- depends on location_zone (loaded by 02_load_lookup_tables.sql) ----
-- Loads from raw_data/restaurant_raw.csv, not clean_data — raw and
-- clean are identical column-for-column except est_cost_per_person_usd
-- (derived below), so an explicit column list lets \copy skip straight
-- past that one gap without needing a staging table.
DELETE FROM restaurant;  -- makes this script safe to re-run without duplicating rows
\copy restaurant (restaurant_id, name, address, city, st, zip, latitude, longitude, zone_id, cuisine_id, country, food_category, price_range, rating, review_count, opening_hours, is_casino_restaurant, yelp_url, google_maps_url) FROM 'raw_data/restaurant_raw.csv' WITH (FORMAT csv, HEADER true);

-- ---------------------------------------------------------------------
-- Backfill est_cost_per_person_usd from the raw price_range symbol.
-- Mapping is based on Atlantic City-specific per-person dining cost
-- research (shore-guide.com AC restaurant guide, 2026), using the
-- midpoint of each tier's real-world range:
--   $    -> $15-30/person   -> est. $22
--   $$   -> $30-50/person   -> est. $40
--   $$$  -> $50-80/person   -> est. $65
--   $$$$ -> $80+/person     -> est. $110 (open-ended tier, picked a
--                              representative fine-dining figure rather
--                              than leaving it unbounded)
-- This is a per-tier estimate for trip-budget math, not a claim about
-- any individual restaurant's actual menu prices.
-- ---------------------------------------------------------------------
UPDATE restaurant
SET est_cost_per_person_usd = CASE price_range
    WHEN '$'    THEN 22
    WHEN '$$'   THEN 40
    WHEN '$$$'  THEN 65
    WHEN '$$$$' THEN 110
    ELSE NULL
END;

-- =====================================================================
-- PERFORMANCE (transform: staging -> join by name -> load)
-- Raw source: raw_data/performance_raw.csv 
-- =====================================================================
DROP TABLE IF EXISTS performance_raw_staging;

CREATE TABLE performance_raw_staging (
    artist_name    VARCHAR(150),
    stage_name       VARCHAR(150),
    day_number         INT,
    day_date             DATE,
    day_theme              VARCHAR(150),
    start_time                TIME,
    end_time                    TIME
);

\copy performance_raw_staging FROM 'raw_data/performance_raw.csv' WITH (FORMAT csv, HEADER true);

DELETE FROM performance;  -- makes this script safe to re-run without duplicating rows

INSERT INTO performance (artist_id, stage_id, day_id, start_time, end_time)
SELECT a.artist_id, v.stage_id, d.day_id, s.start_time, s.end_time
FROM performance_raw_staging s
JOIN artist a ON a.artist_name = s.artist_name
JOIN venue v ON v.stage_name = s.stage_name
JOIN festival_day d ON d.day_number = s.day_number;

-- ---- depends on restaurant + activity ----
-- coupon has no raw source —these promo/deal descriptions were
-- written directly by the team as course-project content 

DELETE FROM coupon; 
\copy coupon FROM 'coupon.csv' WITH (FORMAT csv, HEADER true, NULL '');

-- ---------------------------------------------------------------------
-- Backfill sponsor_id for coupons with a clear, defensible brand fit.
-- This is a curatorial pairing (like the artist tier reassignment in
-- 03_artist_etl.sql), not derived from any data or formula — only 7 of
-- the 15 coupons get a sponsor; the rest are intentionally left
-- unsponsored rather than force-fitting a match that isn't real.
-- ---------------------------------------------------------------------
UPDATE coupon SET sponsor_id = 'SP11' WHERE coupon_id = 1;   -- 2-for-1 draft beers -> Heineken
UPDATE coupon SET sponsor_id = 'SP14' WHERE coupon_id = 8;   -- 2-for-1 well drinks -> Anheuser-Busch
UPDATE coupon SET sponsor_id = 'SP04' WHERE coupon_id = 10;  -- tasting flight -> Hennessy
UPDATE coupon SET sponsor_id = 'SP25' WHERE coupon_id = 11;  -- parasailing -> GoPro
UPDATE coupon SET sponsor_id = 'SP18' WHERE coupon_id = 12;  -- Monopoly Walking Tour souvenir map -> Hasbro, Inc. (makes Monopoly)
UPDATE coupon SET sponsor_id = 'SP09' WHERE coupon_id = 13;  -- vinyl discount -> Spotify
UPDATE coupon SET sponsor_id = 'SP01' WHERE coupon_id = 14;  -- skip-the-line pass -> American Express

-- attendee / ticket / attendee_performance / attendee_activity /
-- attendee_restaurant are intentionally left empty, populated at
-- runtime by real app usage, not seed data.
