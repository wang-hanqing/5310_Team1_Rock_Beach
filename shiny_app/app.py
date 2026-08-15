"""
app.py — Rock & Beach Festival: Monopoly-themed trip planner (Shiny for Python)

An 8-screen flow (Pass Go -> Lineup -> Plan Shows -> Schedule -> Stay ->
Chance -> Summary -> Bank), styled like a Monopoly board game. Navigation
between screens is instant vanilla JS (show/hide, no server round-trip).

Four sections pull LIVE data straight from the shared Postgres database via
queries.py / db.py, using Shiny's @render.ui — these re-run every time a
session loads the page, so any row your teammates add/edit in the database
shows up automatically without redeploying:
  - Lineup page: headliner spotlight + Headliner/Support/Rising artist cards
  - Schedule page: real performances grouped by festival day
  - Stay page: top-rated properties
  - Chance page: random restaurant pick (re-rolls live on "Draw again")

Everything else (Pass Go, Plan Shows, Trip Summary, Bank) stays static —
those need per-attendee login/session state this project doesn't have yet.
"""

import html
import re
from pathlib import Path
import pandas as pd
from shiny import App, ui, render, reactive
from shinywidgets import output_widget, render_widget
from ipyleaflet import Map as LeafletMap, Marker, AwesomeIcon, TileLayer, basemaps
from ipywidgets import HTML as LeafletPopupHTML

import queries

# Real interactive trip map (Venue/Stay/Dining/Activity pins), replacing the
# old flat dot-plot placeholders on Plan Shows and Select Stay. Built with
# ipyleaflet + shinywidgets — ported from the DB architect's own map-demo
# script (05. Map/app.py), reading live from the database via
# queries.get_map_locations() instead of that script's static CSVs.
MAP_CATEGORY_STYLE = {
    "Venue": {"marker_color": "red", "icon": "music"},
    "Stay": {"marker_color": "blue", "icon": "bed"},
    "Dining": {"marker_color": "orange", "icon": "cutlery"},
    "Activity": {"marker_color": "green", "icon": "star"},
}
AC_MAP_CENTER = (39.36, -74.43)


def _redraw_map_markers(leaflet_map, df, selected_categories, highlight_names=None, on_marker_click=None):
    """Clear all non-tile layers off the given ipyleaflet Map and redraw
    markers for whichever categories are currently selected.
    `highlight_names` (optional set of `name` values) renders those rows
    with a gold star marker instead of the category's default color, and
    calls that out in the popup — used by the Plan Shows map to visibly
    connect a venue pin to shows the attendee has actually added.
    `on_marker_click` (optional callback(row_dict)) wires a real action to
    clicking a marker — e.g. selecting that stay, favoriting that
    restaurant/activity — instead of the marker being decorative and only
    showing a popup on click."""
    leaflet_map.layers = tuple(layer for layer in leaflet_map.layers if isinstance(layer, TileLayer))
    if df is None or len(df) == 0 or not selected_categories:
        return
    highlight_names = highlight_names or set()
    filtered = df[df["category"].isin(selected_categories)]
    for _, row in filtered.iterrows():
        is_added = row["name"] in highlight_names
        if is_added:
            icon = AwesomeIcon(name="star", marker_color="orange", icon_color="white")
        else:
            style = MAP_CATEGORY_STYLE.get(row["category"], {"marker_color": "gray", "icon": "info-sign"})
            icon = AwesomeIcon(name=style["icon"], marker_color=style["marker_color"], icon_color="white")
        marker = Marker(location=(row["latitude"], row["longitude"]), icon=icon, draggable=False)
        desc = row.get("description") or ""
        added_tag = "&#9733; On your schedule<br>" if is_added else ""
        action_hint = "<br><i>Click pin to select</i>" if on_marker_click else ""
        marker.popup = LeafletPopupHTML(value=f"{added_tag}<b>{row['name']}</b><br>{row['category']}<br>{desc}{action_hint}")
        if on_marker_click:
            row_dict = row.to_dict()
            # Default-arg trick to bind THIS row's data into the closure —
            # without it every marker's handler would see the last row of
            # the loop instead of its own (the classic Python late-binding
            # closure bug).
            marker.on_click(lambda *, _row=row_dict, **kwargs: on_marker_click(_row))
        leaflet_map.add_layer(marker)

# ── Steps + palette ──────────────────────────────────────────────────────────
STEP_LABELS = ["Lineup", "Plan shows", "Schedule", "Chance", "Properties", "Trip Deed", "The Bank"]
STEP_COLORS = ["#FFD84D", "#2EC4B6", "#7F77DD", "#E85D7A", "#FFD84D", "#2EC4B6", "#7F77DD"]
STEP_STATUS = [
    "Live lineup from the database",
    "1 show added",
    "Live schedule from the database",
    "Live stays from the database",
    "Live dining pick from the database",
    "1 dining pick saved",
    "Railroad Pass selected",
]

BUS_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none">'
    '<rect x="2" y="6" width="20" height="10" rx="2" fill="#1B2A4A"/>'
    '<rect x="4" y="8" width="4" height="4" fill="#FDF6E3"/>'
    '<rect x="10" y="8" width="4" height="4" fill="#FDF6E3"/>'
    '<rect x="16" y="8" width="4" height="4" fill="#FDF6E3"/>'
    '<circle cx="6.5" cy="17" r="2" fill="#1B2A4A"/>'
    '<circle cx="17.5" cy="17" r="2" fill="#1B2A4A"/></svg>'
)
DICE_SVG = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none">'
    '<rect x="3" y="3" width="18" height="18" rx="4" stroke="#B9C4DC" stroke-width="2"/>'
    '<circle cx="8" cy="8" r="1.6" fill="#B9C4DC"/><circle cx="16" cy="8" r="1.6" fill="#B9C4DC"/>'
    '<circle cx="12" cy="12" r="1.6" fill="#B9C4DC"/><circle cx="8" cy="16" r="1.6" fill="#B9C4DC"/>'
    '<circle cx="16" cy="16" r="1.6" fill="#B9C4DC"/></svg>'
)
DICE_SVG_DARK = DICE_SVG.replace("#B9C4DC", "#1B2A4A")

# Larger versions of the icons above, used only in the desktop-sized stepper
# strip (stepper_html) where the default icon size reads too small.
BUS_SVG_LG = BUS_SVG.replace('width="14" height="14"', 'width="22" height="22"')
# Light-colored dice (not the dark variant) since the stepper now sits on
# the dark shadow-photo background instead of white.
DICE_SVG_LG = DICE_SVG.replace('width="11" height="11"', 'width="16" height="16"')

# Spotify logo mark, used as a small link-out button under each Lineup card.
SPOTIFY_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="12" fill="#1DB954"/>'
    '<path d="M17.9 10.9c-3.2-1.9-8.4-2.1-11.4-1.2-.5.1-1-.1-1.1-.6-.1-.5.1-1 .6-1.1 3.5-1 9.3-.8 12.9 1.3.4.3.6.8.3 1.3-.2.4-.8.6-1.3.3zm-.1 2.9c-.2.4-.7.5-1 .3-2.7-1.6-6.8-2.1-10-1.2-.4.1-.8-.1-.9-.5-.1-.4.1-.8.5-.9 3.6-1 8.1-.5 11.2 1.4.3.2.5.6.2.9zm-1.2 2.7c-.2.3-.5.4-.8.2-2.4-1.4-5.3-1.8-8.8-1-.3.1-.6-.1-.7-.4-.1-.3.1-.6.4-.7 3.8-.9 7.1-.4 9.7 1.2.3.2.4.5.2.7z" fill="#04120A"/>'
    '</svg>'
)


def stepper_html(current: int) -> str:
    """Build the horizontal step tracker for step-pages (index 1..7 in the
    overall flow; `current` is 0-based within STEP_LABELS)."""
    items = []
    for i, label in enumerate(STEP_LABELS):
        color = STEP_COLORS[i]
        page_num = i + 2  # step-pages are rbShow(2..8); page 1 is the landing screen
        if i < current:
            items.append(f'''
            <div onclick="rbShow({page_num})" style="cursor:pointer;flex:1;min-width:105px;text-align:center">
              <div style="height:8px;background:{color};opacity:.5;border-radius:8px 8px 0 0"></div>
              <div style="height:62px;border-radius:0 0 8px 8px;background:#2C3E63;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px">
                <span style="color:#5DCAA5;font-size:16px;font-weight:700">&#10003;</span>
                <span style="font-size:14px;color:#E4D8C4;font-weight:400;text-transform:uppercase;letter-spacing:0.05em">{label}</span>
              </div>
            </div>''')
        elif i == current:
            items.append(f'''
            <div onclick="rbShow({page_num})" style="cursor:pointer;flex:1;min-width:105px;text-align:center">
              <div style="height:8px;background:{color};border-radius:8px 8px 0 0;border:2px solid #1B2A4A;border-bottom:none"></div>
              <div style="height:62px;border-radius:0 0 8px 8px;background:#FFD84D;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:2px solid #1B2A4A;border-top:none">
                {BUS_SVG}
                <span style="font-size:14px;color:#1B2A4A;font-weight:600;text-transform:uppercase;letter-spacing:0.05em">{label}</span>
              </div>
            </div>''')
        else:
            items.append(f'''
            <div onclick="rbShow({page_num})" style="cursor:pointer;flex:1;min-width:105px;text-align:center">
              <div style="height:8px;background:{color};opacity:.25;border-radius:8px 8px 0 0"></div>
              <div style="height:62px;border-radius:0 0 8px 8px;background:#243452;border:1.5px dashed #3A4A70;display:flex;align-items:center;justify-content:center;padding:0 4px">
                <span style="font-size:14px;color:#E4D8C4;font-weight:400;text-transform:uppercase;letter-spacing:0.05em">{label}</span>
              </div>
            </div>''')
    return f'''
    <div class="rb-shadow-page rb-sticky-stepper" style="padding:20px 24px 16px">
      <div style="display:flex;gap:10px;overflow-x:auto;padding-bottom:4px">{"".join(items)}</div>
    </div>'''


# ── Live-data render helpers ─────────────────────────────────────────────────
def _fmt_time(t) -> str:
    """Format a datetime.time as '6:00 PM' without relying on platform-
    specific strftime flags (Windows doesn't support %-I)."""
    if t is None or (isinstance(t, float) and pd.isna(t)):
        return ""
    hour = t.hour % 12 or 12
    ampm = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {ampm}"


def _db_error_box(message: str) -> str:
    return f'''
    <div style="background:#FAECE7;padding:14px 20px;border-radius:10px;margin:16px 20px">
      <p style="font-size:12px;font-weight:700;color:#4A1B0C;margin:0 0 4px">Live data unavailable</p>
      <p style="font-size:11px;color:#712B13;margin:0">{message}</p>
    </div>'''


FALLBACK_GRADIENTS = [
    "linear-gradient(160deg, #7F77DD 0%, #2B1B4A 100%)",
    "linear-gradient(160deg, #F0997B 0%, #4A1B0C 100%)",
    "linear-gradient(160deg, #2EC4B6 0%, #085041 100%)",
    "linear-gradient(160deg, #E85D7A 0%, #4B1528 100%)",
    "linear-gradient(160deg, #FFD84D 0%, #7A5A00 100%)",
]

# Illustrated cuisine-bucket art (shipped in www/) for the restaurant deal
# tiles on the Draw Chance page — food_category has ~30 distinct granular
# values (Steakhouse, Subs, Sushi, Bakery, ...) with no broader "cuisine
# group" column in the schema, so this keyword-buckets each one into
# whichever of the 4 illustrated cards fits best.
_CUISINE_KEYWORDS = {
    "cuisine_fine_dining.jpg": ("steak", "fine dining", "chophouse", "seafood", "bistro"),
    "cuisine_bars_brews.jpg": ("brew", "beer", "pub", "distillery", "bar", "cocktail"),
    "cuisine_international.jpg": (
        "sushi", "italian", "japanese", "mexican", "izakaya", "bao", "dumpling",
        "jerk", "taco", "ethnic", "asian", "cuban", "noodle", "cuisine",
    ),
}


def _restaurant_cuisine_image(food_category: str) -> str:
    fc = (food_category or "").lower()
    for img, keywords in _CUISINE_KEYWORDS.items():
        if any(k in fc for k in keywords):
            return img
    # Default bucket: everything quick/casual (subs, food trucks, bakeries,
    # ice cream, donuts, candy, snacks, etc.) — the most common case.
    return "cuisine_quick_bites.jpg"


# Illustrated activity-category art (shipped in www/), keyed by the exact
# 7 activity_category.category_name values in the shared schema (boardwalk,
# beach, casino, cultural, shopping, nightlife, water_sports).
_ACTIVITY_CATEGORY_IMAGES = {
    "beach": "activity_cat_beach.jpg",
    "boardwalk": "activity_cat_boardwalk.jpg",
    "casino": "activity_cat_casino.jpg",
    "cultural": "activity_cat_cultural.jpg",
    "nightlife": "activity_cat_nightlife.jpg",
    "shopping": "activity_cat_shopping.jpg",
    "water-sports": "activity_cat_water_sports.jpg",
}


def _activity_category_image(category_name: str):
    slug = re.sub(r"[^a-z0-9]+", "-", (category_name or "").lower()).strip("-")
    return _ACTIVITY_CATEGORY_IMAGES.get(slug)


# Locally-supplied artist photos (shipped in www/artist_photos/), for artists
# whose DB row has no profile_image_url yet. Keyed by a slug of the artist
# name — same slug-a-name-into-a-filename pattern as the Stay page's
# www/stay_photos/. DB photo (if present) always wins; this is just a
# fallback ahead of the hashed-gradient placeholder.
ARTIST_PHOTOS_DIR = Path(__file__).parent / "www" / "artist_photos"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# Public-domain / Creative-Commons press photos (Wikimedia Commons) for
# lineup artists whose DB row doesn't have a profile_image_url yet. Used
# only as a last-resort fallback (ahead of the hashed-gradient placeholder,
# behind both the DB photo and any locally-supplied www/artist_photos/ file)
# — swap any of these out any time by adding a real photo to the DB or to
# www/artist_photos/<slug>.jpg.
FALLBACK_ARTIST_PHOTO_URLS = {
    "5 seconds of summer": "https://commons.wikimedia.org/wiki/Special:FilePath/5%20Seconds%20of%20Summer%202023.jpg",
    "clairo": "https://commons.wikimedia.org/wiki/Special:FilePath/Clairo%20May%202019%20(cropped%20upper).jpg",
    "mgmt": "https://commons.wikimedia.org/wiki/Special:FilePath/MGMT.jpg",
    "mitski": "https://commons.wikimedia.org/wiki/Special:FilePath/Mitski%20-%2051932297073%20(cropped).jpg",
    "the 1975": "https://commons.wikimedia.org/wiki/Special:FilePath/The%201975%20(14712180536).jpg",
}


def _artist_photo_src(row):
    """Returns an <img src="..."> value for this artist: the DB's
    profile_image_url if set, else a locally-provided photo in
    www/artist_photos/<slug>.jpg if one exists, else a Wikimedia Commons
    fallback photo if we have one on file for this artist, else None
    (caller falls back to the hashed-gradient placeholder)."""
    img = row.get("profile_image_url")
    if isinstance(img, str) and img.strip():
        return img
    name = row.get("artist_name")
    if isinstance(name, str) and name.strip():
        slug = _slugify(name)
        if (ARTIST_PHOTOS_DIR / f"{slug}.jpg").exists():
            return f"artist_photos/{slug}.jpg"
        if (ARTIST_PHOTOS_DIR / f"{slug}.png").exists():
            return f"artist_photos/{slug}.png"
        fallback_url = FALLBACK_ARTIST_PHOTO_URLS.get(name.strip().lower())
        if fallback_url:
            return fallback_url
    return None


def _lineup_grid_card(row, large=False) -> str:
    """One card for the photo-grid Lineup page.
    `large=True` (Headliner tier): full-bleed photo with a dark gradient
    overlay and the name/genre overlaid in white at the bottom, no card
    border — the original, more dramatic treatment, kept specifically
    for headliners so their images stay big and eye-catching (an inset
    photo + separate caption area, like support/rising below get, would
    eat into how large the actual image reads).
    `large=False` (Support/Rising): the A+B card look — cream card with
    a navy border, square photo inset with a small margin, name/genre as
    plain text below the photo on the cream background."""
    name = row["artist_name"]
    img_src = _artist_photo_src(row)
    if img_src:
        bg_layer = f'<img src="{img_src}" style="width:100%;height:100%;object-fit:cover;display:block">'
    else:
        gradient = FALLBACK_GRADIENTS[hash(name) % len(FALLBACK_GRADIENTS)]
        bg_layer = f'<div style="width:100%;height:100%;background:{gradient}"></div>'

    # Venue name intentionally left out of the caption — just artist name + genre.
    meta = row.get("genre") if isinstance(row.get("genre"), str) and row.get("genre").strip() else ""

    spotify_url = row.get("spotify_url")

    if large:
        social_row = ""
        if isinstance(spotify_url, str) and spotify_url.strip():
            social_row = f'<a href="{spotify_url}" target="_blank" rel="noopener" title="Listen on Spotify" style="position:absolute;top:10px;right:10px;z-index:3">{SPOTIFY_SVG}</a>'
        return f'''
        <div class="rb-headliner-card">
          {bg_layer}
          <div class="rb-headliner-overlay"></div>
          {social_row}
          <div class="rb-headliner-caption">
            <p class="name" title="{html.escape(name)}">{name}</p>
            <p class="meta" title="{html.escape(meta)}">{meta}</p>
          </div>
        </div>'''

    social_row = ""
    if isinstance(spotify_url, str) and spotify_url.strip():
        social_row = f'''
        <div class="rb-social-row" style="margin-top:4px">
          <a href="{spotify_url}" target="_blank" rel="noopener" title="Listen on Spotify">{SPOTIFY_SVG}</a>
        </div>'''

    return f'''
    <div class="rb-artist-card-wrap">
      <div class="rb-artist-photo-frame">
        <div class="rb-artist-photo-inner">{bg_layer}</div>
      </div>
      <div class="rb-artist-caption">
        <p class="name" style="font-size:13px" title="{html.escape(name)}">{name}</p>
        <p class="meta" style="font-size:10px" title="{html.escape(meta)}">{meta}</p>
        {social_row}
      </div>
    </div>'''


def _plan_show_card(row, added: bool) -> str:
    """One card for the Plan Shows lineup-style grid — same A+B card
    language as the Lineup page (cream card, navy border, inset square
    photo, plain-text caption below on the cream background), captioned
    with artist name + stage. Time isn't repeated here — each grid is
    already grouped under its own time-slot header right above it, so
    putting the time on the card too was redundant, and worse, made
    captions different heights depending on venue name length. Plus an
    Add / Landed-here action badge in the photo's top-right corner."""
    name = row["artist_name"]
    img_src = _artist_photo_src(row)
    if img_src:
        bg_layer = f'<img src="{img_src}" style="width:100%;height:100%;object-fit:cover;display:block">'
    else:
        gradient = FALLBACK_GRADIENTS[hash(name) % len(FALLBACK_GRADIENTS)]
        bg_layer = f'<div style="width:100%;height:100%;background:{gradient}"></div>'

    if added:
        # Clickable version of the "Landed" stamp — hover swaps the label to
        # "Remove" so it's clear it can be undone, click fires rbRemoveShow.
        action = f'''<span class="token rb-landed-token" style="position:absolute;top:6px;right:6px;z-index:3" onclick="rbRemoveShow({row["performance_id"]})" title="Click to remove from your schedule">
          <span class="rb-landed-default-text">&#10003; Landed</span>
          <span class="rb-landed-hover-text">&#10005; Remove</span>
        </span>'''
    else:
        action = f'<span class="rb-add-btn" style="position:absolute;top:6px;right:6px;z-index:3;font-size:11px;padding:6px 12px" onclick="rbAddShow({row["performance_id"]})">Add</span>'

    return f'''
    <div class="rb-artist-card-wrap">
      <div class="rb-artist-photo-frame">
        <div class="rb-artist-photo-inner">{bg_layer}</div>
        {action}
      </div>
      <div class="rb-artist-caption">
        <p class="name" style="font-size:13px" title="{html.escape(name)}">{name}</p>
        <p class="meta" style="font-size:10px" title="{html.escape(row['stage_name'])}">{row['stage_name']}</p>
      </div>
    </div>'''


DAY_POSTER_COLORS = {1: "#E85D7A", 2: "#2EC4B6", 3: "#7F77DD"}
DAY_POSTER_LABELS = {1: "AUG 21 FRI", 2: "AUG 22 SAT", 3: "AUG 23 SUN"}


def _poster_card(day_number: int, info) -> str:
    """One deed-card poster for the Pass Go page: colored header band +
    a portrait photo card (same style as the Lineup grid) for that day's
    featured headliner — full-bleed photo/gradient fallback, name + venue
    captioned over a dark gradient at the bottom."""
    color = DAY_POSTER_COLORS.get(day_number, "#1B2A4A")
    label = DAY_POSTER_LABELS.get(day_number, f"DAY {day_number}")

    if info is None:
        body = '<div class="dashedbox" style="aspect-ratio:3/4">TBA</div>'
    else:
        name = info.get("artist_name") or "TBA"
        stage = info.get("stage_name") or ""
        img_src = _artist_photo_src(info)
        if img_src:
            bg_layer = f'<img src="{img_src}" style="width:100%;height:100%;object-fit:cover;display:block">'
        else:
            gradient = FALLBACK_GRADIENTS[hash(name) % len(FALLBACK_GRADIENTS)]
            bg_layer = f'<div style="width:100%;height:100%;background:{gradient}"></div>'
        body = f'''
        <div style="position:relative;aspect-ratio:3/4">
          {bg_layer}
          <div style="position:absolute;inset:0;background:linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.15) 55%, rgba(0,0,0,0) 75%)"></div>
          <div style="position:absolute;left:0;right:0;bottom:0;padding:12px;z-index:2">
            <p style="color:#fff;font-weight:800;font-size:15px;margin:0 0 2px;text-shadow:0 2px 6px rgba(0,0,0,0.5)">{name}</p>
            <p style="color:rgba(255,255,255,0.85);font-size:11px;margin:0">{stage}</p>
          </div>
        </div>'''

    return f'''<div onclick="rbOpenLineupModal()" style="flex:1;background:#FDF6E3;border:1.5px solid #1B2A4A;border-radius:8px;overflow:hidden;cursor:pointer">
      <div style="background:{color};padding:8px 0;text-align:center"><span style="font-size:15px;font-weight:400;font-family:var(--font-body);letter-spacing:0.06em;color:#FDF6E3">{label}</span></div>
      {body}
    </div>'''


TIER_DOT = {"Headliner": "#E85D7A", "Support": "#2EC4B6", "Rising": "#7F77DD"}
DAY_COLORS = [("#FAECE7", "#712B13"), ("#E1F5EE", "#085041"), ("#EEEDFE", "#3C3489")]


def _schedule_day_col(idx, day_number, info) -> str:
    bg, color = DAY_COLORS[idx % len(DAY_COLORS)]
    date_val = info["date"]
    date_label = date_val.strftime("%a %b %d") if hasattr(date_val, "strftime") else str(date_val)
    rows_html = ""
    for r in info["rows"]:
        dot = TIER_DOT.get(r["tier"], "#999")
        rows_html += f'''<div style="display:flex;align-items:center;gap:8px;padding:6px 0">
          <div style="width:8px;height:8px;border-radius:50%;background:{dot};flex-shrink:0"></div>
          <div><p style="font-size:9px;color:#888;margin:0">{_fmt_time(r['start_time'])} &middot; {r['stage_name']}</p><p style="font-size:10px;font-weight:700;margin:1px 0 0">{r['artist_name']}</p></div>
        </div>'''
    more = info["total"] - len(info["rows"])
    if more > 0:
        rows_html += f'<p style="font-size:9px;color:#888;margin:6px 0 0">+{more} more that day</p>'
    return f'''<div style="flex:1">
      <div style="text-align:center;font-size:10px;font-weight:700;color:{color};background:{bg};border-radius:8px;padding:5px 0;margin-bottom:8px">Day {day_number} &middot; {date_label}</div>
      <div style="border-left:2px dashed #ccc;margin-left:4px;padding-left:8px">{rows_html}</div>
    </div>'''


# Hotel exterior photos (shipped in www/stay_photos/, keyed by a slug of the
# property name so no extra DB column is needed). Falls back to the same
# hashed-gradient treatment as the Lineup cards for the one property with no
# sourced photo (Super 8 by Wyndham Atlantic City).
STAY_PHOTOS_DIR = Path(__file__).parent / "www" / "stay_photos"


def _stay_photo_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _stay_photo_html(property_name: str) -> str:
    slug = _stay_photo_slug(property_name)
    if (STAY_PHOTOS_DIR / f"{slug}.jpg").exists():
        return f'<img src="stay_photos/{slug}.jpg" style="width:100%;height:100%;object-fit:cover;display:block">'
    gradient = FALLBACK_GRADIENTS[hash(property_name) % len(FALLBACK_GRADIENTS)]
    return f'<div style="width:100%;height:100%;background:{gradient}"></div>'


def _stay_card(row, featured=False, is_selected=False) -> str:
    tier_houses = {"Budget": 1, "Midscale": 1, "Upscale": 2, "Luxury": 3}.get(row.get("price_tier"), 1)
    houses = "".join('<span class="house"></span>' for _ in range(tier_houses))
    price = ""
    if pd.notna(row.get("price_min_usd")) and pd.notna(row.get("price_max_usd")):
        price = f" &middot; ${int(row['price_min_usd'])}–${int(row['price_max_usd'])}"
    stars = ""
    if pd.notna(row.get("star_rating")):
        star_count = int(round(row["star_rating"]))
        stars = f'<p style="font-size:13px;margin:4px 0 0"><span style="color:#FAC00A;letter-spacing:1px">{"★" * star_count}</span> <span style="color:#888">{row["star_rating"]:.1f}</span></p>'
    deed_tag = '<div class="deed">TOP PICK</div>' if featured else ""
    box_style = "border:1.5px solid #1B2A4A;background:#FDF6E3;" if featured else "border:1px solid #ddd;background:#fff;"
    photo = _stay_photo_html(row["property_name"])

    # Add / Selected action — same clickable-stamp pattern as Plan Shows'
    # Add/Landed button (session-only state; there's no attendee_property
    # table in the shared schema yet to persist this to).
    name_attr = html.escape(row["property_name"], quote=True)
    zone_attr = html.escape(str(row.get("section_of_ac") or ""), quote=True)
    if is_selected:
        action = '''<span class="token rb-landed-token" onclick="rbRemoveStay()" title="Click to remove your stay pick">
          <span class="rb-landed-default-text">&#10003; Selected</span>
          <span class="rb-landed-hover-text">&#10005; Remove</span>
        </span>'''
    else:
        action = f'<span class="rb-add-btn" style="font-size:12px;padding:7px 16px" data-name="{name_attr}" data-zone="{zone_attr}" onclick="rbAddStay(this)">Add</span>'

    return f'''<div style="position:relative;display:flex;gap:16px;padding:16px;border-radius:10px;{box_style}margin-bottom:12px">
      {deed_tag}
      <div style="width:130px;height:92px;border-radius:8px;overflow:hidden;flex-shrink:0">{photo}</div>
      <div style="flex:1;min-width:0">
        <p style="font-size:16px;font-weight:700;margin:0">{row['property_name']}</p>
        {stars}
        <p style="font-size:14px;color:#888;margin:4px 0 0">{row['section_of_ac']} &middot; {row['price_tier']}{price}</p>
      </div>
      <div style="align-self:center;text-align:right;white-space:nowrap">
        <div style="margin-bottom:8px">{houses}</div>
        {action}
      </div>
    </div>'''


def _restaurant_card_html(row, is_fav: bool) -> str:
    """One restaurant deal tile for the Draw Chance page's grid list — a
    photo-block top (colorful gradient fallback, no restaurant photos exist
    in the schema) with a heart + rating badge over it, then name/category
    and a price row below. Price uses house icons off price_range's $ count
    (same visual language as the Select Stay page's price tiers), except
    for the handful of restaurants that have a real coupon — those show a
    discount badge instead."""
    name = row.get("name") or "Restaurant"
    category = row.get("food_category") or ""
    photo_bg = f"background-image:url('{_restaurant_cuisine_image(category)}');background-size:cover;background-position:center"

    rating_badge = ""
    if pd.notna(row.get("rating")):
        rating_badge = f'<span class="rb-restaurant-rating">&#9733; {row["rating"]:.1f}</span>'

    dollar_count = max(1, min((row.get("price_range") or "$").count("$"), 4))
    houses_html = "".join('<span class="house"></span>' for _ in range(dollar_count))

    discount = row.get("discount_label")
    if isinstance(discount, str) and discount.strip():
        bottom_row = f'<span class="chip" style="background:#E85D7A;color:#FDF6E3;font-weight:800;font-size:12.5px;padding:4px 11px">{html.escape(discount)}</span>'
    else:
        bottom_row = houses_html

    heart_class = "rb-fav-heart filled" if is_fav else "rb-fav-heart"
    heart = f'<span class="{heart_class}" onclick="rbClickChip(\'fav_restaurant_click\',\'{row["restaurant_id"]}\')">&#9829;</span>'

    # External review links, shown as plain "Yelp" / "Google Map" words
    # rather than the raw URL, opening in a new tab.
    links = []
    yelp_url = row.get("yelp_url")
    if isinstance(yelp_url, str) and yelp_url.strip():
        links.append(f'<a href="{html.escape(yelp_url, quote=True)}" target="_blank" rel="noopener" class="rb-restaurant-link">Yelp</a>')
    google_url = row.get("google_maps_url")
    if isinstance(google_url, str) and google_url.strip():
        links.append(f'<a href="{html.escape(google_url, quote=True)}" target="_blank" rel="noopener" class="rb-restaurant-link">Google Map</a>')
    links_row = f'<div class="rb-restaurant-tile-links">{" &middot; ".join(links)}</div>' if links else ""

    return f'''
    <div class="rb-restaurant-tile">
      <div class="rb-restaurant-photo-top" style="{photo_bg}">
        {rating_badge}
        {heart}
      </div>
      <div class="rb-restaurant-tile-body">
        <p class="rb-restaurant-name">{html.escape(name)}</p>
        <p class="rb-restaurant-category">{html.escape(category)}</p>
        <div class="rb-restaurant-tile-bottom">{bottom_row}</div>
        {links_row}
      </div>
    </div>'''


def _activity_card_html(row, is_fav: bool) -> str:
    """One activity deal tile for the Draw Chance page — same tile template
    as _restaurant_card_html above (reuses the same rb-restaurant-* classes,
    since visually it's the same "deal card" component), sourced from
    activity + activity_category instead of restaurant. No rating or
    Yelp/Google links here (that data doesn't exist for activities); price
    is bucketed into the same house-icon tiers off price_usd instead of a
    $ range string."""
    name = row.get("activity_name") or "Activity"
    category = row.get("category_name") or ""
    cat_img = _activity_category_image(category)
    if cat_img:
        photo_bg = f"background-image:url('{cat_img}');background-size:cover;background-position:center"
    else:
        gradient = FALLBACK_GRADIENTS[hash(name) % len(FALLBACK_GRADIENTS)]
        photo_bg = f"background:{gradient}"

    price = row.get("price_usd")
    if pd.notna(price):
        tier = 1 if price <= 15 else 2 if price <= 30 else 3 if price <= 60 else 4
    else:
        tier = 1
    houses_html = "".join('<span class="house"></span>' for _ in range(tier))

    discount = row.get("discount_label")
    if isinstance(discount, str) and discount.strip():
        bottom_row = f'<span class="chip" style="background:#E85D7A;color:#FDF6E3;font-weight:800;font-size:12.5px;padding:4px 11px">{html.escape(discount)}</span>'
    else:
        bottom_row = houses_html

    heart_class = "rb-fav-heart filled" if is_fav else "rb-fav-heart"
    heart = f'<span class="{heart_class}" onclick="rbClickChip(\'fav_activity_click\',\'{row["activity_id"]}\')">&#9829;</span>'

    return f'''
    <div class="rb-restaurant-tile">
      <div class="rb-restaurant-photo-top" style="{photo_bg}">
        {heart}
      </div>
      <div class="rb-restaurant-tile-body">
        <p class="rb-restaurant-name">{html.escape(name)}</p>
        <p class="rb-restaurant-category">{html.escape(category)}</p>
        <div class="rb-restaurant-tile-bottom">{bottom_row}</div>
      </div>
    </div>'''


def _chance_card_html(row) -> str:
    """One Monopoly-style chance card: the hand-drawn Dining/Activity card
    art, with the live pick's name + real coupon overlaid in the cream panel
    near the bottom of the card (where the static art has its '5% discount'
    callout). `row` comes from the DB architect's v_downtime_chance_cards
    view (06_chance_cards.sql) — every row it returns already has a coupon
    attached via an inner join, so the discount always has real content
    here (no fallback needed)."""
    category = "Dining" if row["item_type"] == "restaurant" else "Activity"
    img = "chance_card_dining.jpg" if category == "Dining" else "chance_card_activity.jpg"
    name = row.get("item_name") or "Mystery pick"
    discount = row.get("discount_label") or ""
    desc = row.get("coupon_desc") or ""
    sponsor_name = row.get("sponsor_name")
    sponsor_badge = (
        f'<p style="font-size:11px;font-weight:700;color:#4A1B0C;opacity:.7;margin:2px 0 0;letter-spacing:0.04em;text-transform:uppercase">Presented by {html.escape(sponsor_name)}</p>'
        if sponsor_name else ""
    )

    # Save button carries the pick's details as data-* attributes so the
    # JS click handler (rbSaveChance) can forward them to Shiny as a real
    # input event — that's what makes them show up on the Summary page.
    name_attr = html.escape(name, quote=True)
    discount_attr = html.escape(discount, quote=True)
    desc_attr = html.escape(desc, quote=True)
    category_attr = html.escape(category, quote=True)

    # Wrapped in a 3D flip container: starts showing the navy "?" back face,
    # then rotates to reveal the real card. It's pure CSS (rbCardFlip
    # keyframes below), so it auto-plays every time Shiny swaps in a fresh
    # chance_pick div — no JS trigger needed.
    return f'''
    <div class="rb-flip-card">
      <div class="rb-flip-card-inner">
        <div class="rb-flip-face rb-flip-face-back">
          <div style="font-size:56px;color:#FFD84D;font-weight:900;line-height:1">?</div>
          <div style="font-size:12px;color:#FDF6E3;font-weight:800;letter-spacing:0.14em;margin-top:8px">CHANCE</div>
        </div>
        <div class="rb-flip-face rb-flip-face-front">
          <img src="{img}" alt="{category} chance card">
          <div class="rb-chance-card-overlay">
            <div style="background:#E85D7A;color:#FDF6E3;font-size:14px;font-weight:800;padding:5px 14px;border-radius:10px;display:inline-block;margin-bottom:6px;letter-spacing:0.03em">{discount}</div>
            <p style="font-size:21px;font-weight:800;color:#1B2A4A;margin:0 0 5px;line-height:1.15">{name}</p>
            <p style="font-size:15px;color:#4A3B22;opacity:.85;margin:0;line-height:1.25">{desc}</p>
            {sponsor_badge}
          </div>
        </div>
      </div>
    </div>
    <div class="rb-cta" style="display:inline-block;background:#FFD84D;border:1.5px solid #1B2A4A;color:#1B2A4A;font-size:14px;font-weight:700;padding:10px 22px;border-radius:16px;margin-top:16px;cursor:pointer" data-name="{name_attr}" data-discount="{discount_attr}" data-desc="{desc_attr}" data-category="{category_attr}" onclick="rbSaveChance(this)">Save</div>'''


def _map_html(points, legend, height=150) -> str:
    """Generic lat/lon dot-map: projects any list of {lat, lon, color, label}
    points into a box of the given height, plus a color legend underneath.
    Reused by the Plan Shows venue map (colored by stage type) and, later,
    the Select Stay map (colored by price tier)."""
    pts = [p for p in points if pd.notna(p.get("lat")) and pd.notna(p.get("lon"))]
    if not pts:
        return f'<div class="dashedbox" style="height:{height}px">No map data yet</div>'
    lats = [p["lat"] for p in pts]
    lons = [p["lon"] for p in pts]
    lat_span = (max(lats) - min(lats)) or 0.001
    lon_span = (max(lons) - min(lons)) or 0.001
    lat_min, lon_min = min(lats), min(lons)
    dots = ""
    for p in pts:
        x_pct = 6 + (p["lon"] - lon_min) / lon_span * 88
        y_pct = 6 + (1 - (p["lat"] - lat_min) / lat_span) * 88
        dots += f'<div class="rb-map-pin" style="left:{x_pct:.1f}%;top:{y_pct:.1f}%;background:{p["color"]}" title="{p["label"]}"></div>'
    legend_html = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:{color};display:inline-block"></span>{label}</span>'
        for color, label in legend
    )
    return f'''<div class="rb-map" style="height:{height}px">{dots}</div>
    <div style="display:flex;flex-wrap:wrap;margin-top:10px;font-size:10px;color:#FDF6E3;text-shadow:0 1px 4px rgba(0,0,0,0.4)">{legend_html}</div>'''


# ── Shared CSS ────────────────────────────────────────────────────────────────
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Bungee&family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {
  --font-display:'Bungee',cursive;
  --font-body:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  --text-xs:11px; --text-sm:12.5px; --text-base:14px; --text-md:16px;
  --text-lg:19px; --text-xl:24px; --text-2xl:32px;
}
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:var(--font-body); background:#fff; margin:0; padding:0; overflow-x:hidden; }
.chip { display:inline-block; font-size:14px; padding:8px 14px; border-radius:14px; }
input { border:1px solid #ccc; border-radius:6px; padding:10px; font-size:14px; font-family:inherit; }
.dashedbox { background:rgba(255,255,255,0.85); border:1.5px dashed #1B2A4A; border-radius:6px; display:flex; align-items:center; justify-content:center; color:#1B2A4A; opacity:.75; font-size:13px; }
.token { background:#1B2A4A; color:#FFD84D; font-size:12px; font-weight:700; padding:6px 12px; border-radius:10px; display:inline-flex; align-items:center; gap:4px; transform:rotate(-4deg); box-shadow:1px 2px 0 rgba(0,0,0,.15); white-space:nowrap; }
.rb-artist-card-wrap { background:rgba(253,246,227,0.85); border:2px solid rgba(27,42,74,0.75); border-radius:14px; overflow:hidden; box-shadow:0 3px 0 rgba(27,42,74,0.12); backdrop-filter:blur(2px); }
.rb-artist-photo-frame { padding:8px 8px 0; position:relative; }
.rb-artist-photo-inner { width:100%; aspect-ratio:1/1; border-radius:8px; overflow:hidden; background:#1B2A4A; }
.rb-artist-caption { padding:8px 10px 10px; text-align:center; }
.rb-artist-caption .name { color:#1B2A4A; font-weight:800; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rb-artist-caption .meta { color:#6b6248; font-weight:500; letter-spacing:0.03em; margin:1px 0 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rb-headliner-card { position:relative; aspect-ratio:3/4; border-radius:14px; overflow:hidden; background:#1B2A4A; box-shadow:0 8px 20px rgba(0,0,0,0.35); }
.rb-headliner-overlay { position:absolute; inset:0; background:linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.15) 55%, rgba(0,0,0,0) 75%); }
.rb-headliner-caption { position:absolute; left:0; right:0; bottom:0; padding:14px; z-index:2; }
.rb-headliner-caption .name { color:#fff; font-weight:800; font-size:20px; margin:0 0 3px; text-shadow:0 2px 6px rgba(0,0,0,0.5); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rb-headliner-caption .meta { color:rgba(255,255,255,0.85); font-size:14px; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* Plan Shows: "Landed" stamp on an already-added show, made clickable so
   attendees can change their mind — hover swaps the label + color to a
   "Remove" cue before they click. */
.rb-landed-token { cursor:pointer; transition:background .15s ease; }
.rb-landed-hover-text { display:none; }
.rb-landed-token:hover { background:#C0392B; }
.rb-landed-token:hover .rb-landed-default-text { display:none; }
.rb-landed-token:hover .rb-landed-hover-text { display:inline; }
.house { display:inline-block; width:0; height:0; border-left:6px solid transparent; border-right:6px solid transparent; border-bottom:7px solid #27500A; position:relative; margin:0 1px; }
.house::after { content:''; position:absolute; left:-5px; top:7px; width:10px; height:6px; background:#27500A; }
.deed { position:absolute; top:-8px; right:12px; background:#FFD84D; border:1.5px solid #1B2A4A; color:#1B2A4A; font-size:11px; font-weight:700; padding:4px 10px; border-radius:4px; transform:rotate(6deg); box-shadow:1px 2px 0 rgba(0,0,0,.15); }

/* overflow:hidden used to live here, but any ancestor with overflow other
   than visible silently breaks position:sticky on elements inside it (the
   sticky stepper). Moved the horizontal-clipping intent up to body instead,
   which is the actual scrolling container and safe for sticky. */
.rb-frame { max-width:none; width:100%; margin:0; background:#fff; }
.rb-page { display:none; }
.rb-page.active { display:block; }
.rb-cta { cursor:pointer; }

/* ── Website nav + hero (landing page) ───────────────────────────────────── */
.rb-navbar { display:flex; align-items:center; gap:24px; background:#1B2A4A; padding:18px 40px; }
.rb-logo { color:#fff; font-family:var(--font-display); font-weight:400; font-size:1.05rem; letter-spacing:0.02em; white-space:nowrap; }
.rb-nav-links { margin-left:auto; display:flex; align-items:center; gap:24px; flex-wrap:wrap; }
.rb-nav-link { color:rgba(255,255,255,0.85) !important; font-family:var(--font-body); font-weight:400; font-size:0.85rem; letter-spacing:0.06em; text-transform:uppercase; text-decoration:none !important; cursor:pointer; transition:color 0.15s ease; }
.rb-nav-link:hover { color:#FFD84D !important; }
.rb-buy-btn { background:#E85D7A !important; color:#fff !important; font-family:var(--font-body); font-weight:600; font-size:0.8rem; letter-spacing:0.04em; text-transform:uppercase; text-decoration:none !important; padding:10px 22px; border-radius:999px; white-space:nowrap; cursor:pointer; box-shadow:0 6px 16px rgba(232,93,122,0.4); transition:transform 0.15s ease; }
.rb-buy-btn:hover { transform:translateY(-1px); }

.rb-hero { position:relative; aspect-ratio:16/7; min-height:0; overflow:hidden; }
.rb-hero-bg { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; object-position:center 25%; z-index:0; }
.rb-hero-venue-badge { position:absolute; right:40px; bottom:24px; z-index:2; color:#fff; font-weight:800; font-size:1.1rem; letter-spacing:0.01em; text-shadow:0 2px 10px rgba(0,0,0,0.45); }

/* Pass Go sections below the hero reuse the hero photo as their background
   (tinted to keep each section's accent color) instead of a flat, unrelated
   solid color, so the page reads as one continuous scene rather than blocks */
/* Pass Go: ONE fixed background photo behind the whole page (nav, posters,
   GO finale) instead of each section carrying its own separate cropped
   copy. background-attachment:fixed keeps it pinned in the viewport while
   the content scrolls over it — the "frozen" parallax effect. */
.rb-landing-fixed-bg {
  background-image: linear-gradient(rgba(10,16,32,0.58), rgba(10,16,32,0.58)), url('Landingpage.jpeg');
  background-size: cover;
  background-position: center 25%;
  background-attachment: fixed;
}
@media (max-width:720px) {
  /* background-attachment:fixed is unreliable on mobile Safari/Chrome — fall back to scroll */
  .rb-landing-fixed-bg { background-attachment: scroll; }
}

/* The poster photo itself, full brightness (no dark tint), shown right
   below the nav before the dimmed sections start further down the page.
   Sized to the image's own aspect ratio (not cropped to a fixed vh) so the
   whole picture is visible and Daily Posters naturally sits below it. */
.rb-landing-hero-space { position:relative; overflow:hidden; line-height:0; }
.rb-landing-hero-img { width:100%; height:auto; display:block; }

.rb-posters-photo-bg { background:transparent; padding:24px; }

/* Same fixed dimmed-photo backdrop as Pass Go, reused behind every other
   page's body (below the stepper) so the whole site reads as one
   continuous board scene instead of separate white page breaks. */
.rb-shadow-page {
  background-image: linear-gradient(rgba(10,16,32,0.62), rgba(10,16,32,0.62)), url('Landingpage.jpeg');
  background-size: cover;
  background-position: center 25%;
  background-attachment: fixed;
}
@media (max-width:720px) {
  .rb-shadow-page { background-attachment: scroll; }
}

/* Stepper stays pinned to the top of the viewport while the rest of the
   page scrolls underneath it — same fixed photo backdrop as the page body
   (rb-shadow-page) so it still reads as one continuous scene, plus a
   z-index so it renders above the scrolling content and a soft shadow so
   it reads as an intentional floating nav bar rather than a seam. */
.rb-sticky-stepper {
  position: sticky;
  top: 0;
  z-index: 50;
  box-shadow: 0 6px 14px rgba(0,0,0,0.25);
}
@media (max-width:720px) {
  /* background-attachment:scroll kicks in on mobile (see above), so a
     sticky element with a scroll-attached background would drag its own
     backdrop along as it stays pinned — fall back to a solid color instead. */
  .rb-sticky-stepper { background-image:none; background-color:#0F1B33; }
}

/* GO finale: the board-loop payoff at the END of Pass Go, after the daily
   posters, so landing on GO feels like completing a lap of the board */
.rb-go-finale { background:transparent; padding:16px 24px 44px; display:flex; flex-direction:column; align-items:center; gap:18px; }
.rb-go-finale-caption { font-size:16px; font-weight:700; color:#FDF6E3; text-align:center; max-width:360px; margin:0; }

.rb-cta-banner { background:#1B2A4A; padding:28px; text-align:center; }
.rb-cta-banner-btn { display:inline-block; background:#E85D7A !important; color:#fff !important; font-weight:800; font-size:1rem; letter-spacing:0.04em; text-transform:uppercase; text-decoration:none !important; padding:16px 44px; border-radius:999px; cursor:pointer; box-shadow:0 10px 24px rgba(232,93,122,0.4); transition:transform 0.15s ease; }
.rb-cta-banner-btn:hover { transform:translateY(-2px); }

/* Shiny's action button, reskinned to match the dashed "Draw again" pill */
.rb-draw-btn { all:unset; box-sizing:border-box; cursor:pointer; display:inline-flex; align-items:center; gap:8px; background:#FDF6E3; border:1.5px dashed #1B2A4A; color:#1B2A4A; font-size:14px; font-weight:700; padding:10px 22px; border-radius:16px; font-family:inherit; margin-top:16px; }
.rb-draw-btn:hover { background:#F4D9A0; }

/* Draw Chance card: a 3D flip reveal. Starts on the navy "?" back face,
   rotates to the hand-drawn Dining/Activity card art with the live pick's
   name + description overlaid in a cream panel near the bottom (over the
   art's own '5% discount' callout area). Pure CSS animation — replays
   automatically every time Shiny swaps in a fresh card, no JS needed. */
.rb-flip-card { perspective:1400px; max-width:380px; margin:0 auto; }
.rb-flip-card-inner { position:relative; transform-style:preserve-3d; animation:rbCardFlip .8s cubic-bezier(.22,.85,.32,1.1) forwards; }
@keyframes rbCardFlip { from { transform:rotateY(180deg); } to { transform:rotateY(0deg); } }
.rb-flip-face { backface-visibility:hidden; -webkit-backface-visibility:hidden; border-radius:16px; box-shadow:0 10px 28px rgba(0,0,0,0.4); }
.rb-flip-face-back { position:absolute; inset:0; transform:rotateY(180deg); background:#1B2A4A; border:2px solid #FFD84D; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.rb-flip-face-front { position:relative; }
.rb-flip-face-front img { width:100%; display:block; border-radius:16px; }
.rb-chance-card-overlay { position:absolute; left:6%; right:6%; top:62%; bottom:6%; background:#F3EAD6; border-radius:6px; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:8px 10px; text-align:center; overflow:hidden; }

/* Draw Chance's browsable restaurant deal list, below the flip card. */
.rb-restaurant-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; }
.rb-restaurant-tile { background:#FDF6E3; border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }
.rb-restaurant-photo-top { position:relative; height:88px; display:flex; align-items:center; justify-content:center; }
.rb-restaurant-emoji { font-size:26px; opacity:.55; }
.rb-restaurant-rating { position:absolute; top:6px; left:6px; background:#fff; border-radius:10px; padding:3px 8px; font-size:13px; font-weight:700; color:#1B2A4A; }
.rb-restaurant-tile-body { padding:9px 10px 12px; }
.rb-restaurant-name { font-size:16px; font-weight:700; color:#1B2A4A; margin:0 0 3px; line-height:1.2; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.rb-restaurant-category { font-size:13px; font-weight:700; color:#6b6b6b; margin:0 0 7px; }
.rb-restaurant-tile-bottom { display:flex; align-items:center; min-height:12px; }
.rb-restaurant-tile-links { margin-top:7px; }
.rb-restaurant-link { font-size:11.5px; font-weight:800; color:#1B2A4A; text-decoration:underline; margin-right:10px; }
.rb-restaurant-link:hover { color:#E85D7A; }
.rb-fav-heart { position:absolute; top:6px; right:6px; cursor:pointer; font-size:22px; color:rgba(255,255,255,0.9); line-height:1; background:rgba(0,0,0,0.2); border-radius:50%; width:34px; height:34px; display:flex; align-items:center; justify-content:center; }
.rb-fav-heart.filled { color:#E85D7A; background:#fff; }

/* Lineup photo grid */
/* Non-headliner cards: smaller and capped (120-150px) so headliners (which
   override this with their own larger 170-200px capped style) stand out as
   the more "charming" ones. auto-fit still fills leftover row space, just
   bounded by the max instead of stretching unbounded like the old 1fr did. */
.rb-lineup-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 200px)); gap:14px; padding:16px 20px; background:transparent; justify-content:space-between; }
.rb-headliner-scroll { display:flex; gap:14px; overflow-x:auto; padding:6px 20px 24px; scroll-snap-type:x proximity; -webkit-overflow-scrolling:touch; }
.rb-headliner-scroll .rb-headliner-card { flex:1 1 200px; max-width:260px; scroll-snap-align:start; }
/* Social link-out row under each lineup card (Spotify, etc.) */
.rb-social-row { display:flex; justify-content:center; gap:8px; margin-top:6px; }
.rb-social-row a { display:flex; align-items:center; justify-content:center; width:38px; height:38px; border-radius:50%; background:rgba(0,0,0,0.55); box-shadow:0 2px 6px rgba(0,0,0,0.3); }
.rb-social-row a:hover { background:rgba(0,0,0,0.8); transform:scale(1.06); }

/* Pass Go's circular GO button, a Shiny action button reskinned to match
   the original CSS-only circle */
.rb-go-btn-wrap { position:relative; display:flex; align-items:center; gap:10px; }
.rb-go-btn.btn.btn-default.action-button { all:unset; box-sizing:border-box; cursor:pointer; width:220px; height:220px; display:block; background:transparent !important; border:none !important; }
.rb-go-btn .action-label { display:block; width:100%; height:100%; }
.rb-go-btn img { width:100%; height:100%; object-fit:contain; filter:drop-shadow(0 8px 20px rgba(0,0,0,0.35)) hue-rotate(-20deg) saturate(1.1); transition:transform 0.15s ease; }
.rb-go-btn:hover img { transform:translateY(-2px) scale(1.03); }

/* Plan Shows: filter bar, performance rows, jail-card conflict warning, map */
.rb-filter-row { display:flex; gap:10px; padding:4px 24px 18px; flex-wrap:wrap; align-items:center; }
.rb-filter-row .form-select, .rb-filter-row .form-control { border:1px solid #4A5A80 !important; background:#2C3E63 !important; color:#FDF6E3 !important; border-radius:8px !important; font-size:14px !important; font-weight:400 !important; text-transform:uppercase !important; letter-spacing:0.03em !important; padding:9px 12px !important; box-shadow:none !important; }
.rb-filter-row .form-select option { background:#2C3E63; color:#FDF6E3; text-transform:none; }
/* Chance page's restaurant/activity filter dropdowns — bumped bigger than
   the base .rb-filter-row size above (which Plan Shows also uses). */
.rb-filter-row-lg .form-select, .rb-filter-row-lg .form-control { font-size:18px !important; padding:12px 16px !important; }
.rb-filter-row-lg .form-select option { font-size:18px; }
.rb-filter-row .shiny-input-container { margin-bottom:0 !important; width:auto; }
.rb-perf-row { background:transparent; display:flex; align-items:center; gap:12px; padding:14px 24px; border-bottom:1px solid rgba(255,255,255,0.18); }
.rb-add-btn { cursor:pointer; background:#1B2A4A; color:#FDF6E3; font-size:13px; font-weight:700; padding:9px 18px; border-radius:12px; white-space:nowrap; }
.rb-add-btn:hover { background:#2C3E63; }
.rb-jail-card { border:2px solid #C0392B; background:#FAECE7; border-radius:10px; padding:12px 14px; margin:12px 20px; display:flex; align-items:center; gap:10px; }
.rb-map { position:relative; background:#9AD3E8; border-radius:12px; overflow:hidden; }
.rb-map-pin { position:absolute; width:14px; height:14px; border-radius:50%; border:2px solid #fff; transform:translate(-50%,-50%); box-shadow:0 1px 3px rgba(0,0,0,.3); }

/* My 3-Day Schedule: per-day board-path of added shows + free-time gaps */
.rb-board-day { flex:1; min-width:230px; }
.rb-board-title { font-size:20px; font-weight:700; color:#FDF6E3; margin:0 0 14px; text-shadow:0 1px 4px rgba(0,0,0,0.4); }
.rb-board-path { border-left:2px dotted #ccc; margin-left:10px; padding-left:18px; }
.rb-board-tile { position:relative; margin-bottom:14px; }
.rb-board-tile::before { content:''; position:absolute; left:-25px; top:8px; width:11px; height:11px; border-radius:50%; background:#1B2A4A; }
.rb-board-tile.free::before { background:#fff; border:2px dashed #999; }
.rb-tile-card { border-radius:8px; padding:12px 14px; }
.rb-tile-card.show { background:#FDF6E3; border:1.5px solid #1B2A4A; }
.rb-tile-card.next { border-color:#FFD84D; box-shadow:0 0 0 2px #FFD84D; }
.rb-tile-card.free { border:1.5px dashed #999; background:#fafafa; cursor:pointer; }
.rb-tile-card.free:hover { background:#F4D9A0; }
.rb-tile-bus { display:inline-flex; align-items:center; gap:5px; background:#FFD84D; border:1px solid #1B2A4A; border-radius:8px; padding:3px 9px; font-size:12px; font-weight:700; color:#1B2A4A; margin-bottom:7px; }

/* Conflict-jail popup (shown when the DB's conflict trigger blocks an Add) */
.modal-content { border-radius:16px; }
.rb-jail-dismiss-btn { all:unset; cursor:pointer; background:#FAECE7; color:#791F1F; font-weight:700; font-size:12px; padding:10px 22px; border-radius:14px; display:inline-block; font-family:inherit; }
.rb-jail-dismiss-btn:hover { background:#F4D9A0; }

@media (max-width:720px) {
  .rb-hero { aspect-ratio:4/5; }
}

/* Full-lineup popup, opened by clicking any daily poster on Pass Go */
.rb-lineup-modal-overlay { display:none; position:fixed; inset:0; background:rgba(10,16,32,0.85); z-index:1000; align-items:center; justify-content:center; padding:24px; }
.rb-lineup-modal-overlay.active { display:flex; }
.rb-lineup-modal-img { max-width:90vw; max-height:90vh; border-radius:12px; box-shadow:0 20px 60px rgba(0,0,0,0.5); display:block; }
.rb-lineup-modal-close { position:absolute; top:20px; right:28px; width:40px; height:40px; border-radius:50%; background:#FDF6E3; border:2px solid #1B2A4A; color:#1B2A4A; font-size:20px; font-weight:800; display:flex; align-items:center; justify-content:center; cursor:pointer; line-height:1; }
"""

JS = """
function rbShow(n){
  document.querySelectorAll('.rb-page').forEach(function(el){
    el.classList.toggle('active', el.dataset.page == n);
  });
  var frame = document.querySelector('.rb-frame');
  if (frame) { frame.scrollIntoView({behavior:'smooth', block:'start'}); }
}
function rbAddShow(performanceId){
  if (window.Shiny) {
    Shiny.setInputValue('add_click', performanceId, {priority: 'event'});
  }
}
function rbRemoveShow(performanceId){
  if (window.Shiny) {
    Shiny.setInputValue('remove_click', performanceId, {priority: 'event'});
  }
}
function rbAddStay(el){
  if (window.Shiny) {
    Shiny.setInputValue('add_stay_click', {name: el.dataset.name, zone: el.dataset.zone}, {priority: 'event'});
  }
}
function rbRemoveStay(){
  if (window.Shiny) {
    Shiny.setInputValue('remove_stay_click', true, {priority: 'event'});
  }
}
function rbSelectTier(key){
  if (window.Shiny) {
    Shiny.setInputValue('select_tier_click', key, {priority: 'event'});
  }
}
function rbPayClick(){
  // In-app modal instead of a browser alert() — alert() always shows the
  // page's own address ("127.0.0.1:8000 says...") as a header, which reads
  // as a broken/dev artifact rather than part of the site.
  if (window.Shiny) {
    Shiny.setInputValue('pay_click', Date.now(), {priority: 'event'});
  }
}
function rbClickChip(inputId, value){
  // Generic chip-click helper: sends the clicked value to a Shiny input;
  // the server decides how to toggle it (single-select vs multi-select).
  if (window.Shiny) {
    Shiny.setInputValue(inputId, value, {priority: 'event'});
  }
}
function rbOpenLineupModal(){
  // Shows the full 3-day lineup graphic in a popup when a daily poster is
  // clicked on Pass Go (replaces the earlier "jump to Lineup page" behavior).
  var el = document.getElementById('rbLineupModal');
  if (el) { el.classList.add('active'); }
}
function rbCloseLineupModal(){
  var el = document.getElementById('rbLineupModal');
  if (el) { el.classList.remove('active'); }
}
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape') { rbCloseLineupModal(); }
});
function rbSaveChance(el){
  // Chance card's Save button: forward the card's details (stashed on the
  // element as data-* attributes) to Shiny so the server can remember it
  // and show it on the Summary page, then jump there.
  if (window.Shiny) {
    Shiny.setInputValue('save_chance_click', {
      name: el.dataset.name,
      discount: el.dataset.discount,
      desc: el.dataset.desc,
      category: el.dataset.category
    }, {priority: 'event'});
  }
  rbShow(7);
}
if (window.Shiny) {
  $(document).on('shiny:connected', function() {
    Shiny.addCustomMessageHandler('rbShowPage', function(msg) {
      rbShow(msg.page);
    });
  });
}
"""


# ── Page 1 · Pass Go (landing) ──────────────────────────────────────────────
# Split into static top (nav + hero + CTA banner) / a real GO button that
# opens a registration modal / LIVE daily posters / static color stripe.
PAGE_1_NAV = """
<div class="rb-navbar">
  <div class="rb-logo">🎸 ROCK &amp; BEACH</div>
  <div class="rb-nav-links">
    <span class="rb-nav-link" onclick="rbShow(1)">HOME</span>
    <span class="rb-nav-link" onclick="rbShow(2)">LINEUP</span>
  </div>
  <span class="rb-buy-btn" onclick="rbShow(8)">BUY TICKETS</span>
</div>
"""


# Full 3-day lineup graphic, shown as a popup when any daily poster is
# clicked. Sits outside the .rb-page structure (appended once, right after
# the page frame) so it can overlay whichever page is currently active.
LINEUP_MODAL_HTML = """
<div id="rbLineupModal" class="rb-lineup-modal-overlay" onclick="if(event.target===this){rbCloseLineupModal()}">
  <span class="rb-lineup-modal-close" onclick="rbCloseLineupModal()">&times;</span>
  <img src="lineup_poster.jpg" class="rb-lineup-modal-img" alt="Full 3-day festival lineup">
</div>
"""

# ── Page 2 · View Lineup (spotlight + cards are LIVE, rest is static) ───────
PAGE_2_CHIPS = """
<div style="background:#fff;padding:16px 20px 6px;display:flex;gap:8px">
  <span class="chip" style="background:#1B2A4A;color:#FDF6E3;font-weight:700">Headliner</span>
  <span class="chip" style="border:1px solid #ccc;color:#666">Support</span>
  <span class="chip" style="border:1px solid #ccc;color:#666">Rising</span>
</div>
"""

# ── Page 3 · Plan Shows (filters/list/map/conflict are all LIVE) ───────────
PAGE_3_TITLE = """
<div style="background:transparent;padding:20px 24px 8px">
  <p style="font-size:22px;font-weight:700;color:#FDF6E3;margin:0 0 14px;text-shadow:0 2px 8px rgba(0,0,0,0.4)">Plan shows</p>
</div>
"""


# ── Page 4 · My 3-Day Schedule (day columns are LIVE, rest is static) ───────
PAGE_4_INTRO = """
<div style="background:transparent;padding:20px 24px 10px">
  <p style="font-size:22px;font-weight:700;color:#FDF6E3;margin:0;text-shadow:0 2px 8px rgba(0,0,0,0.4)">My 3-day schedule</p>
</div>
"""

PAGE_4_CTA = """
<div style="background:transparent;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
  <span style="font-size:14px;color:#FDF6E3;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Looks good? Move on to lodging.</span>
  <span onclick="rbShow(6)" class="rb-cta" style="background:#FFD84D;color:#1B2A4A;font-size:14px;font-weight:700;padding:10px 18px;border-radius:14px">Continue to select stay</span>
</div>
"""

# ── Page 5 · Select Stay (property cards are LIVE, rest is static) ─────────
PAGE_5_TITLE = """
<div style="background:transparent;padding:20px 24px 4px">
  <p style="font-size:22px;font-weight:700;color:#FDF6E3;margin:0;text-shadow:0 2px 8px rgba(0,0,0,0.4)">Select stay</p>
</div>
"""

# Zone chips filter on property.section_of_ac via an ILIKE substring match
# (label shown to the user -> substring sent to the query). Price tier chips
# are a multi-select over property.price_tier's exact values, grouped by
# house-count the same way _stay_card already displays them.
ZONE_CHIPS = [("Boardwalk / Casino", "Boardwalk"), ("Atlantic Ave", "Atlantic Ave"), ("Marina", "Marina")]
# tier key -> (house count shown, list of exact property.price_tier values it covers)
PRICE_TIER_CHIPS = [("1", 1, ["Budget", "Midscale"]), ("2", 2, ["Upscale"]), ("3", 3, ["Luxury"])]

PAGE_5_MAP_LABEL = """
<p style="font-size:15px;font-weight:700;color:#FDF6E3;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Stay map &middot; venues &amp; stays</p>
"""

# ── Page 6 · Draw Chance (dining pick is LIVE + re-rollable) ───────────────
PAGE_6_INTRO = """
<div style="background:transparent;padding:20px 24px">
  <p style="font-size:22px;font-weight:700;color:#FDF6E3;margin:0 0 14px;text-shadow:0 2px 8px rgba(0,0,0,0.4)">Draw chance</p>
</div>
"""

# ── Page 7 · Trip Summary ───────────────────────────────────────────────────
# Fully live now: header/shows/budget/footer are all @render.ui functions in
# the server section below (trip_summary_header, trip_summary_shows,
# trip_budget_summary, trip_summary_footer), reading real session +
# database state instead of hardcoded placeholder text.

# ── Page 8 · The Bank ───────────────────────────────────────────────────────
PAGE_8_TOP = """
<div style="background:transparent;padding:20px 24px">
  <p style="font-size:22px;font-weight:700;color:#FDF6E3;margin:0 0 6px;text-shadow:0 2px 8px rgba(0,0,0,0.4)">The bank</p>
  <p style="font-size:14px;color:#E4D8C4;margin:0;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Choose your ticket tier</p>
</div>
"""

# key -> (image filename, display name, price)
TICKET_TIERS = {
    "ga": ("Community%20pass.png", "Community Chest Pass", 399),
    "vip": ("Rail%20Road%20Pass.png", "Railroad Pass", 599),
    "club": ("Boardwalk%20Pass.png", "Boardwalk & Park Place", 999),
}

PAGE_8_BOTTOM = """
<div style="background:transparent;padding:22px 24px">
  <div style="background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;display:flex;align-items:center;gap:14px;margin-bottom:12px;flex-wrap:wrap">
    <div style="flex:1"><p style="font-size:15px;font-weight:700;margin:0">Reservation emailed</p><p style="font-size:13px;color:#888;margin:3px 0 0">Sent to you@email.com &middot; includes ticket, stay, and schedule</p></div>
    <span class="chip" style="border:1px solid #ccc;background:#fff">Resend</span>
  </div>
  <div style="display:flex;gap:10px"><input placeholder="Add another email (optional)" style="flex:1"><span style="background:#1B2A4A;color:#FDF6E3;font-size:14px;font-weight:700;padding:11px 16px;border-radius:10px">Send</span></div>
</div>
"""


def _page(idx: int, *children) -> ui.Tag:
    cls = "rb-page active" if idx == 0 else "rb-page"
    return ui.div(*children, class_=cls, **{"data-page": str(idx + 1)})


app_ui = ui.page_fluid(
    ui.tags.style(CSS),
    ui.div(
        _page(
            0,
            ui.div(
                ui.HTML(PAGE_1_NAV),
                ui.div(
                    ui.HTML('<img src="Landingpage.jpeg" class="rb-landing-hero-img">'),
                    class_="rb-landing-hero-space",
                ),
                ui.div(
                    ui.output_ui("daily_posters"),
                    class_="rb-posters-photo-bg",
                ),
                ui.div(
                    ui.div(
                        ui.input_action_button("join_go", ui.HTML('<img src="go_button_3d_transparent_v2.gif" alt="GO">'), class_="rb-go-btn"),
                        class_="rb-go-btn-wrap",
                    ),
                    class_="rb-go-finale",
                ),
                class_="rb-landing-fixed-bg",
            ),
        ),
        _page(
            1,
            ui.div(
                ui.HTML(stepper_html(0)),
                ui.output_ui("lineup_cards"),
                class_="rb-shadow-page",
            ),
        ),
        _page(
            2,
            ui.div(
                ui.HTML(stepper_html(1)),
                ui.HTML(PAGE_3_TITLE),
                ui.div(
                    ui.div(
                        ui.div(
                            ui.input_select("pf_day", "", choices={"": "All days", "1": "Fri Aug 21", "2": "Sat Aug 22", "3": "Sun Aug 23"}),
                            ui.input_select("pf_time", "", choices={"": "All times"}),
                            ui.input_select("pf_venue", "", choices={"": "All venues"}),
                            ui.input_text("pf_search", "", placeholder="Search artist..."),
                            class_="rb-filter-row",
                            style="background:transparent",
                        ),
                        ui.output_ui("conflict_warning"),
                        ui.output_ui("performance_list"),
                        style="flex:1;min-width:280px",
                    ),
                    ui.div(
                        output_widget("plan_shows_map", height="500px"),
                        style="width:340px;flex-shrink:0;position:sticky;top:16px",
                    ),
                    style="display:flex;gap:20px;align-items:flex-start;padding:0 20px 22px;flex-wrap:wrap",
                ),
                class_="rb-shadow-page",
            ),
        ),
        _page(
            3,
            ui.div(
                ui.HTML(stepper_html(2)),
                ui.HTML(PAGE_4_INTRO),
                ui.output_ui("schedule_days"),
                ui.HTML(PAGE_4_CTA),
                class_="rb-shadow-page",
            ),
        ),
        _page(
            4,
            ui.div(
                ui.HTML(stepper_html(3)),
                ui.HTML(PAGE_6_INTRO),
                ui.output_ui("chance_pick"),
                ui.div(
                    ui.HTML('<p style="font-size:19px;font-weight:700;color:#FDF6E3;margin:0 0 12px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">More restaurant deals</p>'),
                    ui.div(
                        ui.input_select("rest_country", "", choices={"": "All countries"}),
                        ui.input_select("rest_category", "", choices={"": "All types"}),
                        class_="rb-filter-row",
                        style="padding:0 0 12px",
                    ),
                    ui.output_ui("restaurant_price_filter_chips"),
                    ui.output_ui("restaurant_list"),
                    style="background:transparent;padding:8px 24px 24px",
                ),
                ui.div(
                    ui.HTML('<p style="font-size:19px;font-weight:700;color:#FDF6E3;margin:0 0 12px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">More activities</p>'),
                    ui.div(
                        ui.input_select("activity_category_filter", "", choices={"": "All categories"}),
                        class_="rb-filter-row",
                        style="padding:0 0 12px",
                    ),
                    ui.output_ui("activity_list"),
                    style="background:transparent;padding:8px 24px 24px",
                ),
                class_="rb-shadow-page",
            ),
        ),
        _page(
            5,
            ui.div(
                ui.HTML(stepper_html(4)),
                ui.HTML(PAGE_5_TITLE),
                ui.div(
                    ui.div(
                        ui.output_ui("stay_filters"),
                        ui.output_ui("stay_cards"),
                        style="flex:1;min-width:280px",
                    ),
                    ui.div(
                        ui.HTML(PAGE_5_MAP_LABEL),
                        ui.input_checkbox_group(
                            "stay_map_categories", "",
                            choices=["Venue", "Stay", "Dining", "Activity"],
                            selected=["Venue", "Stay"],
                            inline=True,
                        ),
                        output_widget("stay_trip_map", height="500px"),
                        style="width:340px;flex-shrink:0;position:sticky;top:16px",
                    ),
                    style="display:flex;gap:20px;align-items:flex-start;padding:0 24px 26px;flex-wrap:wrap",
                ),
                class_="rb-shadow-page",
            ),
        ),
        _page(6, ui.div(
            ui.HTML(stepper_html(5)),
            ui.output_ui("trip_summary_header"),
            ui.output_ui("trip_progress_icons"),
            ui.output_ui("trip_summary_shows"),
            ui.output_ui("stay_summary"),
            ui.output_ui("chance_save_summary"),
            ui.output_ui("favorite_restaurants_summary"),
            ui.output_ui("favorite_activities_summary"),
            ui.output_ui("trip_budget_summary"),
            ui.output_ui("trip_summary_footer"),
            class_="rb-shadow-page",
        )),
        _page(7, ui.div(
            ui.HTML(stepper_html(6)),
            ui.HTML(PAGE_8_TOP),
            ui.output_ui("bank_content"),
            ui.HTML(PAGE_8_BOTTOM),
            class_="rb-shadow-page",
        )),
        class_="rb-frame",
    ),
    ui.HTML(LINEUP_MODAL_HTML),
    ui.tags.script(JS),
)


def server(input, output, session):
    # Attendee identity for this session, captured at Pass Go / GO signup.
    # Everything downstream (Add a show, Select stay, etc.) writes against
    # this id — there's no separate login system.
    current_attendee = reactive.value(None)

    # ── Page 5: Select Stay zone/price filter chips ──────────────────────
    # Zone is single-select (clicking the active chip again clears it back
    # to "all zones"); price tier is multi-select (defaults to all three
    # tiers selected, i.e. no filter, matching "show everything" default).
    stay_zone = reactive.value(None)
    stay_tiers = reactive.value({"1", "2", "3"})

    @reactive.effect
    @reactive.event(input.stay_zone_click)
    def _toggle_stay_zone():
        clicked = input.stay_zone_click()
        stay_zone.set(None if stay_zone.get() == clicked else clicked)

    @reactive.effect
    @reactive.event(input.stay_tier_click)
    def _toggle_stay_tier():
        clicked = input.stay_tier_click()
        current = set(stay_tiers.get())
        if clicked in current:
            current.discard(clicked)
        else:
            current.add(clicked)
        stay_tiers.set(current)

    @render.ui
    def stay_filters():
        zone_sel = stay_zone.get()
        tier_sel = stay_tiers.get()

        zone_chips = ""
        for label, keyword in ZONE_CHIPS:
            active = zone_sel == keyword
            style = "background:#F0997B;color:#4A1B0C;font-weight:700" if active else "background:#FDF6E3;border:1px solid #ccc;color:#666"
            zone_chips += f'<span class="chip rb-cta" style="{style};cursor:pointer" onclick="rbClickChip(\'stay_zone_click\',\'{keyword}\')">{label}</span>'

        tier_chips = ""
        for key, houses, _values in PRICE_TIER_CHIPS:
            active = key in tier_sel
            style = "background:#FFD84D;color:#1B2A4A;font-weight:700" if active else "background:#FDF6E3;border:1px solid #ccc;color:#666"
            house_icons = "".join('<span class="house"></span>' for _ in range(houses))
            tier_chips += f'<span class="chip rb-cta" style="{style};cursor:pointer" onclick="rbClickChip(\'stay_tier_click\',\'{key}\')">{house_icons}</span>'

        return ui.HTML(f'''
        <div style="background:transparent;padding:0 24px 14px">
          <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">{zone_chips}</div>
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <span style="font-size:14px;color:#FDF6E3;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Price tier:</span>
            {tier_chips}
          </div>
        </div>''')

    # ── Page 1: daily posters (live) ─────────────────────────────────────
    @render.ui
    def daily_posters():
        try:
            posters = queries.get_daily_headliner_posters()
        except Exception as e:
            return ui.HTML(_db_error_box(f"Couldn't reach the database ({e})."))
        cards = "".join(_poster_card(d, posters.get(d)) for d in (1, 2, 3))
        return ui.HTML(f'<div style="display:flex;gap:14px">{cards}</div>')

    # ── Page 1: GO button -> registration modal -> INSERT INTO attendee ──
    join_error = reactive.value("")

    @reactive.effect
    @reactive.event(input.join_go)
    def _show_join_modal():
        join_error.set("")
        ui.modal_show(
            ui.modal(
                ui.input_text("join_name", "Name", placeholder="Your name"),
                ui.input_text("join_email", "Email", placeholder="you@email.com"),
                ui.output_ui("join_status"),
                title="Join Rock & Beach",
                easy_close=True,
                footer=ui.TagList(
                    ui.modal_button("Cancel"),
                    ui.input_action_button("join_submit", "Join & collect $200", class_="rb-cta-banner-btn"),
                ),
            )
        )

    @render.ui
    def join_status():
        msg = join_error.get()
        if not msg:
            return None
        return ui.HTML(f'<p style="font-size:12px;color:#993556;margin:6px 0 0">{msg}</p>')

    @reactive.effect
    @reactive.event(input.join_submit)
    async def _submit_join():
        name = (input.join_name() or "").strip()
        email = (input.join_email() or "").strip()
        if not name or "@" not in email:
            join_error.set("Please enter your name and a valid email.")
            return
        try:
            attendee_id = queries.add_attendee(name, email)
        except Exception as e:
            join_error.set(f"Couldn't save that — {e}")
            return
        current_attendee.set({"id": attendee_id, "name": name})
        ui.modal_remove()
        ui.notification_show(f"Welcome, {name}! You collected $200.", type="message", duration=4)
        await session.send_custom_message("rbShowPage", {"page": 2})

    # ── Page 3: Plan Shows — filter bar, Add-a-show, conflict detection ──
    conflict_msg = reactive.value("")
    schedule_tick = reactive.value(0)  # bumped after every add, so performance_list re-renders

    # Venue dropdown starts as just "All venues" and gets real choices
    # filled in here once loaded — same dynamic-population pattern as the
    # Chance page's country/type filters.
    @reactive.effect
    def _populate_venue_filter():
        try:
            venues_df = queries.get_venues()
        except Exception:
            return
        if len(venues_df) == 0:
            return
        names = sorted(venues_df["stage_name"].dropna().unique().tolist())
        choices = {"": "All venues"}
        choices.update({v: v for v in names})
        ui.update_select("pf_venue", choices=choices, session=session)

    @reactive.effect
    def _populate_time_filter():
        try:
            times_df = queries.get_performance_time_slots()
        except Exception:
            return
        if len(times_df) == 0:
            return
        choices = {"": "All times"}
        for t in times_df["start_time"]:
            choices[str(t)] = _fmt_time(t)
        ui.update_select("pf_time", choices=choices, session=session)

    @render.ui
    def performance_list():
        _ = schedule_tick.get()  # subscribe to post-add refreshes
        try:
            day_raw = input.pf_day()
            venue_raw = (input.pf_venue() or "").strip()
            time_raw = (input.pf_time() or "").strip()
            search = (input.pf_search() or "").strip()
            # No cap — every matching show is shown, grouped by date below,
            # instead of truncating at a small limit like the old list view.
            df, total = queries.get_performances(
                day=int(day_raw) if day_raw else None,
                tier=None,
                search=search or None,
                venue=venue_raw or None,
                time_slot=time_raw or None,
                limit=500,
            )
        except Exception as e:
            return ui.HTML(_db_error_box(f"Couldn't reach the database ({e})."))
        if len(df) == 0:
            return ui.HTML('<div class="dashedbox" style="height:60px;margin:0 20px 14px">No shows match those filters</div>')

        attendee = current_attendee.get()
        try:
            added_ids = queries.get_attendee_performance_ids(attendee["id"] if attendee else None)
        except Exception:
            added_ids = set()

        # Table-style layout: one row per festival day, date label in a
        # fixed-width left column. Inside that column's content, headliners
        # get their own dedicated row up top, then the remaining artists are
        # split into further rows by start time (2:00 PM shows together,
        # 5:00 PM shows together, etc.) instead of one continuous grid.
        rows = []
        for day_number in sorted(df["day_number"].unique()):
            day_group = df[df["day_number"] == day_number]
            day_number_int = int(day_number)
            label = DAY_POSTER_LABELS.get(day_number_int, f"DAY {day_number_int}")
            date_part, _, dow_part = label.rpartition(" ")
            color = DAY_POSTER_COLORS.get(day_number_int, "#1B2A4A")

            def _cards_grid(rows_df, capped=False):
                cards = "".join(
                    _plan_show_card(r, added=(r["performance_id"] in added_ids))
                    for r in rows_df.to_dict("records")
                )
                # capped=True (headliner row): fixed 170-200px card width so
                # 1-2 headliners don't stretch to fill the whole row width
                # the way the time-slot groups below are meant to. Left-
                # aligned (not centered) so it stays lined up with the date
                # column and the rows underneath instead of floating in the
                # middle of the row.
                extra = "grid-template-columns:repeat(auto-fit, minmax(195px, 230px));justify-content:start;" if capped else "grid-template-columns:repeat(auto-fit, minmax(145px, 180px));"
                return f'<div class="rb-lineup-grid" style="padding:0;margin:0 0 16px;{extra}">{cards}</div>'

            blocks = []
            headliners = day_group[day_group["tier"] == "Headliner"].sort_values("start_time")
            if len(headliners):
                hl_time_label = f"{_fmt_time(headliners['start_time'].min())} \u2013 {_fmt_time(headliners['end_time'].max())}"
                blocks.append(
                    f'<p style="font-size:15px;font-weight:700;color:#E4D8C4;margin:0 0 8px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">{hl_time_label}</p>'
                    + _cards_grid(headliners, capped=True)
                )

            others = day_group[day_group["tier"] != "Headliner"].sort_values("start_time")
            for start_time, slot_group in others.groupby("start_time", sort=True):
                time_label = f"{_fmt_time(start_time)} \u2013 {_fmt_time(slot_group['end_time'].max())}"
                blocks.append(
                    f'<p style="font-size:15px;font-weight:700;color:#E4D8C4;margin:0 0 8px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">{time_label}</p>'
                    + _cards_grid(slot_group)
                )

            rows.append(f'''
            <div style="display:flex;gap:16px;align-items:flex-start;padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.15)">
              <div style="flex:0 0 110px;padding-top:4px">
                <div style="background:{color};border-radius:10px;padding:8px 4px;text-align:center;box-shadow:0 3px 8px rgba(0,0,0,0.3)">
                  <p style="font-size:15px;line-height:1.2;font-weight:800;color:#fff;margin:0">{date_part}</p>
                  <p style="font-size:12px;line-height:1.2;font-weight:700;color:rgba(255,255,255,0.9);margin:0;letter-spacing:0.04em">{dow_part}</p>
                </div>
              </div>
              <div style="flex:1">{"".join(blocks)}</div>
            </div>''')

        return ui.HTML(f'<div style="background:transparent">{"".join(rows)}</div>')

    @render.ui
    def conflict_warning():
        msg = conflict_msg.get()
        if not msg:
            return None
        return ui.HTML(f'''<div class="rb-jail-card">
          <span style="font-size:20px">&#128274;</span>
          <span style="font-size:11px;color:#791F1F;font-weight:700">Go to jail &mdash; {msg}</span>
        </div>''')

    def _show_conflict_modal():
        """Popup shown when the DB's check_performance_conflict trigger
        blocks an Add — Monopoly 'Go to Jail' card, jail-bars artwork."""
        ui.modal_show(
            ui.modal(
                ui.HTML('''
                  <div style="text-align:center;padding:6px 4px">
                    <img src="jail_character_icon.png" style="width:130px;margin:0 auto 16px;display:block">
                    <p style="font-size:19px;font-weight:800;color:#791F1F;margin:0 0 10px">Sent to conflict jail</p>
                    <p style="font-size:13px;color:#555;margin:0 0 2px">This overlaps a show you already added that day.</p>
                    <p style="font-size:13px;color:#555;margin:0">Remove one to continue.</p>
                  </div>
                '''),
                easy_close=True,
                size="s",
                footer=ui.div(
                    ui.modal_button("Awaiting resolution", class_="rb-jail-dismiss-btn"),
                    style="text-align:center;width:100%",
                ),
            )
        )

    @reactive.effect
    @reactive.event(input.add_click)
    def _add_show():
        attendee = current_attendee.get()
        if not attendee:
            conflict_msg.set("join at Pass Go first so we know whose schedule to update.")
            return
        performance_id = input.add_click()
        try:
            queries.add_attendee_performance(attendee["id"], int(performance_id))
            conflict_msg.set("")
            ui.notification_show("Added to your schedule.", type="message", duration=3)
            # Fly the venue map straight to this show's stage, so Add
            # visibly connects to a pin instead of leaving the map generic.
            try:
                venue = queries.get_performance_venue(int(performance_id))
                if venue is not None and pd.notna(venue["latitude"]) and pd.notna(venue["longitude"]):
                    plan_shows_map.widget.center = (float(venue["latitude"]), float(venue["longitude"]))
                    plan_shows_map.widget.zoom = 15
            except Exception:
                pass  # map just stays put — not worth failing the Add over
        except Exception as e:
            msg = str(e).lower()
            if "duplicate key" in msg or "already exists" in msg:
                conflict_msg.set("")  # already on your schedule — the row already shows the stamp
            elif "conflict" in msg or "overlap" in msg:
                conflict_msg.set("")
                _show_conflict_modal()
            else:
                conflict_msg.set(f"couldn't add that show ({e}).")
        schedule_tick.set(schedule_tick.get() + 1)

    @reactive.effect
    @reactive.event(input.remove_click)
    def _remove_show():
        # Undo an Add — the "Landed" stamp on Plan Shows is clickable and
        # fires this, so attendees can change their mind before moving on.
        attendee = current_attendee.get()
        if not attendee:
            return
        performance_id = input.remove_click()
        try:
            queries.remove_attendee_performance(attendee["id"], int(performance_id))
            ui.notification_show("Removed from your schedule.", type="message", duration=3)
        except Exception as e:
            conflict_msg.set(f"couldn't remove that show ({e}).")
        schedule_tick.set(schedule_tick.get() + 1)

    # ── Real interactive trip map (Venue/Stay/Dining/Activity) ──────────
    # Shared cached dataset (reactive.calc caches within a session, so
    # having two map instances on two different pages doesn't double the
    # database round-trips) plus one ipyleaflet widget per page, each
    # redrawn whenever that page's category checkboxes change.
    @reactive.calc
    def map_locations():
        return queries.get_map_locations()

    @render_widget
    def plan_shows_map():
        return LeafletMap(center=AC_MAP_CENTER, zoom=13, basemap=basemaps.CartoDB.Positron)

    @reactive.effect
    def _update_plan_shows_map():
        try:
            df = map_locations()
        except Exception:
            return  # widget just stays empty; page still has performance_list's own error box for DB issues
        # Reading these .get()s (rather than passing them in as args) is
        # what makes this effect a dependent of both — so the map redraws
        # itself with the right gold stars right after every Add/Remove.
        _ = schedule_tick.get()
        attendee = current_attendee.get()
        added_venues = set()
        if attendee:
            try:
                sched = queries.get_attendee_schedule(attendee["id"])
                added_venues = set(sched["stage_name"].dropna().unique().tolist())
            except Exception:
                added_venues = set()
        # Only venues the attendee has actually added get a pin — the map
        # starts empty and pins appear as shows get added, instead of
        # always showing all 5 venues with the added ones merely
        # highlighted. Plain red music-note pins (MAP_CATEGORY_STYLE's
        # default Venue style) work fine here now that there's nothing
        # else on the map to distinguish them from.
        df_added = df[df["name"].isin(added_venues)] if len(added_venues) else df.iloc[0:0]
        # Clicking a pin sets the existing pf_venue dropdown to that venue
        # — reuses the filter that's already wired to performance_list,
        # rather than building a second, parallel filtering path.
        _redraw_map_markers(
            plan_shows_map.widget, df_added, ["Venue"],
            on_marker_click=lambda row: ui.update_select("pf_venue", selected=row["name"], session=session),
        )

        # Keep every added venue in view: one venue flies/zooms straight to
        # it, two-or-more fit the map's bounds to include all of them
        # instead of only ever centering on a single pin.
        if len(df_added) == 1:
            row = df_added.iloc[0]
            plan_shows_map.widget.center = (float(row["latitude"]), float(row["longitude"]))
            plan_shows_map.widget.zoom = 15
        elif len(df_added) > 1:
            lats = df_added["latitude"].astype(float)
            lons = df_added["longitude"].astype(float)
            plan_shows_map.widget.fit_bounds([[lats.min(), lons.min()], [lats.max(), lons.max()]])

    @render_widget
    def stay_trip_map():
        return LeafletMap(center=AC_MAP_CENTER, zoom=13, basemap=basemaps.CartoDB.Positron)

    def _on_stay_map_click(row):
        # One handler covering all categories shown on this map (unlike
        # Plan Shows' venue-only map above) — dispatches by row["category"]
        # to whichever action that category already supports elsewhere in
        # the app, so a map click does exactly what clicking "Add"/the
        # heart icon on that item's own card would do.
        category = row.get("category")
        if category == "Stay":
            selected_stay.set((row["name"], row.get("description")))
        elif category == "Dining":
            current = set(favorite_restaurant_ids.get())
            current.add(str(row["id_value"]))
            favorite_restaurant_ids.set(current)
        elif category == "Activity":
            current = set(favorite_activity_ids.get())
            current.add(str(row["id_value"]))
            favorite_activity_ids.set(current)
        # Venue markers on this map (if shown) are informational only —
        # no venue-selection action exists on the Select Stay page.

    @reactive.effect
    def _update_stay_trip_map():
        try:
            df = map_locations()
        except Exception:
            return
        _redraw_map_markers(stay_trip_map.widget, df, input.stay_map_categories(), on_marker_click=_on_stay_map_click)

    @render.ui
    def headliner_spotlight():
        try:
            row = queries.get_headliner_spotlight()
        except Exception as e:
            return ui.HTML(_db_error_box(f"Couldn't reach the database ({e})."))
        if row is None:
            return ui.HTML(_db_error_box("No headliner performance scheduled yet."))
        day_label = f"Day {int(row['day_number'])}" if pd.notna(row.get("day_number")) else ""
        html = f'''
        <div style="background:transparent;padding:18px 20px 22px">
          <p style="font-size:24px;font-weight:800;color:#FDF6E3;margin:0 0 4px;text-shadow:0 2px 8px rgba(0,0,0,0.5)">{row['artist_name']}</p>
          <p style="font-size:13px;color:#F4D9A0;margin:0;text-shadow:0 1px 4px rgba(0,0,0,0.5)">{day_label} &middot; {row['stage_name']} &middot; {_fmt_time(row['start_time'])}</p>
        </div>'''
        return ui.HTML(html)

    @render.ui
    def lineup_cards():
        try:
            df = queries.get_lineup_grid()
        except Exception as e:
            return ui.HTML(_db_error_box(f"Couldn't reach the database ({e})."))
        if len(df) == 0:
            return ui.HTML(_db_error_box("No artists found."))

        sections = []

        # Headliners: horizontal scroll strip instead of a wrapping grid —
        # keeps every headliner card at full size (no shrinking to fit
        # a row) regardless of how many there are; extra ones scroll into
        # view instead of wrapping to a second line or getting squeezed.
        headliners = df[df["tier"] == "Headliner"]
        if len(headliners):
            cards = "".join(_lineup_grid_card(r, large=True) for r in headliners.to_dict("records"))
            sections.append(f'<div class="rb-headliner-scroll" style="margin-top:20px">{cards}</div>')

        # Support + Rising: consolidated into a single shared grid (instead of
        # two separate stacked grids) so they flow together in the same lines.
        rest = df[df["tier"].isin(["Support", "Rising"])]
        if len(rest):
            cards = "".join(_lineup_grid_card(r, large=False) for r in rest.to_dict("records"))
            sections.append(f'<div class="rb-lineup-grid" style="margin-top:20px">{cards}</div>')

        html = f'<div style="background:transparent;padding-bottom:16px">{"".join(sections)}</div>'
        return ui.HTML(html)

    @render.ui
    def schedule_days():
        """My 3-Day Schedule: a board-path per day built from this
        attendee's added shows (checked tiles) interleaved with their
        free-time gaps (dashed tiles, tap to jump to Draw Chance). Refreshes
        whenever schedule_tick changes (i.e. right after an Add)."""
        _ = schedule_tick.get()
        attendee = current_attendee.get()
        if not attendee:
            return ui.HTML(_db_error_box("Join at Pass Go first, then add shows on Plan Shows to build your schedule."))
        try:
            sched = queries.get_attendee_schedule(attendee["id"])
            gaps = queries.get_attendee_downtime(attendee["id"])
        except Exception as e:
            return ui.HTML(_db_error_box(f"Couldn't reach the database ({e})."))
        if len(sched) == 0:
            return ui.HTML('<div class="dashedbox" style="height:80px;margin:20px 24px">No shows added yet &mdash; head to Plan Shows to add some.</div>')

        # earliest added show across the whole trip gets the bus token
        next_idx = sched.sort_values(["day_number", "start_time"]).index[0]

        gaps_by_day = {}
        if len(gaps):
            for day_number, group in gaps.groupby("day_number"):
                gaps_by_day[int(day_number)] = group.sort_values("gap_start")

        cols = []
        for day_number in sorted(sched["day_number"].unique()):
            day_number = int(day_number)
            day_shows = sched[sched["day_number"] == day_number]
            day_gaps = gaps_by_day.get(day_number, pd.DataFrame())

            events = [(r["start_time"], "show", r, idx == next_idx) for idx, r in day_shows.iterrows()]
            events += [(g["gap_start"], "gap", g, False) for _, g in day_gaps.iterrows()]
            events.sort(key=lambda e: e[0])

            tiles = ""
            for _, kind, row, is_next in events:
                if kind == "show":
                    bus = f'<span class="rb-tile-bus">{BUS_SVG} Next stop</span>' if is_next else ""
                    tiles += f'''<div class="rb-board-tile">
                      <div class="rb-tile-card show{" next" if is_next else ""}">
                        {bus}<p style="font-size:17px;font-weight:700;margin:0">{row['artist_name']}</p>
                        <p style="font-size:14px;color:#666;margin:4px 0 0">{_fmt_time(row['start_time'])}&ndash;{_fmt_time(row['end_time'])} &middot; {row['stage_name']}</p>
                      </div>
                    </div>'''
                else:
                    mins = int(row["gap_minutes"])
                    tiles += f'''<div class="rb-board-tile free" onclick="rbShow(5)">
                      <div class="rb-tile-card free">
                        <p style="font-size:15px;color:#888;margin:0">Free time &middot; {mins} min</p>
                        <p style="font-size:13px;color:#aaa;margin:4px 0 0">Tap to draw a chance card</p>
                      </div>
                    </div>'''
            cols.append(f'''<div class="rb-board-day">
              <p class="rb-board-title">Day {day_number}</p>
              <div class="rb-board-path">{tiles}</div>
            </div>''')

        return ui.HTML(f'<div style="background:transparent;padding:20px 24px;display:flex;gap:24px;flex-wrap:wrap">{"".join(cols)}</div>')

    @render.ui
    def stay_cards():
        selected_tier_keys = stay_tiers.get()
        # If every tier chip is selected (the default), that's "no filter" —
        # pass None instead of all values so an empty selection (all
        # deselected) can still be told apart from "show everything".
        if selected_tier_keys == {"1", "2", "3"}:
            price_tiers = None
        else:
            price_tiers = [v for key, _houses, values in PRICE_TIER_CHIPS if key in selected_tier_keys for v in values]

        if selected_tier_keys == set():
            df = pd.DataFrame()  # all tiers deselected -> show nothing, no need to query
        else:
            try:
                df = queries.get_top_stays(zone=stay_zone.get(), price_tiers=price_tiers)
            except Exception as e:
                return ui.HTML(_db_error_box(f"Couldn't reach the database ({e})."))
        if len(df) == 0:
            return ui.HTML('<div class="dashedbox" style="height:60px;margin:0 24px 14px">No stays match those filters</div>')
        picked = selected_stay.get()
        picked_name = picked[0] if picked else None
        cards = "".join(
            _stay_card(r, featured=(i == 0), is_selected=(r["property_name"] == picked_name))
            for i, r in enumerate(df.to_dict("records"))
        )
        return ui.HTML(f'<div style="background:transparent;padding:0 24px 20px"><p style="font-size:14px;color:#E4D8C4;margin:0 0 12px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">{len(df)} stays, live from the database</p>{cards}</div>')

    # Selected stay — session-only (no attendee_property table in the shared
    # schema yet), single-select: Adding a different stay just swaps it.
    selected_stay = reactive.value(None)  # (property_name, section_of_ac) or None

    @reactive.effect
    @reactive.event(input.add_stay_click)
    def _add_stay():
        picked = input.add_stay_click()
        selected_stay.set((picked.get("name"), picked.get("zone")))
        ui.notification_show("Stay selected.", type="message", duration=3)

    @reactive.effect
    @reactive.event(input.remove_stay_click)
    def _remove_stay():
        selected_stay.set(None)

    @render.ui
    def stay_summary():
        picked = selected_stay.get()
        if picked is None:
            body = '''<div style="background:#fff;display:flex;align-items:center;gap:14px;border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:20px">
              <div style="width:52px;height:52px;border-radius:8px;background:#F4C0D1"></div>
              <div style="flex:1"><p style="font-size:15px;font-weight:700;margin:0;color:#888">No stay selected yet</p><p style="font-size:13px;color:#888;margin:3px 0 0">Pick one on the Select Stay page</p></div>
              <span onclick="rbShow(5)" class="chip rb-cta" style="border:1px solid #ccc;cursor:pointer">Choose &#8599;</span>
            </div>'''
        else:
            name, zone = picked
            photo = _stay_photo_html(name)
            link_row = ""
            try:
                details = queries.get_stay_details(name)
                if details is not None and isinstance(details.get("google_maps_link"), str) and details["google_maps_link"].strip():
                    link_row = f'<a href="{html.escape(details["google_maps_link"], quote=True)}" target="_blank" rel="noopener" style="font-size:12px;color:#1B2A4A;font-weight:700;display:inline-block;margin-top:4px">View on map &#8599;</a>'
            except Exception:
                pass
            body = f'''<div style="background:#fff;display:flex;align-items:center;gap:14px;border:1.5px solid #1B2A4A;border-radius:10px;padding:14px;margin-bottom:20px">
              <div style="width:52px;height:52px;border-radius:8px;overflow:hidden;flex-shrink:0">{photo}</div>
              <div style="flex:1"><p style="font-size:15px;font-weight:700;margin:0">{html.escape(name)}</p><p style="font-size:13px;color:#888;margin:3px 0 0">{html.escape(zone or "")}</p>{link_row}</div>
              <span class="token" style="position:static">&#10003; Selected</span>
            </div>'''
        return ui.HTML(f'''
        <div style="background:transparent;padding:0 24px">
          <p style="font-size:13px;font-weight:700;color:#E4D8C4;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">STAY &middot; reserve separately</p>
          {body}
        </div>''')

    @render.ui
    def trip_summary_header():
        # Personalized with the name captured at registration (join_name),
        # which was already being carried through current_attendee for
        # every DB write on this page — it just was never actually shown
        # to the person before now.
        attendee = current_attendee.get()
        name = (attendee or {}).get("name") or ""
        greeting = f"Your trip so far, {html.escape(name)}" if name else "Your trip so far"
        return ui.HTML(f'''
        <div style="background:transparent;padding:20px 24px">
          <p style="font-size:22px;font-weight:700;color:#FDF6E3;margin:0 0 6px;text-shadow:0 2px 8px rgba(0,0,0,0.4)">{greeting}</p>
          <p style="font-size:14px;color:#E4D8C4;margin:0 0 14px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Last check before you head to the bank</p>
        </div>
        ''')

    @render.ui
    def trip_summary_shows():
        # Was hardcoded fake times (Fri 6/9pm etc.) for every attendee
        # regardless of what they'd actually added — now reads the same
        # v_attendee_schedule-backed query the Schedule page and the
        # progress icons already use, grouped by day.
        attendee = current_attendee.get()
        _ = schedule_tick.get()  # re-render after every Add/Remove, same pattern as elsewhere on this page
        rows_html = ""
        if attendee:
            try:
                df = queries.get_attendee_schedule(attendee["id"])
            except Exception:
                df = pd.DataFrame()
            if len(df):
                for day_number, group in df.groupby("day_number"):
                    times = ", ".join(_fmt_time(t) for t in group["start_time"])
                    rows_html += f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid #eee"><span>Day {day_number} &middot; {len(group)} show{"s" if len(group) != 1 else ""}</span><span style="color:#888">{times}</span></div>'
        if not rows_html:
            rows_html = '<div style="padding:6px 0;color:#888">No shows added yet &mdash; head to Plan Shows to pick some</div>'
        return ui.HTML(f'''
        <div style="background:transparent;padding:20px 24px">
          <p style="font-size:13px;font-weight:700;color:#E4D8C4;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">SHOWS &middot; included with ticket</p>
          <div style="background:#fff;border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:20px;font-size:14px">
            {rows_html}
          </div>
        </div>
        ''')

    @render.ui
    def trip_progress_icons():
        # The 4 Monopoly deed-card icons (each already has its own label
        # baked into the art) replace the old flat colored squares, with a
        # small checkmark/question-mark badge reflecting whether that piece
        # of the trip is actually locked in yet — reading real session
        # state instead of the old hardcoded ✓/? placeholders.
        attendee = current_attendee.get()
        shows_done = False
        if attendee:
            try:
                shows_done = len(queries.get_attendee_schedule(attendee["id"])) > 0
            except Exception:
                shows_done = False
        stay_done = selected_stay.get() is not None
        dining_done = saved_chance_pick.get() is not None
        activity_done = len(favorite_activity_ids.get()) > 0

        items = [
            ("summary_card_shows.jpg", shows_done),
            ("summary_card_stay.jpg", stay_done),
            ("summary_card_dining.jpg", dining_done),
            ("summary_card_activity.jpg", activity_done),
        ]
        tiles = ""
        for img, done in items:
            opacity = "1" if done else ".45"
            badge_color = "background:#2EC4B6;color:#04342C" if done else "background:#F0997B;color:#4A1B0C"
            badge_symbol = "&#10003;" if done else "?"
            tiles += f'''
            <div style="position:relative;opacity:{opacity}">
              <img src="{img}" style="width:240px;border-radius:20px;display:block;box-shadow:0 10px 26px rgba(0,0,0,0.35)">
              <span style="position:absolute;top:-14px;right:-14px;width:52px;height:52px;border-radius:50%;{badge_color};font-size:28px;font-weight:800;display:flex;align-items:center;justify-content:center;border:3.5px solid #FDF6E3">{badge_symbol}</span>
            </div>'''
        return ui.HTML(f'''
        <div style="background:#FDF6E3;border-radius:14px;margin:0 24px 20px;padding:30px 24px;display:flex;gap:36px;justify-content:center;flex-wrap:wrap">
          {tiles}
        </div>''')

    # ── Page 8: Bank — clickable ticket tier cards ────────────────────────
    # Session-only (no ticket/order table in the shared schema), single-
    # select: clicking a different deed card swaps it and the price flows
    # through to Trip summary's Total, the Pay button, and the bus pass.
    selected_ticket_tier = reactive.value("vip")

    @reactive.effect
    @reactive.event(input.select_tier_click)
    def _select_tier():
        key = input.select_tier_click()
        if key in TICKET_TIERS:
            selected_ticket_tier.set(key)

    @render.ui
    def bank_content():
        tier_key = selected_ticket_tier.get()
        _img, name, price = TICKET_TIERS[tier_key]

        cards = ""
        for key, (t_img, t_name, t_price) in TICKET_TIERS.items():
            is_sel = key == tier_key
            badge = '<div class="deed" style="top:-10px;right:16px;z-index:2">SELECTED</div>' if is_sel else ""
            shadow = "0 0 0 3px #FFD84D,0 6px 16px rgba(0,0,0,0.35)" if is_sel else "0 6px 16px rgba(0,0,0,0.3)"
            cards += f'''
            <div class="rb-cta" style="flex:1;min-width:170px;max-width:230px;position:relative" onclick="rbSelectTier('{key}')">
              {badge}
              <img src="{t_img}" style="width:100%;border-radius:14px;display:block;box-shadow:{shadow}">
            </div>'''

        return ui.HTML(f'''
        <div style="background:transparent;padding:20px 24px">
          <div style="display:flex;gap:18px;margin-bottom:22px;flex-wrap:wrap;justify-content:center">
            {cards}
          </div>
          <p style="font-size:16px;font-weight:700;color:#FDF6E3;margin:0 0 12px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Trip summary</p>
          <div style="background:#fff;border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:20px;font-size:14px">
            <div style="display:flex;justify-content:space-between;padding:6px 0"><span style="color:#888">2 shows added</span><span>Fri, Sat</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid #eee"><span style="color:#888">Stay</span><span>Property placeholder</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid #eee"><span style="color:#888">1 chance card saved</span><span>Dining pick</span></div>
            <div style="display:flex;justify-content:space-between;padding:10px 0 0;font-size:16px;font-weight:700;border-top:1px solid #ccc;margin-top:6px"><span>Total</span><span>${price}</span></div>
          </div>
          <p style="font-size:16px;font-weight:700;color:#FDF6E3;margin:0 0 12px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Billing</p>
          <div style="background:#fff;border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:10px;margin-bottom:20px">
            <input placeholder="Name on card" style="width:100%">
            <input placeholder="Card number" style="width:100%">
            <div style="display:flex;gap:10px"><input placeholder="MM / YY" style="flex:1"><input placeholder="CVC" style="flex:1"></div>
          </div>
          <div onclick="rbPayClick()" class="rb-cta" style="text-align:center;background:#FFD84D;border:1.5px solid #1B2A4A;color:#1B2A4A;font-size:16px;font-weight:700;padding:14px;border-radius:12px">Pay ${price} and get tickets</div>
        </div>
        <div style="background:transparent;padding:24px;text-align:center">
          <div style="background:#FDF6E3;border:1.5px solid #1B2A4A;border-radius:12px;padding:20px;max-width:340px;margin:0 auto">
            <p style="font-size:13px;font-weight:700;color:#1B2A4A;opacity:.6;margin:0 0 10px">MONOPOLY TOUR BUS PASS</p>
            <img src="bus_pass_qr.png" style="width:180px;height:180px;border-radius:8px;margin:0 auto 10px;display:block">
            <p style="font-size:14px;font-weight:700;color:#1B2A4A;margin:0">{html.escape(name)} &middot; Aug 21-23</p>
          </div>
        </div>''')

    @reactive.effect
    @reactive.event(input.pay_click)
    def _show_pay_modal():
        # In-app confirmation modal for the "Pay & get tickets" button —
        # styled like the rest of the site instead of a browser alert().
        ui.modal_show(
            ui.modal(
                ui.HTML('''
                  <div style="text-align:center;padding:10px 4px">
                    <div style="width:64px;height:64px;border-radius:50%;background:#2EC4B6;display:flex;align-items:center;justify-content:center;margin:0 auto 14px">
                      <span style="color:#04342C;font-size:32px;font-weight:800">&#10003;</span>
                    </div>
                    <p style="font-size:26px;font-weight:800;color:#1B2A4A;margin:0">Check the ticket</p>
                  </div>
                '''),
                easy_close=True,
                size="s",
                footer=ui.div(
                    ui.modal_button("OK", class_="rb-jail-dismiss-btn"),
                    style="text-align:center;width:100%",
                ),
            )
        )

    # Draw Chance re-roll counter. We deliberately DON'T use
    # @reactive.event(input.draw_again, ignore_none=False) on chance_pick
    # itself — in this environment that combination was silently preventing
    # the very first render (confirmed by testing a plain @render.ui vs. one
    # wrapped in @reactive.event side by side). Instead: a tiny effect bumps
    # this counter on each click, and chance_pick reads it via plain
    # automatic reactive tracking, which fires immediately on page load AND
    # re-fires on every bump.
    chance_draw_trigger = reactive.value(0)

    @reactive.effect
    @reactive.event(input.draw_again)
    def _bump_chance_draw():
        chance_draw_trigger.set(chance_draw_trigger.get() + 1)

    @render.ui
    def chance_pick():
        chance_draw_trigger.get()  # dependency only — re-run on each "Draw again" click

        # Whole function wrapped in one catch-all: absolutely anything that
        # goes wrong here (even something unanticipated) should surface as
        # visible red-ish text instead of silently rendering nothing, so a
        # blank Chance page is never mysterious again.
        try:
            attendee = current_attendee.get()
            attendee_id = attendee["id"] if attendee else None

            row = queries.get_chance_card(attendee_id)

            if attendee_id is None:
                return ui.div(
                    ui.HTML('<div class="dashedbox" style="height:70px;max-width:340px;margin:0 auto">Land on GO first &mdash; chance cards match coupons to your actual free time between shows.</div>'),
                    style="background:transparent;padding:24px;text-align:center",
                )
            if row is None:
                return ui.div(
                    ui.HTML('<div class="dashedbox" style="height:70px;max-width:340px;margin:0 auto">No chance card fits your schedule yet &mdash; add a show or two on Plan Shows to open up some free time.</div>'),
                    ui.input_action_button("draw_again", ui.TagList(ui.HTML(DICE_SVG_DARK), " Try again"), class_="rb-draw-btn"),
                    style="background:transparent;padding:24px;text-align:center",
                )

            card_html = _chance_card_html(row)
            return ui.div(
                ui.HTML(card_html),
                ui.input_action_button("draw_again", ui.TagList(ui.HTML(DICE_SVG_DARK), " Draw again"), class_="rb-draw-btn"),
                style="background:transparent;padding:24px;text-align:center",
            )
        except Exception as e:
            import traceback
            detail = traceback.format_exc().replace("\n", "<br>")
            return ui.div(
                ui.HTML(f'<div style="background:#FAECE7;padding:14px 20px;border-radius:10px;text-align:left;max-width:600px;margin:0 auto"><p style="font-size:12px;font-weight:700;color:#4A1B0C;margin:0 0 6px">Chance card error</p><p style="font-size:10px;color:#712B13;margin:0;font-family:monospace;white-space:pre-wrap">{detail}</p></div>'),
                style="background:transparent;padding:24px",
            )

    # Draw Chance's "Save" button (rbSaveChance in JS) forwards the card's
    # name/discount/desc/category here as a plain dict. This is session-only
    # state (an in-memory reactive.value, not written to the database) — it
    # resets if the server restarts, since there's no "saved_pick" table in
    # the shared schema yet. Good enough to make the Summary page reflect
    # what you actually drew instead of always showing placeholder text.
    saved_chance_pick = reactive.value(None)

    @reactive.effect
    @reactive.event(input.save_chance_click)
    def _save_chance_pick():
        saved_chance_pick.set(input.save_chance_click())

    @render.ui
    def chance_save_summary():
        pick = saved_chance_pick.get()
        if pick is None:
            body = '<div class="dashedbox" style="height:60px;margin-bottom:12px">No chance card saved yet &mdash; draw one on the Chance page and hit Save</div>'
        else:
            name = html.escape(pick.get("name") or "")
            discount = html.escape(pick.get("discount") or "")
            desc = html.escape(pick.get("desc") or "")
            category = html.escape(pick.get("category") or "")
            body = f'''
            <div style="background:#fff;display:flex;align-items:center;gap:14px;border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:12px">
              <div style="width:52px;height:52px;border-radius:8px;background:#F4D9A0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#4A1B0C;text-align:center;padding:2px">{discount}</div>
              <div style="flex:1"><p style="font-size:15px;font-weight:700;margin:0">{name}</p><p style="font-size:13px;color:#888;margin:3px 0 0">{desc}</p></div>
              <span class="chip" style="border:1px solid #ccc">{category}</span>
            </div>'''
        return ui.HTML(f'''
        <div style="background:transparent;padding:0 24px 4px">
          <p style="font-size:13px;font-weight:700;color:#E4D8C4;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">DINING &amp; ACTIVITIES &middot; reserve separately</p>
          {body}
        </div>''')

    # Browsable restaurant deal list on the Draw Chance page, below the
    # flip card. Favoriting (heart icon) is session-only state — same
    # tradeoff as saved_chance_pick above, no "favorites" table in the
    # shared schema yet — but it's enough to make the hearted restaurants
    # actually show up on the Summary page like you asked.
    favorite_restaurant_ids = reactive.value(set())
    # Price filter is multi-select (dollar-sign count, 1-4) via the same
    # house-icon chip pattern as the Stay page's price tier — defaults to
    # all four selected, i.e. no filter applied.
    restaurant_price_tiers = reactive.value({1, 2, 3, 4})

    @reactive.calc
    def all_restaurants_df():
        try:
            return queries.get_all_restaurants()
        except Exception:
            return pd.DataFrame()

    # Country/Type dropdowns start empty ("All ...") and get their real
    # choices filled in here once the live restaurant data loads — Shiny's
    # input_select needs static choices at UI-build time, so this is the
    # dynamic-population step for values that only exist in the DB.
    @reactive.effect
    def _populate_restaurant_filters():
        df = all_restaurants_df()
        if len(df) == 0:
            return
        countries = sorted(df["country"].dropna().unique().tolist())
        categories = sorted(df["food_category"].dropna().unique().tolist())
        country_choices = {"": "All countries"}
        country_choices.update({c: c for c in countries})
        category_choices = {"": "All types"}
        category_choices.update({c: c for c in categories})
        ui.update_select("rest_country", choices=country_choices, session=session)
        ui.update_select("rest_category", choices=category_choices, session=session)

    @reactive.effect
    @reactive.event(input.fav_restaurant_click)
    def _toggle_fav_restaurant():
        clicked = input.fav_restaurant_click()
        current = set(favorite_restaurant_ids.get())
        if clicked in current:
            current.discard(clicked)
        else:
            current.add(clicked)
        favorite_restaurant_ids.set(current)

    @reactive.effect
    @reactive.event(input.rest_price_click)
    def _toggle_rest_price():
        clicked = int(input.rest_price_click())
        current = set(restaurant_price_tiers.get())
        if clicked in current:
            current.discard(clicked)
        else:
            current.add(clicked)
        restaurant_price_tiers.set(current)

    @render.ui
    def restaurant_price_filter_chips():
        price_sel = restaurant_price_tiers.get()
        chips = ""
        for tier in (1, 2, 3, 4):
            active = tier in price_sel
            style = "background:#FFD84D;color:#1B2A4A;font-weight:700" if active else "background:#FDF6E3;border:1px solid #ccc;color:#666"
            house_icons = "".join('<span class="house" style="transform:scale(1.3)"></span>' for _ in range(tier))
            chips += f'<span class="chip rb-cta" style="{style};cursor:pointer;font-size:19px;padding:11px 18px" onclick="rbClickChip(\'rest_price_click\',\'{tier}\')">{house_icons}</span>'
        return ui.HTML(f'''
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:0 0 14px">
          <span style="font-size:18px;color:#FDF6E3;text-shadow:0 1px 4px rgba(0,0,0,0.4)">Price:</span>
          {chips}
        </div>''')

    @render.ui
    def restaurant_list():
        # Filter-driven instead of grouped-by-country — with ~100
        # restaurants, splitting into country sections still meant a lot of
        # scrolling. Country / Type dropdowns + price chips narrow the list
        # down directly instead.
        df = all_restaurants_df()
        if len(df) == 0:
            return ui.HTML('<div class="dashedbox" style="height:60px">Couldn\'t load restaurants right now</div>')
        favs = favorite_restaurant_ids.get()
        df = df.copy()
        df["country"] = df["country"].fillna("Other")
        df["food_category"] = df["food_category"].fillna("Other")

        country_sel = (input.rest_country() or "").strip()
        category_sel = (input.rest_category() or "").strip()
        price_sel = restaurant_price_tiers.get()

        if country_sel:
            df = df[df["country"] == country_sel]
        if category_sel:
            df = df[df["food_category"] == category_sel]
        if price_sel and len(price_sel) < 4:
            def _dollar_count(pr):
                return max(1, min((pr or "$").count("$"), 4))
            df = df[df["price_range"].apply(_dollar_count).isin(price_sel)]

        if len(df) == 0:
            return ui.HTML('<div class="dashedbox" style="height:60px">No restaurants match those filters</div>')

        cards = "".join(
            _restaurant_card_html(r, is_fav=(r["restaurant_id"] in favs))
            for r in df.to_dict("records")
        )
        plural = "" if len(df) == 1 else "s"
        count_label = f'<p style="font-size:16px;font-weight:600;color:#C9BFA6;margin:0 0 10px">{len(df)} restaurant{plural}</p>'
        return ui.HTML(f'{count_label}<div class="rb-restaurant-grid">{cards}</div>')

    @render.ui
    def favorite_restaurants_summary():
        df = all_restaurants_df()
        favs = favorite_restaurant_ids.get()
        if len(df) == 0 or not favs:
            body = '<div class="dashedbox" style="height:60px;margin-bottom:12px">No favorite restaurants yet &mdash; tap the heart on any deal on the Chance page</div>'
        else:
            picked = df[df["restaurant_id"].isin(favs)]
            cards = "".join(_restaurant_card_html(r, is_fav=True) for r in picked.to_dict("records"))
            body = f'<div class="rb-restaurant-grid">{cards}</div>'
        return ui.HTML(f'''
        <div style="background:transparent;padding:0 24px 4px">
          <p style="font-size:13px;font-weight:700;color:#E4D8C4;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">FAVORITE RESTAURANTS</p>
          {body}
        </div>''')

    # Browsable activity deal list on the Draw Chance page, below the
    # restaurant deals — same pattern as restaurants above (live DB data,
    # session-only favoriting, one filter), just sourced from
    # activity + activity_category instead of restaurant.
    favorite_activity_ids = reactive.value(set())

    @reactive.calc
    def all_activities_df():
        try:
            return queries.get_all_activities()
        except Exception:
            return pd.DataFrame()

    @reactive.effect
    def _populate_activity_filters():
        df = all_activities_df()
        if len(df) == 0:
            return
        categories = sorted(df["category_name"].dropna().unique().tolist())
        category_choices = {"": "All categories"}
        category_choices.update({c: c for c in categories})
        ui.update_select("activity_category_filter", choices=category_choices, session=session)

    @reactive.effect
    @reactive.event(input.fav_activity_click)
    def _toggle_fav_activity():
        clicked = input.fav_activity_click()
        current = set(favorite_activity_ids.get())
        if clicked in current:
            current.discard(clicked)
        else:
            current.add(clicked)
        favorite_activity_ids.set(current)

    @render.ui
    def activity_list():
        df = all_activities_df()
        if len(df) == 0:
            return ui.HTML('<div class="dashedbox" style="height:60px">Couldn\'t load activities right now</div>')
        favs = favorite_activity_ids.get()
        df = df.copy()
        df["category_name"] = df["category_name"].fillna("Other")

        category_sel = (input.activity_category_filter() or "").strip()
        if category_sel:
            df = df[df["category_name"] == category_sel]

        if len(df) == 0:
            return ui.HTML('<div class="dashedbox" style="height:60px">No activities match that filter</div>')

        cards = "".join(
            # activity_id is a numeric DB column (unlike restaurant_id,
            # which is a text code like "R047"), but the heart's onclick
            # always sends it to Shiny as a string — compare as strings on
            # both sides so numeric vs. string types don't silently fail
            # to match and make the heart look unclickable.
            _activity_card_html(r, is_fav=(str(r["activity_id"]) in favs))
            for r in df.to_dict("records")
        )
        noun = "activity" if len(df) == 1 else "activities"
        count_label = f'<p style="font-size:16px;font-weight:600;color:#C9BFA6;margin:0 0 10px">{len(df)} {noun}</p>'
        return ui.HTML(f'{count_label}<div class="rb-restaurant-grid">{cards}</div>')

    @render.ui
    def favorite_activities_summary():
        df = all_activities_df()
        favs = favorite_activity_ids.get()
        if len(df) == 0 or not favs:
            body = '<div class="dashedbox" style="height:60px;margin-bottom:12px">No favorite activities yet &mdash; tap the heart on any deal on the Chance page</div>'
        else:
            picked = df[df["activity_id"].astype(str).isin(favs)]
            cards = "".join(_activity_card_html(r, is_fav=True) for r in picked.to_dict("records"))
            body = f'<div class="rb-restaurant-grid">{cards}</div>'
        return ui.HTML(f'''
        <div style="background:transparent;padding:0 24px 4px">
          <p style="font-size:13px;font-weight:700;color:#E4D8C4;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">FAVORITE ACTIVITIES</p>
          {body}
        </div>''')

    def _compute_trip_budget():
        """Shared by trip_budget_summary (display) and the email share
        button (mailto body) so the two can never drift out of sync.
        Returns (line_items, total) where line_items is a list of
        (label, amount_or_None) tuples — amount is None for the stay row
        when nothing's selected yet, so callers can render "TBD" instead
        of a fake $0.

        Ticket: flat price for whichever tier is currently picked on the
        Bank page. Stay: average of price_min_usd/price_max_usd for the
        one selected property, multiplied by 3 nights (the festival is
        Aug 21-23, fixed length — no separate length-of-stay input in
        this app). Dining/Activities: sum of est_cost_per_person_usd /
        price_usd across everything hearted as a favorite. The one thing
        NOT counted: a saved Draw Chance pick — it's a stumbled-into deal
        with no reliable base price to sum, not a planned expense.
        """
        line_items = []

        tier_key = selected_ticket_tier.get()
        _img, tier_name, ticket_price = TICKET_TIERS.get(tier_key, (None, "Ticket", 0))
        line_items.append((f"Festival ticket ({tier_name})", ticket_price))

        stay_amount = None
        picked_stay = selected_stay.get()
        if picked_stay:
            try:
                details = queries.get_stay_details(picked_stay[0])
                if details is not None and pd.notna(details.get("price_min_usd")) and pd.notna(details.get("price_max_usd")):
                    stay_amount = round((float(details["price_min_usd"]) + float(details["price_max_usd"])) / 2) * 3
            except Exception:
                stay_amount = None
        line_items.append(("Stay (3 nights, avg. rate)", stay_amount))

        dining_total = 0
        rest_df = all_restaurants_df()
        favs_r = favorite_restaurant_ids.get()
        if len(rest_df) and favs_r:
            picked = rest_df[rest_df["restaurant_id"].isin(favs_r)]
            dining_total = round(picked["est_cost_per_person_usd"].fillna(0).sum())
        line_items.append((f"Dining ({len(favs_r)} favorited)", dining_total))

        activity_total = 0
        act_df = all_activities_df()
        favs_a = favorite_activity_ids.get()
        if len(act_df) and favs_a:
            picked = act_df[act_df["activity_id"].astype(str).isin(favs_a)]
            activity_total = round(picked["price_usd"].fillna(0).sum())
        line_items.append((f"Activities ({len(favs_a)} favorited)", activity_total))

        total = ticket_price + (stay_amount or 0) + dining_total + activity_total
        return line_items, total

    @render.ui
    def trip_budget_summary():
        line_items, total = _compute_trip_budget()
        rows_html = ""
        for label, amount in line_items:
            amount_html = f"${amount:,.0f}" if amount is not None else '<span style="color:#888">TBD</span>'
            rows_html += f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid #eee"><span>{html.escape(label)}</span><span>{amount_html}</span></div>'
        return ui.HTML(f'''
        <div style="background:transparent;padding:0 24px 4px">
          <p style="font-size:13px;font-weight:700;color:#E4D8C4;margin:0 0 10px;text-shadow:0 1px 4px rgba(0,0,0,0.4)">ESTIMATED BUDGET</p>
          <div style="background:#fff;border:1px solid #ddd;border-radius:10px;padding:14px 16px;margin-bottom:12px;font-size:14px">
            {rows_html}
            <div style="display:flex;justify-content:space-between;padding:10px 0 0;margin-top:4px;border-top:1.5px solid #1B2A4A;font-size:17px;font-weight:800"><span>Total</span><span>${total:,.0f}</span></div>
          </div>
          <p style="font-size:11px;color:#E4D8C4;opacity:.75;margin:0 0 20px">Stay is estimated for the full 3-night festival (Aug 21-23) at the property's average nightly rate. Dining/activity prices shown are estimates, not final menu or admission prices.</p>
        </div>
        ''')

    @render.ui
    def trip_summary_footer():
        # "Continue to bank" CTA shows the real ticket price for whichever
        # tier is currently selected (was hardcoded $399 regardless of
        # tier).
        attendee = current_attendee.get()
        n_shows = 0
        if attendee:
            try:
                n_shows = len(queries.get_attendee_schedule(attendee["id"]))
            except Exception:
                n_shows = 0
        n_stay = 1 if selected_stay.get() else 0
        n_picks = len(favorite_restaurant_ids.get()) + len(favorite_activity_ids.get())

        tier_key = selected_ticket_tier.get()
        _img, tier_name, ticket_price = TICKET_TIERS.get(tier_key, (None, "Ticket", 0))

        return ui.HTML(f'''
        <div style="background:#F4D9A0;border-radius:10px;margin:0 24px 20px;padding:18px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
          <span style="font-size:14px;color:#1B2A4A">{n_shows} shows &middot; {n_stay} stay &middot; {n_picks} saved picks</span>
          <span onclick="rbShow(8)" class="rb-cta" style="background:#1B2A4A;color:#FDF6E3;font-size:14px;font-weight:700;padding:12px 20px;border-radius:14px">Continue to bank &middot; ${ticket_price:,.0f}</span>
        </div>
        ''')


app = App(app_ui, server, static_assets=Path(__file__).parent / "www")