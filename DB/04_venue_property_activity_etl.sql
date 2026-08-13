-- =====================================================================
-- Venue / Property / Activity ETL
-- Run AFTER 01_schema.sql, 02_load_lookup_tables.sql (venue/property/
-- restaurant/activity all have a zone_id FK into location_zone, which
-- must be populated first), AND 03_artist_etl.sql. 
--
-- Documents the transform logic used for zone_id assignment
-- across the three "has a physical location" tables. 
-- =====================================================================


-- =====================================================================
-- PART 1 VENUE (manual, curated, 5 rows)
-- =====================================================================
-- No staging table needed at this scale. Zone assigned by simply
-- knowing where each venue physically is; is_casino_venue likewise
-- assigned by hand (see the earlier venue/casino-flag discussion).
-- Written as explicit INSERT statements rather than \copy so the
-- reasoning is visible in the script itself, not just in the CSV.
-- =====================================================================
DELETE FROM venue;

INSERT INTO venue (stage_name, stage_type, capacity, location_desc, address, latitude, longitude, zone_id, is_casino_venue) VALUES
    ('Jim Whelan Boardwalk Hall (Main Arena)', 'Main', 14770, 'Center of the AC Boardwalk (2301 Boardwalk)', '2301 Boardwalk, Atlantic City, NJ 08401', 39.3551, -74.4385, 1, FALSE),
    ('Hard Rock Live at Etess Arena',          'Main', 7000,  'Hard Rock Hotel & Casino (North Boardwalk)', '1000 Boardwalk, Atlantic City, NJ 08401', 39.3582, -74.4187, 1, TRUE),
    ('Ovation Hall',                           'Main', 5500,  'Ocean Casino Resort (Northernmost end of the Boardwalk)', '1000 Boardwalk, Atlantic City, NJ 08401', 39.3582, -74.4187, 1, TRUE),
    ('Borgata Event Center',                   'Main', 3200,  'Borgata Hotel Casino & Spa (Marina District)', '500 Boardwalk, Atlantic City, NJ 08401', 39.3629, -74.4147, 3, TRUE),
    ('Atlantic City Beach Grounds',            'Pop-up', 50000, 'Open beach adjacent to the Boardwalk (varies by event)', '777 Harrah''s Blvd, Atlantic City, NJ 08401', 39.3807, -74.4285, 1, FALSE);

-- =====================================================================
-- PART 2 PROPERTY (transform: staging -> rename/cast -> zone)
-- Raw source: raw_data/stay_raw.csv 
-- =====================================================================
DELETE FROM property;
DROP TABLE IF EXISTS property_raw_staging;

CREATE TABLE property_raw_staging (
    property_name         VARCHAR(150),
    address               VARCHAR(255),
    latitude              NUMERIC(9,6),
    longitude             NUMERIC(9,6),
    section_of_ac         VARCHAR(150),
    total_units           INT,
    star_rating           NUMERIC(2,1),
    price_min_usd         INT,
    price_max_usd         INT,
    price_tier            VARCHAR(20),
    has_casino_raw        VARCHAR(5),   -- 'Yes' / 'No' text in the raw file
    has_pool_raw          VARCHAR(10),  -- 'Yes' / 'No' / 'Unclear' in the raw file
    has_restaurant_raw    VARCHAR(5),
    monopoly_tier         VARCHAR(50),  
    property_type         VARCHAR(100),
    source_notes          TEXT,
    google_maps_link      VARCHAR(500)
);

\copy property_raw_staging FROM 'raw_data/stay_raw.csv' WITH (FORMAT csv, HEADER true);

-- TRANSFORM + LOAD: rename fields, cast Yes/No -> boolean, derive
-- zone_id from the section_of_ac text 

INSERT INTO property (
    property_name, address, latitude, longitude, section_of_ac, zone_id,
    total_units, star_rating, price_min_usd, price_max_usd, price_tier,
    has_casino, has_pool, has_restaurant, property_type, source_notes,
    google_maps_link
)
SELECT
    s.property_name, s.address, s.latitude, s.longitude, s.section_of_ac,
    CASE
        WHEN s.section_of_ac LIKE 'Boardwalk%' THEN 1
        WHEN s.section_of_ac LIKE 'Marina%'    THEN 3
        WHEN s.section_of_ac ILIKE '%regional%' THEN 4
        ELSE NULL
    END,
    s.total_units, s.star_rating, s.price_min_usd, s.price_max_usd, s.price_tier,
    (s.has_casino_raw = 'Yes'),
    CASE WHEN s.has_pool_raw IN ('Yes','No') THEN (s.has_pool_raw = 'Yes') ELSE NULL END,  -- 'Unclear' -> NULL, not FALSE
    (s.has_restaurant_raw = 'Yes'),
    s.property_type, s.source_notes, s.google_maps_link
FROM property_raw_staging s;


-- =====================================================================
-- PART 3 ACTIVITY zone_id backfill
-- =====================================================================
DELETE FROM activity;  

\copy activity (activity_id, activity_name, category_id, location_desc, latitude, longitude, duration_min, price_usd, description, genre_relevance, coord_status, price_basis) FROM 'raw_data/activity_raw.csv' WITH (FORMAT csv, HEADER true);

UPDATE activity a
SET zone_id = nz.zone_id
FROM (
    SELECT act.activity_id, a2.zone_id
    FROM activity act
    CROSS JOIN LATERAL (
        SELECT anchors.zone_id,
               sqrt(power((act.latitude - anchors.a_lat) * 69.0, 2) + power((act.longitude - anchors.a_lon) * 52.8, 2)) AS dist
        FROM (VALUES (1, 39.3582, -74.4187), (2, 39.3580, -74.4321), (3, 39.3776, -74.4357)) AS anchors(zone_id, a_lat, a_lon)
        ORDER BY dist ASC
        LIMIT 1
    ) a2
) nz
WHERE a.activity_id = nz.activity_id;
