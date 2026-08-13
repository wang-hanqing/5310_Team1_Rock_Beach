-- =====================================================================
-- Artist ETL: raw 85-artist master list -> final 30-artist lineup
-- Run AFTER 01_schema.sql, BEFORE 06_load_remaining_data.sql's other \copy
-- commands (this replaces \copy artist FROM 'artist.csv' with an
-- explicit, auditable extract -> curate -> transform -> load sequence).
--
-- HOW TO RUN (psql, from the project folder containing raw_data/):
--   \i 03_artist_etl.sql
-- (the \copy this needs is embedded in the file itself below, no
-- separate step required.)
--
-- WHY THIS FILE EXISTS: clean_data/artist.csv looks like a plain load,
-- but it is NOT raw data loaded as-is. Two real transform decisions
-- happened between raw_data/artists.xlsx (92 rows / 85-artist list) and
-- the final 30-artist lineup:
--   1. EXTRACT: only 30 of the 85 artists were selected into the final
--      lineup (team curatorial choice, not a formula).
--   2. TRANSFORM: for 20 of those 30, the final `tier` (Headliner /
--      Support / Rising) does NOT match the tier implied by the raw
--      Spotify monthly-listener thresholds documented in the raw file
--      (Headliner = 50M+, Support = 20-50M, Rising = under 20M). Tier
--      was manually reassigned by the team for lineup/genre balance.
-- Both steps are made explicit and re-runnable below instead of being
-- silently baked into a static clean CSV.
--
-- DATA NOTE: raw_data/artists.xlsx and raw_data/artists_raw.csv were
-- corrected directly at the source (artist_id A023 <-> A027 swapped,
-- so A023 = Green Day and A027 = One Direction consistently) — Green
-- Day replaced One Direction in the final lineup, and both files now
-- agree on that with no separate swap step needed here.
-- =====================================================================

-- ---------------------------------------------------------------------
-- STEP 1 (EXTRACT): staging table matching the raw file's structure.
-- Raw source: raw_data/artists.xlsx ("Artists" sheet), already exported
-- to raw_data/artists_raw.csv (85 rows) alongside this script.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS artist_raw_staging;

CREATE TABLE artist_raw_staging (
    artist_id           VARCHAR(10),
    artist_name         VARCHAR(150),
    genre               VARCHAR(100),
    sub_genre           VARCHAR(150),
    is_crossover        BOOLEAN,
    crossover_note       VARCHAR(255),
    origin_city           VARCHAR(150),
    bio_short              TEXT,
    profile_image_url       VARCHAR(500),
    spotify_artist_id         VARCHAR(50),
    spotify_url                 VARCHAR(255),
    monthly_listeners             VARCHAR(20),   -- raw has commas, e.g. '131,256,019'; kept as text on purpose
    raw_tier                        VARCHAR(20),  -- the Spotify-threshold tier from the raw file (NOT final)
    stage                             VARCHAR(50),
    day                                 VARCHAR(50),
    time_slot                            VARCHAR(50)
);

\copy artist_raw_staging FROM 'raw_data/artists_raw.csv' WITH (FORMAT csv, HEADER true);

-- ---------------------------------------------------------------------
-- STEP 2 (EXTRACT, curated): the 30 artist_ids the team selected out of
-- the 85 for the final lineup. This list IS the transform — it is a
-- deliberate editorial choice, not derivable from any column in the
-- raw data, so it is written out explicitly rather than hidden in a
-- WHERE clause pretending to be a formula.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS artist_selected_lineup;

CREATE TABLE artist_selected_lineup (
    artist_id VARCHAR(10) PRIMARY KEY
);

INSERT INTO artist_selected_lineup (artist_id) VALUES
    ('A001'), ('A002'), ('A003'), ('A004'), ('A005'),
    ('A006'), ('A007'), ('A008'), ('A009'), ('A010'),
    ('A011'), ('A012'), ('A013'), ('A014'), ('A015'),
    ('A016'), ('A017'), ('A018'), ('A020'), ('A021'),
    ('A022'), ('A024'), ('A025'), ('A031'), ('A065'),
    ('A066'), ('A064'), ('A067'), ('A068'), ('A023');

-- ---------------------------------------------------------------------
-- STEP 3 (LOAD): load the 30 curated artists from staging into the real
-- `artist` table, carrying the raw tier over for now — it gets
-- overridden for the 20 reassigned artists in Step 4.
-- ---------------------------------------------------------------------
INSERT INTO artist (
    artist_id, artist_name, genre, sub_genre, is_crossover,
    crossover_note, origin_city, bio_short, profile_image_url,
    spotify_artist_id, spotify_url, tier
)
SELECT
    s.artist_id, s.artist_name, s.genre, s.sub_genre, s.is_crossover,
    s.crossover_note, s.origin_city, s.bio_short, s.profile_image_url,
    s.spotify_artist_id, s.spotify_url, s.raw_tier
FROM artist_raw_staging s
JOIN artist_selected_lineup l ON l.artist_id = s.artist_id;

-- ---------------------------------------------------------------------
-- STEP 4 (TRANSFORM): explicit tier overrides. These 20 artists'
-- final tier was reassigned by the team away from the raw
-- Spotify-listener-threshold tier, for lineup/genre balance across the
-- 3-day festival. Documented here instead of silently differing from
-- the raw source with no explanation.
-- ---------------------------------------------------------------------
UPDATE artist a
SET tier = v.new_tier
FROM (VALUES
    ('A003', 'Support'),
    ('A004', 'Support'),
    ('A008', 'Support'),
    ('A009', 'Support'),
    ('A010', 'Support'),
    ('A011', 'Rising'),
    ('A012', 'Support'),
    ('A013', 'Support'),
    ('A014', 'Support'),
    ('A015', 'Support'),
    ('A016', 'Rising'),
    ('A017', 'Rising'),
    ('A018', 'Rising'),
    ('A020', 'Rising'),
    ('A021', 'Rising'),
    ('A022', 'Rising'),
    ('A024', 'Rising'),
    ('A025', 'Rising'),
    ('A031', 'Headliner'),
    ('A023', 'Rising')
) AS v(artist_id, new_tier)
WHERE a.artist_id = v.artist_id;

-- ---------------------------------------------------------------------
-- Sanity check: confirm final counts match the intended 6/9/15 split.
-- ---------------------------------------------------------------------
-- SELECT tier, COUNT(*) FROM artist GROUP BY tier;
-- Expect: Headliner=6, Support=9, Rising=15


