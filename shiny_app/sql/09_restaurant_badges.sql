-- =====================================================================
-- ⚠️  DRAFT — parked feature. Built now since it's a cheap, no-schema-
-- change VIEW, but not wired into the Shiny UI yet. Ready whenever
-- the team wants to use it.
--
-- v_restaurant_badges: computed local-flavor labels for restaurants,
-- based on rating + review_count (no manual curation needed — labels
-- update automatically as data changes).
--
-- NOTE: property and activity don't currently have both a rating AND a
-- review_count column, so this same formula can't be replicated for
-- them as-is — would need those columns added first if the team wants
-- badges there too later.
--
-- Thresholds (data-driven, based on this dataset's actual distribution:
-- review_count ranges 190-5200, Q1=410, median=630, Q3=1105 — the first
-- version of this view used a guessed absolute cutoff (<200) that turned
-- out to be below the dataset's own minimum, so nothing ever qualified
-- as "Hidden gem". Recalibrated to use quartiles instead, which stays
-- correct even as more restaurants get added later):
--   Hidden gem   = rating >= 4.5 AND review_count < Q1   (great, under the radar)
--   Must try     = rating >= 4.5 AND review_count >= Q3  (great, and everyone knows it)
--   Local hero   = rating >= 4.2 AND review_count between Q1 and Q3 (broadly loved staple)
-- =====================================================================

CREATE OR REPLACE VIEW v_restaurant_badges AS
WITH stats AS (
    SELECT
        percentile_cont(0.25) WITHIN GROUP (ORDER BY review_count) AS q1,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY review_count) AS q3
    FROM restaurant
)
SELECT
    r.restaurant_id,
    r.name,
    r.zone_id,
    r.cuisine_id,
    r.price_range,
    r.rating,
    r.review_count,
    CASE
        WHEN r.rating >= 4.5 AND r.review_count < s.q1                          THEN 'Hidden gem'
        WHEN r.rating >= 4.5 AND r.review_count >= s.q3                         THEN 'Must try'
        WHEN r.rating >= 4.2 AND r.review_count BETWEEN s.q1 AND s.q3           THEN 'Local hero'
        ELSE NULL
    END AS badge
FROM restaurant r
CROSS JOIN stats s;
