-- =====================================================================
-- Sponsor + Song ETL
-- Run AFTER 03_artist_etl.sql (song depends on artist being loaded)
-- =====================================================================


-- =====================================================================
-- PART 1 SPONSOR (transform: drop tier_id)
-- Raw source: raw_data/sponsor_raw.csv (50 rows). Raw carries a `tier_id` 
-- column that the final schema deliberately does not have 
-- =====================================================================
DROP TABLE IF EXISTS sponsor_raw_staging;

CREATE TABLE sponsor_raw_staging (
    sponsor_id        VARCHAR(10),
    tier_id           VARCHAR (10),
    sponsor_name      VARCHAR(150),
    category_type     VARCHAR(50),
    investment_usd    INT,
    activation_desc   TEXT,
    booth_location    VARCHAR(150),
    contact_email     VARCHAR(150),
    contract_status   VARCHAR(20),
    logo_url          VARCHAR(500)
);

\copy sponsor_raw_staging FROM 'raw_data/sponsor_raw.csv' WITH (FORMAT csv, HEADER true);

DELETE FROM sponsor;

INSERT INTO sponsor (
    sponsor_id, sponsor_name, category_type, investment_usd,
    activation_desc, booth_location, contact_email, contract_status, logo_url
)
SELECT
    sponsor_id, sponsor_name, category_type, investment_usd,
    activation_desc, booth_location, contact_email, contract_status, logo_url
FROM sponsor_raw_staging;


-- =====================================================================
-- PART 2 — SONG (transform: filter to curated 30 artists, join
-- artist_id by name, drop artist_name per 3NF)
-- Raw source: raw_data/songs.csv 
-- =====================================================================
DROP TABLE IF EXISTS song_raw_staging;

CREATE TABLE song_raw_staging (
    artist_name          VARCHAR(150),
    track_name           VARCHAR(255),
    spotify_track_url    VARCHAR(255),
    streams              BIGINT
);

\copy song_raw_staging FROM 'raw_data/songs_raw.csv' WITH (FORMAT csv, HEADER true);

DELETE FROM song;

INSERT INTO song (song_id, artist_id, track_name, spotify_track_url, streams)
SELECT
    'S' || LPAD(ROW_NUMBER() OVER (ORDER BY a.artist_id, s.track_name)::TEXT, 4, '0'),
    a.artist_id,
    s.track_name,
    s.spotify_track_url,
    s.streams
FROM song_raw_staging s
JOIN artist a ON a.artist_name = s.artist_name;