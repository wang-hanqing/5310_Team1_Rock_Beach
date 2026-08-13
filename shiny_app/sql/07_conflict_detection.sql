-- =====================================================================
-- Scheduling logic, step 2: conflict detection for attendee_performance
-- Run AFTER 01_schema.sql (needs attendee_performance / performance to exist)
-- =====================================================================

-- ---------------------------------------------------------------------
-- A. Hard block at insert time — a trigger that rejects any INSERT into
--    attendee_performance that would create a same-day, overlapping-time
--    selection for that attendee. Uses PostgreSQL's native OVERLAPS
--    operator on (start_time, end_time) pairs.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION check_performance_conflict()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM attendee_performance ap
        JOIN performance existing ON ap.performance_id = existing.performance_id
        JOIN performance incoming ON incoming.performance_id = NEW.performance_id
        WHERE ap.attendee_id = NEW.attendee_id
          AND existing.day_id = incoming.day_id
          AND existing.performance_id != NEW.performance_id
          AND (existing.start_time, existing.end_time)
              OVERLAPS (incoming.start_time, incoming.end_time)
    ) THEN
        RAISE EXCEPTION
            'Schedule conflict: attendee % already has an overlapping performance selected on this day',
            NEW.attendee_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_performance_conflict ON attendee_performance;
CREATE TRIGGER trg_check_performance_conflict
BEFORE INSERT ON attendee_performance
FOR EACH ROW EXECUTE FUNCTION check_performance_conflict();

-- ---------------------------------------------------------------------
-- B. Diagnostic view — surfaces any conflicting pairs an attendee has
--    selected (useful for a "My Schedule" UI warning, or a sanity check
--    if data ever gets loaded in some other way that bypasses the trigger)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_attendee_schedule_conflicts AS
SELECT
    ap1.attendee_id,
    p1.day_id,
    p1.performance_id  AS performance_1,
    a1.artist_name      AS artist_1,
    p1.start_time        AS start_1,
    p1.end_time            AS end_1,
    p2.performance_id        AS performance_2,
    a2.artist_name             AS artist_2,
    p2.start_time                AS start_2,
    p2.end_time                    AS end_2
FROM attendee_performance ap1
JOIN attendee_performance ap2
  ON ap1.attendee_id = ap2.attendee_id
 AND ap1.performance_id < ap2.performance_id
JOIN performance p1 ON ap1.performance_id = p1.performance_id
JOIN performance p2 ON ap2.performance_id = p2.performance_id
JOIN artist a1 ON p1.artist_id = a1.artist_id
JOIN artist a2 ON p2.artist_id = a2.artist_id
WHERE p1.day_id = p2.day_id
  AND (p1.start_time, p1.end_time) OVERLAPS (p2.start_time, p2.end_time);
