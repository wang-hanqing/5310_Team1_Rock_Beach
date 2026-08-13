-- Rock & Beach Festival Database Schema 
-- 3NF-compliant design
-- Scope: 30 featured artists, 5 venues, 3-day festival (Aug 21-23, 2026)

-- Drop tables if re-running (reverse dependency order)
DROP TABLE IF EXISTS vote CASCADE;  -- feature dropped: no song voting in this version
DROP TABLE IF EXISTS attendee_activity CASCADE;
DROP TABLE IF EXISTS attendee_restaurant CASCADE;
DROP TABLE IF EXISTS coupon CASCADE;
DROP TABLE IF EXISTS attendee_performance CASCADE;
DROP TABLE IF EXISTS ticket CASCADE;
DROP TABLE IF EXISTS ticket_type CASCADE;
DROP TABLE IF EXISTS attendee CASCADE;
DROP TABLE IF EXISTS performance CASCADE;
DROP TABLE IF EXISTS festival_day CASCADE;
DROP TABLE IF EXISTS song CASCADE;
DROP TABLE IF EXISTS artist CASCADE;
DROP TABLE IF EXISTS venue CASCADE;
DROP TABLE IF EXISTS activity CASCADE;
DROP TABLE IF EXISTS activity_category CASCADE;
DROP TABLE IF EXISTS restaurant CASCADE;
DROP TABLE IF EXISTS cuisine_type CASCADE;
DROP TABLE IF EXISTS location_zone CASCADE;
DROP TABLE IF EXISTS property CASCADE;
DROP TABLE IF EXISTS sponsor CASCADE;

-- =====================================================================
-- 1. ARTIST  (tier is an independent, classification of
--    Headliner/Support/Rising not derived from any other column)
-- =====================================================================
CREATE TABLE artist (
    artist_id           VARCHAR(10)   PRIMARY KEY,
    artist_name         VARCHAR(150)  NOT NULL,
    genre               VARCHAR(100),
    sub_genre           VARCHAR(150),
    is_crossover        BOOLEAN,
    crossover_note      VARCHAR(255),
    origin_city         VARCHAR(150),
    bio_short           TEXT,
    profile_image_url   VARCHAR(500),
    spotify_artist_id   VARCHAR(50),
    spotify_url         VARCHAR(255),
    tier                VARCHAR(20)  CHECK (tier IN ('Headliner','Support','Rising'))
);

-- =====================================================================
-- 2. SONG  
-- =====================================================================
CREATE TABLE song (
    song_id              VARCHAR(10)  PRIMARY KEY,
    artist_id            VARCHAR(10)  NOT NULL REFERENCES artist(artist_id),
    track_name           VARCHAR(255) NOT NULL,
    spotify_track_url    VARCHAR(255),
    streams              BIGINT
);

-- =====================================================================
-- 3. VENUE (Stage)
-- =====================================================================
CREATE TABLE venue (
    stage_id             SERIAL       PRIMARY KEY,
    stage_name           VARCHAR(150) NOT NULL,
    stage_type           VARCHAR(50),
    capacity             INT,
    location_desc        VARCHAR(255),
    address              VARCHAR(255),
    latitude             NUMERIC(9,6),
    longitude            NUMERIC(9,6),
    zone_id              INT,  -- FK to location_zone added below via ALTER TABLE,
                               -- since location_zone is created later in this script
    is_casino_venue      BOOLEAN  -- mirrors restaurant.is_casino_restaurant /
                                  -- property.has_casino, for the same
                                  -- orthogonal casino/non-casino filter
                                  -- within a zone (see zone_id discussion)
);

-- =====================================================================
-- 4. FESTIVAL_DAY  (3 days: Aug 21-23, 2026)
-- =====================================================================
CREATE TABLE festival_day (
    day_id                SERIAL       PRIMARY KEY,
    day_number            INT,
    day_date              DATE,
    day_theme             VARCHAR(150)
);

-- =====================================================================
-- 5. PERFORMANCE  (bridge table: which artist plays which stage/day/time)
-- =====================================================================
CREATE TABLE performance (
    performance_id        SERIAL       PRIMARY KEY,
    artist_id             VARCHAR(10)  NOT NULL REFERENCES artist(artist_id),
    stage_id              INT REFERENCES venue(stage_id),
    day_id                INT REFERENCES festival_day(day_id),
    start_time            TIME,
    end_time              TIME
);

-- =====================================================================
-- 6. LOCATION_ZONE  (referenced by RESTAURANT.zone_id)
-- =====================================================================
CREATE TABLE location_zone (
    zone_id                INT          PRIMARY KEY,
    zone_name              VARCHAR(50)  NOT NULL
);

-- now that location_zone exists, attach the FK on venue.zone_id
-- (added to support zone-based itinerary browsing — grouping performances
-- alongside restaurant/stay options within the same AC zone)
ALTER TABLE venue ADD CONSTRAINT fk_venue_zone
    FOREIGN KEY (zone_id) REFERENCES location_zone(zone_id);

-- =====================================================================
-- 7. CUISINE_TYPE  (referenced by RESTAURANT.cuisine_id)
--    NOTE: cuisine_id groups by dining FORMAT (inferred from data
--    pattern), not by nationality, country/food_category are kept
--    directly on RESTAURANT since they are independent, restaurant-
--    level facts, not derivable from cuisine_id.
-- =====================================================================
CREATE TABLE cuisine_type (
    cuisine_id             INT          PRIMARY KEY,
    cuisine_name           VARCHAR(100) NOT NULL,
    cuisine_category       VARCHAR(50)
);

-- =====================================================================
-- 8. RESTAURANT
-- =====================================================================
CREATE TABLE restaurant (
    restaurant_id          VARCHAR(10)  PRIMARY KEY,
    name                   VARCHAR(150) NOT NULL,
    address                VARCHAR(255),
    city                   VARCHAR(100),
    st                     CHAR(2),
    zip                    VARCHAR(10),
    latitude               NUMERIC(9,6),
    longitude              NUMERIC(9,6),
    zone_id                INT REFERENCES location_zone(zone_id),
    cuisine_id             INT REFERENCES cuisine_type(cuisine_id),
    country                VARCHAR(50),
    food_category          VARCHAR(50),
    price_range            VARCHAR(10),
    est_cost_per_person_usd NUMERIC(6,2),  
    rating                 NUMERIC(2,1),
    review_count           INT,
    opening_hours          VARCHAR(50),
    is_casino_restaurant   BOOLEAN,
    yelp_url               VARCHAR(500),
    google_maps_url        VARCHAR(500)
);

-- =====================================================================
-- 9. SPONSOR 
-- =====================================================================
CREATE TABLE sponsor (
    sponsor_id              VARCHAR(10)  PRIMARY KEY,
    sponsor_name            VARCHAR(150) NOT NULL,
    category_type           VARCHAR(50),
    investment_usd          INT,
    activation_desc         TEXT,
    booth_location          VARCHAR(150),
    contact_email           VARCHAR(150),
    contract_status         VARCHAR(20),
    logo_url                VARCHAR(500)
);

-- =====================================================================
-- 10. PROPERTY
-- =====================================================================
CREATE TABLE property (
    property_id              SERIAL        PRIMARY KEY,
    property_name            VARCHAR(150)  NOT NULL,
    address                  VARCHAR(255),
    latitude                 NUMERIC(9,6),
    longitude                NUMERIC(9,6),
    section_of_ac            VARCHAR(150),
    zone_id                  INT REFERENCES location_zone(zone_id),  -- nullable: a few properties are regional (outside AC proper) and don't fit any of the 3 zones
    total_units              INT,
    star_rating              NUMERIC(2,1),
    price_min_usd            INT,
    price_max_usd            INT,
    price_tier               VARCHAR(20),
    has_casino               BOOLEAN,
    has_pool                 BOOLEAN,
    has_restaurant           BOOLEAN,
    property_type            VARCHAR(100),
    source_notes             TEXT,
    google_maps_link         VARCHAR(500)
);

-- =====================================================================
-- 11. ACTIVITY_CATEGORY
-- =====================================================================
CREATE TABLE activity_category (
    category_id               INT           PRIMARY KEY,
    category_name             VARCHAR(50)  NOT NULL,
    notes                     VARCHAR(255)
);

-- =====================================================================
-- 12. ACTIVITY
-- =====================================================================
CREATE TABLE activity (
    activity_id                INT           PRIMARY KEY,
    activity_name              VARCHAR(150)  NOT NULL,
    category_id                INT REFERENCES activity_category(category_id),
    location_desc              VARCHAR(255),
    latitude                   NUMERIC(9,6),
    longitude                  NUMERIC(9,6),
    zone_id                    INT REFERENCES location_zone(zone_id),
    duration_min               INT,
    price_usd                  NUMERIC(6,2),
    description                TEXT,
    genre_relevance            VARCHAR(255),
    coord_status               VARCHAR(100),
    price_basis                VARCHAR(255)
);

-- =====================================================================
-- 13-15. ATTENDEE / TICKET_TYPE / TICKET
-- =====================================================================
CREATE TABLE ticket_type (
    ticket_type_id            SERIAL        PRIMARY KEY,
    type_name                 VARCHAR(50)  NOT NULL,
    price_usd                 NUMERIC(8,2),
    perks_desc                TEXT,
    capacity                  INT,
    is_available              BOOLEAN
);

CREATE TABLE attendee (
    attendee_id                SERIAL        PRIMARY KEY,
    name                       VARCHAR(150),
    email                      VARCHAR(150),
    ticket_type_id             INT REFERENCES ticket_type(ticket_type_id),
    property_id                INT REFERENCES property(property_id)
);

CREATE TABLE ticket (
    ticket_id                   SERIAL        PRIMARY KEY,
    ticket_type_id              INT REFERENCES ticket_type(ticket_type_id),
    attendee_id                 INT REFERENCES attendee(attendee_id),
    purchase_date               DATE,
    purchase_price_usd          NUMERIC(8,2),
    payment_status              VARCHAR(20),
    ticket_status               VARCHAR(20),
    qr_code                     VARCHAR(255)
);

-- =====================================================================
-- 16. ATTENDEE_PERFORMANCE  
-- =====================================================================
CREATE TABLE attendee_performance (
    attendee_performance_id   SERIAL        PRIMARY KEY,
    attendee_id               INT NOT NULL REFERENCES attendee(attendee_id),
    performance_id            INT NOT NULL REFERENCES performance(performance_id),
    UNIQUE (attendee_id, performance_id)
);

-- =====================================================================
-- 17. COUPON  
-- =====================================================================
CREATE TABLE coupon (
    coupon_id        SERIAL        PRIMARY KEY,
    item_type        VARCHAR(20)  NOT NULL CHECK (item_type IN ('restaurant','activity')),
    restaurant_id    VARCHAR(10) REFERENCES restaurant(restaurant_id),
    activity_id      INT REFERENCES activity(activity_id),
    coupon_desc      VARCHAR(255) NOT NULL,   
    discount_label   VARCHAR(50),
    sponsor_id       VARCHAR(10)  REFERENCES sponsor(sponsor_id),  -- nullable: not every deal is sponsor-branded
    CHECK (
        (item_type = 'restaurant' AND restaurant_id IS NOT NULL AND activity_id IS NULL)
        OR
        (item_type = 'activity'   AND activity_id   IS NOT NULL AND restaurant_id IS NULL)
    )
);

-- =====================================================================
-- 18. ATTENDEE_ACTIVITY
-- =====================================================================
CREATE TABLE attendee_activity (
    attendee_activity_id      SERIAL        PRIMARY KEY,
    attendee_id               INT NOT NULL REFERENCES attendee(attendee_id),
    activity_id               INT NOT NULL REFERENCES activity(activity_id),
    coupon_id                 INT REFERENCES coupon(coupon_id),
    UNIQUE (attendee_id, activity_id)
);

-- =====================================================================
-- 19. ATTENDEE_RESTAURANT 
-- =====================================================================
CREATE TABLE attendee_restaurant (
    attendee_restaurant_id    SERIAL        PRIMARY KEY,
    attendee_id               INT NOT NULL REFERENCES attendee(attendee_id),
    restaurant_id             VARCHAR(10) NOT NULL REFERENCES restaurant(restaurant_id),
    coupon_id                 INT REFERENCES coupon(coupon_id),
    UNIQUE (attendee_id, restaurant_id)
);

