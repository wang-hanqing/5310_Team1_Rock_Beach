"""
queries.py — read queries against the Rock & Beach Postgres schema.

Each function returns a pandas DataFrame via db.run_query(). Nothing here
mutates data — these are all SELECTs used to render live content on the
website (Lineup, Schedule, Stay, Chance pages).
"""

from pathlib import Path

import numpy as np
import pandas as pd
from db import run_query, insert_and_return_id

# Small curated coupon list (coupon_id, item_type, restaurant_id, activity_id,
# coupon_desc, discount_label) — lives as a static CSV next to app.py rather
# than a DB table, since it's a short hand-picked bonus list, not
# database-of-record content. Only a handful of restaurants/activities have
# a coupon on purpose (like a real Chance card, most draws are plain — a
# coupon is a bonus when one happens to match).
_COUPON_PATH = Path(__file__).parent / "coupon.csv"
_coupons_df = None


def _load_coupons() -> pd.DataFrame:
    global _coupons_df
    if _coupons_df is None:
        df = pd.read_csv(_COUPON_PATH, dtype={"restaurant_id": "string"})
        df["activity_id"] = pd.to_numeric(df["activity_id"], errors="coerce").astype("Int64")
        _coupons_df = df
    return _coupons_df


def get_coupon_discount_label(item_type: str, item_id) -> str:
    """Look up the discount_label for a drawn restaurant or activity.
    Returns None if this particular pick doesn't have a coupon (most won't —
    only 10 restaurants and 4 activities are in the list)."""
    df = _load_coupons()
    if item_type == "restaurant":
        match = df[(df["item_type"] == "restaurant") & (df["restaurant_id"] == str(item_id))]
    else:
        match = df[(df["item_type"] == "activity") & (df["activity_id"] == int(item_id))]
    if len(match) == 0:
        return None
    return match.iloc[0]["discount_label"]


def get_artists_by_tier(tier: str, limit: int = 3):
    """Artists for a given tier ('Headliner' | 'Support' | 'Rising')."""
    sql = """
        SELECT artist_name, genre, origin_city, profile_image_url
        FROM artist
        WHERE tier = %(tier)s
        ORDER BY artist_name
        LIMIT %(limit)s
    """
    return run_query(sql, params={"tier": tier, "limit": limit})


def get_lineup_grid():
    """Full lineup (all artists, all tiers), each with its first scheduled
    venue if it has one — used for the photo-grid Lineup page. Grouping
    into Headliner/Support/Rising sections happens on the app.py side.
    Includes spotify_url so each card can link out to the artist's Spotify
    page (every row has one, even the artists still missing a photo)."""
    sql = """
        SELECT ar.artist_name, ar.genre, ar.tier, ar.profile_image_url,
               ar.spotify_url, v.stage_name
        FROM artist ar
        LEFT JOIN LATERAL (
            SELECT p.stage_id
            FROM performance p
            WHERE p.artist_id = ar.artist_id
            ORDER BY p.start_time
            LIMIT 1
        ) perf ON true
        LEFT JOIN venue v ON perf.stage_id = v.stage_id
        ORDER BY ar.artist_name
    """
    return run_query(sql)


def get_headliner_spotlight():
    """One headliner performance to feature at the top of the Lineup page."""
    sql = """
        SELECT ar.artist_name, fd.day_theme, fd.day_number, fd.day_date,
               v.stage_name, p.start_time
        FROM performance p
        JOIN artist ar        ON p.artist_id = ar.artist_id
        JOIN venue v            ON p.stage_id = v.stage_id
        JOIN festival_day fd      ON p.day_id = fd.day_id
        WHERE ar.tier = 'Headliner'
        ORDER BY fd.day_number, p.start_time
        LIMIT 1
    """
    df = run_query(sql)
    return df.iloc[0] if len(df) else None


def get_schedule_by_day(per_day_limit: int = 6):
    """Performances grouped by festival day, earliest first, capped per day."""
    sql = """
        SELECT fd.day_number, fd.day_date, fd.day_theme,
               ar.artist_name, ar.tier, v.stage_name,
               p.start_time, p.end_time
        FROM performance p
        JOIN artist ar    ON p.artist_id = ar.artist_id
        JOIN venue v        ON p.stage_id = v.stage_id
        JOIN festival_day fd  ON p.day_id = fd.day_id
        ORDER BY fd.day_number, p.start_time
    """
    df = run_query(sql)
    if len(df) == 0:
        return {}
    out = {}
    for day_number, group in df.groupby("day_number", sort=True):
        out[day_number] = {
            "date": group.iloc[0]["day_date"],
            "theme": group.iloc[0]["day_theme"],
            "rows": group.head(per_day_limit).to_dict("records"),
            "total": len(group),
        }
    return out


def get_top_stays(zone: str = None, price_tiers: list = None, limit: int = 500):
    """Properties for the Select Stay page, highest-rated first. `zone` is
    an optional ILIKE substring against section_of_ac (e.g. 'Boardwalk',
    'Marina'); `price_tiers` is an optional list of exact price_tier values
    to include (e.g. ['Budget', 'Midscale']). limit is a safety cap, not a
    real content limit (previously hardcoded to 3, which silently hid the
    other 24 properties)."""
    where = []
    params = {"limit": limit}
    if zone:
        where.append("section_of_ac ILIKE %(zone)s")
        params["zone"] = f"%{zone}%"
    if price_tiers:
        where.append("price_tier = ANY(%(price_tiers)s)")
        params["price_tiers"] = price_tiers
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT property_name, section_of_ac, price_tier,
               star_rating, price_min_usd, price_max_usd, has_pool, has_casino
        FROM property
        {where_sql}
        ORDER BY star_rating DESC NULLS LAST
        LIMIT %(limit)s
    """
    return run_query(sql, params=params)


def get_all_restaurants():
    """All restaurants for the Draw Chance page's browsable deal list, each
    left-joined to its coupon (if it has one) so real discounts show up
    where they exist — most rows will have discount_label/coupon_desc as
    None, and that's expected (only a handful of restaurants have coupons).
    Also joined to v_restaurant_badges (Hidden gem / Must try / Local hero
    — computed from rating + review_count, see 09_restaurant_badges.sql)
    and to location_zone for the zone filter/default. Includes country
    (cuisine origin, e.g. 'Italian', 'Japanese') so the app can group the
    list into sections instead of one flat wall of ~100 cards. Ordered
    best-rated first within each group."""
    sql = """
        SELECT r.restaurant_id, r.name, r.food_category, r.price_range,
               r.est_cost_per_person_usd,
               r.opening_hours, r.address, r.rating, r.review_count,
               r.country, r.yelp_url, r.google_maps_url,
               r.zone_id, lz.zone_name,
               vb.badge,
               c.discount_label, c.coupon_desc
        FROM restaurant r
        LEFT JOIN coupon c ON c.item_type = 'restaurant' AND c.restaurant_id = r.restaurant_id
        LEFT JOIN location_zone lz ON lz.zone_id = r.zone_id
        LEFT JOIN v_restaurant_badges vb ON vb.restaurant_id = r.restaurant_id
        ORDER BY r.rating DESC NULLS LAST, r.name
    """
    return run_query(sql)


def get_all_activities():
    """All activities for the Draw Chance page's browsable deal list —
    same shape/purpose as get_all_restaurants() above, just sourced from
    activity + activity_category instead of restaurant, with the same
    left-join-to-coupon pattern so real discounts surface where they exist."""
    sql = """
        SELECT a.activity_id, a.activity_name, a.description, a.location_desc,
               a.price_usd, a.duration_min, ac.category_name,
               c.discount_label, c.coupon_desc
        FROM activity a
        LEFT JOIN activity_category ac ON a.category_id = ac.category_id
        LEFT JOIN coupon c ON c.item_type = 'activity' AND c.activity_id = a.activity_id
        ORDER BY a.activity_name
    """
    return run_query(sql)


def get_random_restaurant():
    """One random restaurant pick for the Draw Chance page (Dining draws)."""
    sql = """
        SELECT restaurant_id, name, price_range, food_category, opening_hours, address
        FROM restaurant
        ORDER BY random()
        LIMIT 1
    """
    df = run_query(sql)
    return df.iloc[0] if len(df) else None


def get_random_activity():
    """One random activity pick for the Draw Chance page (Activity draws),
    joined to its category name."""
    sql = """
        SELECT a.activity_id, a.activity_name, ac.category_name,
               a.location_desc, a.price_usd, a.description
        FROM activity a
        LEFT JOIN activity_category ac ON a.category_id = ac.category_id
        ORDER BY random()
        LIMIT 1
    """
    df = run_query(sql)
    return df.iloc[0] if len(df) else None


def get_chance_card(attendee_id: int):
    """The actual Draw Chance pick: a restaurant or activity that (a) has a
    coupon attached and (b) fits one of this attendee's real free-time gaps
    between added shows. Reads the DB architect's v_downtime_chance_cards
    view exactly as specified in 06_chance_cards.sql:
        SELECT * FROM v_downtime_chance_cards WHERE attendee_id = $1
        ORDER BY random() LIMIT 1
    Returns None if there's no attendee yet, or no gap-fitting coupon match
    right now (e.g. no shows added, or no downtime long enough) — that's an
    expected, normal state, not an error."""
    if attendee_id is None:
        return None
    sql = """
        SELECT item_type, item_id, item_name, coupon_id, coupon_desc,
               discount_label, sponsor_name, item_url, gap_start, gap_end, gap_minutes,
               approx_miles_from_stage
        FROM v_downtime_chance_cards
        WHERE attendee_id = %(attendee_id)s
        ORDER BY random()
        LIMIT 1
    """
    df = run_query(sql, params={"attendee_id": attendee_id})
    return df.iloc[0] if len(df) else None


def get_daily_headliner_posters():
    """One featured headliner performance per festival day (earliest set
    time that day) — used for the Pass Go page's 3 deed-card posters.

    Day 1 (Aug 21) has a genuine tie: Coldplay and Justin Bieber both
    have a Headliner performance at the exact same start_time (21:00),
    on different stages. The tiebreak below is an explicit editorial
    choice to feature Coldplay on that day's poster — not a bug fix,
    just picking a winner for a tie the query alone can't resolve."""
    sql = """
        SELECT fd.day_number, fd.day_date, ar.artist_id, ar.artist_name,
               ar.profile_image_url, v.stage_name
        FROM performance p
        JOIN artist ar       ON p.artist_id = ar.artist_id
        JOIN festival_day fd   ON p.day_id = fd.day_id
        JOIN venue v             ON p.stage_id = v.stage_id
        WHERE ar.tier = 'Headliner'
        ORDER BY fd.day_number, p.start_time
    """
    df = run_query(sql)
    posters = {}
    for day_number, group in df.groupby("day_number"):
        if day_number == 1 and (group["artist_name"] == "Coldplay").any():
            posters[int(day_number)] = group[group["artist_name"] == "Coldplay"].iloc[0].to_dict()
        else:
            posters[int(day_number)] = group.iloc[0].to_dict()
    return posters


def add_attendee(name: str, email: str):
    """Register a new attendee (Pass Go's 'GO' button -> registration
    modal). Returns the new attendee_id."""
    sql = """
        INSERT INTO attendee (name, email)
        VALUES (%(name)s, %(email)s)
        RETURNING attendee_id
    """
    return insert_and_return_id(sql, {"name": name, "email": email})


def get_performances(day: int = None, tier: str = None, search: str = None, venue: str = None, time_slot: str = None, limit: int = 20):
    """Performances for the Plan Shows filter bar (day / tier / artist
    search / venue / time_slot, all optional). Returns performance_id so
    callers can add/track a specific show, plus a total_count (pre-LIMIT)
    for a '+N more' note."""
    where = []
    params = {}
    if day:
        where.append("fd.day_number = %(day)s")
        params["day"] = day
    if tier:
        where.append("ar.tier = %(tier)s")
        params["tier"] = tier
    if search:
        where.append("ar.artist_name ILIKE %(search)s")
        params["search"] = f"%{search}%"
    if venue:
        where.append("v.stage_name = %(venue)s")
        params["venue"] = venue
    if time_slot:
        where.append("p.start_time = %(time_slot)s")
        params["time_slot"] = time_slot
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT p.performance_id, ar.artist_name, ar.tier, ar.profile_image_url,
               v.stage_name, v.stage_type, fd.day_number, p.start_time, p.end_time
        FROM performance p
        JOIN artist ar       ON p.artist_id = ar.artist_id
        JOIN venue v           ON p.stage_id = v.stage_id
        JOIN festival_day fd     ON p.day_id = fd.day_id
        {where_sql}
        ORDER BY fd.day_number, p.start_time
    """
    df = run_query(sql, params=params if params else None)
    total = len(df)
    return df.head(limit), total


def get_performance_time_slots():
    """Distinct performance start times across the whole festival, for
    the Plan Shows time-slot filter dropdown — populated from real data
    instead of a hardcoded guess at what slots exist."""
    sql = "SELECT DISTINCT start_time FROM performance ORDER BY start_time"
    return run_query(sql)


def get_venues():
    """All venues, for the reusable zone/type-colored map component
    (venue has no zone column in this schema, so pins are colored by
    stage_type — Main vs Secondary — instead)."""
    sql = "SELECT stage_name, stage_type, latitude, longitude FROM venue"
    return run_query(sql)


def get_attendee_performance_ids(attendee_id: int):
    """Set of performance_ids this attendee has already added — used to
    show the bus-token 'Landed here' stamp instead of an Add action."""
    if attendee_id is None:
        return set()
    sql = "SELECT performance_id FROM attendee_performance WHERE attendee_id = %(attendee_id)s"
    df = run_query(sql, params={"attendee_id": attendee_id})
    return set(df["performance_id"].tolist())


def add_attendee_performance(attendee_id: int, performance_id: int):
    """Add a performance to an attendee's personal schedule. The database
    has a BEFORE INSERT trigger (check_performance_conflict) that raises
    an exception if this overlaps a same-day performance already added —
    that exception propagates up to the caller to show as a warning."""
    sql = """
        INSERT INTO attendee_performance (attendee_id, performance_id)
        VALUES (%(attendee_id)s, %(performance_id)s)
        RETURNING attendee_performance_id
    """
    return insert_and_return_id(sql, {"attendee_id": attendee_id, "performance_id": performance_id})


def get_performance_venue(performance_id: int):
    """Venue name + coordinates for one performance — used to fly the Plan
    Shows venue map straight to that spot right after an attendee adds a
    show there, so Add visibly "connects" to a pin on the map."""
    sql = """
        SELECT v.stage_name, v.latitude, v.longitude
        FROM performance p
        JOIN venue v ON p.stage_id = v.stage_id
        WHERE p.performance_id = %(performance_id)s
    """
    df = run_query(sql, params={"performance_id": performance_id})
    return df.iloc[0] if len(df) else None


def remove_attendee_performance(attendee_id: int, performance_id: int):
    """Undo an Add — lets an attendee change their mind and remove a show
    from their personal schedule (the Plan Shows 'Landed' stamp becomes
    clickable to trigger this)."""
    sql = """
        DELETE FROM attendee_performance
        WHERE attendee_id = %(attendee_id)s AND performance_id = %(performance_id)s
        RETURNING attendee_performance_id
    """
    return insert_and_return_id(sql, {"attendee_id": attendee_id, "performance_id": performance_id})


def get_attendee_schedule(attendee_id: int):
    """This attendee's added shows, day by day, earliest first — for the
    My 3-Day Schedule board-path page. Reads the DB architect's
    v_attendee_schedule view (attendee_performance JOIN performance,
    artist, venue, festival_day) instead of re-deriving the join here."""
    if attendee_id is None:
        return pd.DataFrame()
    sql = """
        SELECT day_number, artist_name, tier, stage_name, start_time, end_time
        FROM v_attendee_schedule
        WHERE attendee_id = %(attendee_id)s
        ORDER BY day_number, start_time
    """
    return run_query(sql, params={"attendee_id": attendee_id})


def get_attendee_downtime(attendee_id: int):
    """Free-time gaps between this attendee's consecutive added shows on
    the same day — reads the DB architect's v_attendee_downtime view
    (built with LEAD() over v_attendee_schedule). Reused as-is by Draw
    Chance later for its 'free time right now' recommendations."""
    if attendee_id is None:
        return pd.DataFrame()
    sql = """
        SELECT day_number, gap_start, gap_end, gap_minutes, after_stage
        FROM v_attendee_downtime
        WHERE attendee_id = %(attendee_id)s
        ORDER BY day_number, gap_start
    """
    return run_query(sql, params={"attendee_id": attendee_id})


def get_counts():
    """Quick stats used for the trip-summary style status lines."""
    sql = """
        SELECT
            (SELECT COUNT(*) FROM artist)      AS artist_count,
            (SELECT COUNT(*) FROM performance) AS performance_count,
            (SELECT COUNT(*) FROM restaurant)  AS restaurant_count,
            (SELECT COUNT(*) FROM property)    AS property_count
    """
    df = run_query(sql)
    return df.iloc[0] if len(df) else None


def _jitter_duplicate_coords(df: pd.DataFrame, radius_deg: float = 0.00035) -> pd.DataFrame:
    """Some locations share the exact same lat/lon (e.g. multiple venues
    inside the same casino building). Spread exact duplicates in a small
    circle around the original point so every marker on the interactive map
    is separately visible/clickable instead of stacking on top of each
    other. Points with unique coordinates are left untouched. (Ported from
    the DB architect's own map-demo script.)"""
    df = df.copy()
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)
    for (lat, lng), group in df.groupby(["latitude", "longitude"]):
        if len(group) <= 1:
            continue
        n = len(group)
        for i, idx in enumerate(group.index):
            angle = 2 * np.pi * i / n
            df.loc[idx, "latitude"] = lat + radius_deg * np.sin(angle)
            df.loc[idx, "longitude"] = lng + radius_deg * np.cos(angle) / np.cos(np.radians(lat))
    return df


def get_map_locations():
    """Unified Venue/Stay/Dining/Activity dataset (name, latitude,
    longitude, category, description, id_value) for the interactive trip
    map, read live from the database. id_value is the row's real primary
    key (stage_id/property_name/restaurant_id/activity_id — property has
    no separate id column already in use elsewhere in the app, so its
    name doubles as the key, same as selected_stay's own storage), used
    to wire map clicks to the same select/favorite actions the list/card
    views already trigger, instead of markers being decorative-only."""
    venues = run_query("SELECT stage_id AS id_value, stage_name AS name, stage_type AS description, latitude, longitude FROM venue")
    venues["category"] = "Venue"

    stays = run_query("SELECT property_name AS id_value, property_name AS name, address AS description, latitude, longitude FROM property")
    stays["category"] = "Stay"

    diners = run_query("SELECT restaurant_id AS id_value, name, food_category, price_range, latitude, longitude FROM restaurant")
    diners["description"] = diners["food_category"].fillna("") + " · " + diners["price_range"].fillna("")
    diners["category"] = "Dining"
    diners = diners[["id_value", "name", "description", "latitude", "longitude", "category"]]

    activities = run_query("SELECT activity_id AS id_value, activity_name AS name, description, latitude, longitude FROM activity")
    activities["category"] = "Activity"

    combined = pd.concat([venues, stays, diners, activities], ignore_index=True)
    combined = combined.dropna(subset=["latitude", "longitude"])
    combined = _jitter_duplicate_coords(combined)
    return combined


# ── Trip Summary / Budget queries ────────────────────────────────────────────
def get_stay_details(property_name: str):
    """Price range + map link for the attendee's single selected stay
    (session-only selected_stay reactive value stores just the name, not
    a property_id, so this looks it up by name)."""
    if not property_name:
        return None
    sql = """
        SELECT property_name, price_min_usd, price_max_usd, google_maps_link
        FROM property
        WHERE property_name = %(name)s
        LIMIT 1
    """
    df = run_query(sql, params={"name": property_name})
    return df.iloc[0] if len(df) else None