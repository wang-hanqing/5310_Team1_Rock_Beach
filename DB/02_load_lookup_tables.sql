-- =====================================================================
-- Load lookup/reference tables with NO foreign-key dependencies.
-- Run this SECOND, right after 01_schema.sql and define location_zone before 
-- ETL scripts 
--
-- SOURCE NOTE 
-- location_zone, cuisine_type, festival_day, and
-- ticket_type were directly defined by the team (zone definitions,
-- cuisine groupings, the 3 festival dates/themes, ticket tiers/pricing)
-- activity_category DOES have a real raw source (raw_data/activity_category_raw.csv
-- and loads from there instead 
--
-- HOW TO RUN (psql, from the project folder containing raw_data/ and
-- clean_data/):
--   \i 02_load_lookup_tables.sql
-- =====================================================================

\copy location_zone       FROM 'location_zone.csv'      			 WITH (FORMAT csv, HEADER true);
\copy cuisine_type        FROM 'cuisine_type.csv'        		 	 WITH (FORMAT csv, HEADER true);
\copy festival_day        FROM 'festival_day.csv'            		 WITH (FORMAT csv, HEADER true);
\copy activity_category   FROM 'raw_data/activity_category_raw.csv'  WITH (FORMAT csv, HEADER true);
\copy ticket_type         FROM 'ticket_type.csv'                     WITH (FORMAT csv, HEADER true);
