"""Low-level helpers for the Flashscore lineup parser.

Pure functions and domain constants extracted from ``parser.py`` keep
the main module focused on the parsing pipeline.
"""

import re
import logging
from typing import Any

from bs4 import BeautifulSoup, Tag

from entities.match import Sport
from entities.player import Position, SquadStatus
from services.config import AWAY_SIDE, CDN_BASE, HISTORY_DEPTH, HOME_SIDE
from services.countries import COUNTRY_TO_ISO


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

# dlie2 group labels, compared case-insensitively via ``.upper()``.
XI_GROUP_NAMES: set[str] = {
    "STARTING LINEUPS",
    "LINE 1", "LINE 2", "LINE 3", "LINE 4",
}
SUB_GROUP_NAMES: set[str] = {
    "SUBSTITUTES",
}

# Flashscore-specific markers.
PREFERRED_TEAM_LOGO_VARIANT = 15


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def dig(data: Any, *keys: str, default: Any = None) -> Any:
    """Safely walk nested dictionaries. Return ``default`` if any key is missing."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        else:
            return default
    return data


def parse_int_cell(row: Tag, selector: str, default: int | None = None) -> int | None:
    """Parse an integer from the selected cell. Return ``default`` on failure."""
    cell = row.select_one(selector)
    if not cell:
        return default
    try:
        return int(cell.get_text(strip=True).replace("'", ""))
    except (ValueError, TypeError):
        return default


def normalize_team_name(name: str) -> str:
    """Normalize a team name for fuzzy fallback matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", name)).strip().lower()


# ---------------------------------------------------------------------------
# Flashscore-specific helpers
# ---------------------------------------------------------------------------

def unwrap_event(api_response: dict[str, Any]) -> dict[str, Any]:
    """Extract the GraphQL envelope ``{data: {findEventById: {...}}}``."""
    return (
        dig(api_response, "data", "findEventById", default={})
        or api_response.get("findEventById", {})
        or {}
    )


def team_logo_url(images: list[dict[str, Any]]) -> str | None:
    """
    Return the best available team logo from a list of ``Image`` objects.

    Prefers the variant with ``variantType: 15`` (used on the Flashscore website),
    and falls back to the first available variant if not found.
    """
    # Prefer ``variantType`` 15.
    for img in images:
        if img.get("variantType") == PREFERRED_TEAM_LOGO_VARIANT:
            path = img.get("path")
            if path:
                return f"{CDN_BASE}image/data/{path}"
    # Fallback: use the first image with a valid path.
    for img in images:
        path = img.get("path")
        if path:
            return f"{CDN_BASE}image/data/{path}"
    return None


def first_valid_participant(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first participant object with a stable identifier."""
    for item in payload.get("participants", []):
        part = item.get("participant", {})
        if isinstance(part, dict) and part.get("id"):
            return part
    return None


def find_current_start(event_participants: list[dict[str, Any]], event_id: str) -> tuple[int | None, bool]:
    """Find the viewed match in any ``lastEvents`` list."""
    for ep in event_participants:
        part = first_valid_participant(ep) or {}
        for le in part.get("lastEvents", []):
            if le.get("id") == event_id:
                return le.get("startTime"), True
    return None, False


def previous_event_ids(
    last_events: list[dict[str, Any]],
    current_start: int | None,
    found_in_last_events: bool,
) -> list[str]:
    """Return previous match IDs, newest first.

    The number of IDs returned is capped by ``HISTORY_DEPTH`` (see ``services.config``).
    All downstream consumers, including the ``Player`` dataclass and the UI table, use the same constant.
    """
    if not last_events:
        return []
    if not found_in_last_events:
        return [le.get("id") for le in last_events[:HISTORY_DEPTH] if le.get("id")]
    if current_start is None:
        return []

    result: list[str] = []
    for le in last_events:
        st = le.get("startTime")
        if isinstance(st, (int, float)) and st < current_start:
            eid = le.get("id")
            if eid:
                result.append(eid)
            if len(result) >= HISTORY_DEPTH:
                break
    return result


def resolve_lineup_target(
    event_participants: list[dict[str, Any]],
    team_id: str | None,
    side_hint: str | None,
    fallback_name: str | None,
) -> dict[str, Any] | None:
    """Select the lineup block using stable identifiers first."""
    target: dict[str, Any] | None = None
    side_hint_upper = side_hint.upper() if side_hint else ""
    fallback_name_norm = normalize_team_name(fallback_name) if fallback_name else ""

    for ep in event_participants:
        ep_side = dig(ep, "type", "side", default="").upper()
        if team_id is not None:
            for item in ep.get("participants", []):
                part = item.get("participant", {})
                if isinstance(part, dict) and str(part.get("id", "")) == str(team_id):
                    return ep
        if side_hint_upper in (HOME_SIDE, AWAY_SIDE) and ep_side == side_hint_upper:
            target = ep
            break
        if fallback_name and ep.get("name") == fallback_name:
            target = ep
            break
        if fallback_name and normalize_team_name(ep.get("name", "")) == fallback_name_norm:
            target = ep
            break

    if target is None:
        if side_hint_upper == HOME_SIDE and event_participants:
            logger.warning(
                "Falling back to the first event participant while resolving lineup "
                "(team_id=%r, side_hint=%r, fallback_name=%r)",
                team_id, side_hint, fallback_name,
            )
            return event_participants[0]
        if side_hint_upper == AWAY_SIDE and len(event_participants) > 1:
            logger.warning(
                "Falling back to the second event participant while resolving lineup "
                "(team_id=%r, side_hint=%r, fallback_name=%r)",
                team_id, side_hint, fallback_name,
            )
            return event_participants[1]
    return target


def build_status_map(groups: list[dict[str, Any]]) -> dict[str, SquadStatus]:
    """Convert lineup groups into a mapping from participant IDs to statuses."""
    status_map: dict[str, SquadStatus] = {}
    for g in groups:
        gname = g.get("name", "")
        gname_upper = gname.upper()
        if gname_upper in XI_GROUP_NAMES:
            status = SquadStatus.IN_XI
        elif gname_upper in SUB_GROUP_NAMES:
            status = SquadStatus.ON_BENCH
        else:
            continue
        for pid in g.get("playerIds", []):
            status_map[str(pid)] = status
    return status_map


def select_squad_table(soup: BeautifulSoup, sport: Sport) -> Tag | None:
    """Select the best available squad table for the given sport."""
    if sport == Sport.HOCKEY:
        return (
            soup.select_one('[id$="-table"]:not(#overall-all-table)')
            or soup.select_one("#overall-all-table")
            or soup.select_one('[id$="-table"]')
        )
    return soup.select_one("#overall-all-table") or soup.select_one('[id$="-table"]')


def position_from_title(title: str) -> Position:
    """Map a squad section title to a ``Position`` value."""
    t = title.strip().lower()
    if "goalkeeper" in t:
        return Position.GOALKEEPER
    if "defender" in t:
        return Position.DEFENDER
    if "midfield" in t:
        return Position.MIDFIELDER
    if "forward" in t or "attacker" in t or "striker" in t:
        return Position.FORWARD
    return Position.UNKNOWN


def country_to_flag_url(country_name: str) -> str | None:
    """
    Convert a country name, such as ``"Belarus"``, to a Flashscore CDN flag image URL using a built-in lookup table.

    Returns ``None`` if the country cannot be resolved.
    """
    code = COUNTRY_TO_ISO.get(country_name)
    if code is None:
        return None
    return f"{CDN_BASE}image/country_flags/{code}.png"
