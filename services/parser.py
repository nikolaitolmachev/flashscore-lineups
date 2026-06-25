"""
Flashscore lineup parser based on direct API calls.

It combines Flashscore's GraphQL backend (``2.ds.lsapp.eu``) with squad HTML pages to build match data.
"""

import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from entities.lineup_result import LineupResult
from entities.match import Match, Sport
from entities.odds import Odds
from entities.player import IHGoalkeeper, Player, Position, SquadStatus
from entities.team import Team
from services.config import (
    AWAY_SIDE,
    BET_SCOPE_FULL_TIME,
    BET_TYPE_HOME_DRAW_AWAY,
    API_BASE,
    BASE_URL,
    HASH_BOOKMAKERS,
    HASH_LINEUPS,
    HASH_MATCH_INFO,
    HASH_ODDS,
    HOME_SIDE,
    ODDS_API_BASE,
    PROJECT_ID,
    REQUEST_TIMEOUT,
    SQUAD_URL_FMT,
    USER_AGENT,
)
from services.exceptions import (
    InvalidURLError,
    LineupNotReadyError,
    ParserError,
    SportNotSupportedError,
)
from services.parser_helpers import (
    build_status_map,
    country_to_flag_url,
    dig,
    find_current_start,
    first_valid_participant,
    parse_int_cell,
    position_from_title,
    previous_event_ids,
    resolve_lineup_target,
    select_squad_table,
    team_logo_url,
    unwrap_event,
)


logger = logging.getLogger(__name__)


# Regex: extract eventId from ``?mid=XXXXXXXX``.
_RE_MID = re.compile(r"[?&]mid=([A-Za-z0-9]+)")

# Regex: sport from URL path ``/match/{sport}/``.
_RE_SPORT = re.compile(r"/match/(football|hockey)/")

# Regex: extract participant ID from a Flashscore player URL.
_RE_PLAYER_ID = re.compile(r"/player/[^/]+/([A-Za-z0-9]+)")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class LineupParser:
    """
    Parses Flashscore match data via direct API calls.

    The pipeline combines team metadata, current lineups, historical
    lineups, squad pages, and bookmaker odds into a single result object.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        """
        Create a parser.

        The optional ``session`` can be shared across instances to reuse HTTP connections.
        """
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._session.headers.setdefault("Accept", "application/json")
        self._event_id: str = ""
        self._bookmakers: list[dict[str, int | str]] = []
        self._geo: dict[str, str] | None = None

    def _request_json(
        self,
        url: str,
        *,
        context: str,
        timeout: int | float,
        log_errors: bool = True,
    ) -> dict[str, Any]:
        """Fetch JSON from ``url`` and optionally log request details."""
        logger.debug("GET %s", url)
        try:
            resp = self._session.get(url, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException:
            if log_errors:
                logger.exception("Failed to fetch %s: %s", context, url)
            raise
        try:
            return resp.json()
        except ValueError:
            if log_errors:
                logger.exception("Invalid JSON response for %s: %s", context, url)
            raise

    @staticmethod
    def _build_match(url: str, sport: Sport, home_info: dict[str, Any], away_info: dict[str, Any]) -> Match:
        """Build match metadata."""
        return Match(
            url=url,
            sport=sport,
            tournament=None,  # not available in dsof
            home_team_id=home_info["id"],
            away_team_id=away_info["id"],
            home_team_name=home_info["name"],
            away_team_name=away_info["name"],
        )

    @staticmethod
    def _build_team(info: dict[str, Any], players: list[Player]) -> Team:
        """Build a team from parsed squad data."""
        return Team(
            participant_id=info["id"],
            name=info["name"],
            url=info["url"],
            logo_url=info.get("logo_url"),
            players=players,
            uses_minutes=any((p.minutes_played or 0) > 0 for p in players),
        )

    def _load_status_history(
        self,
        team_id: str,
        team_name: str,
        last_event_ids: list[str],
    ) -> list[dict[str, SquadStatus]]:
        """Fetch status maps for the team's previous matches."""
        return [
            self._fetch_last_status(prev_id, team_id, team_name)
            for prev_id in last_event_ids
        ]

    @staticmethod
    def _history_failures(history: list[dict[str, SquadStatus]]) -> int:
        """Count previous matches whose lineup data could not be loaded."""
        return sum(1 for status_map in history if not status_map)

    @staticmethod
    def _log_history_load(
        event_id: str,
        home_last: list[dict[str, SquadStatus]],
        away_last: list[dict[str, SquadStatus]],
    ) -> None:
        """Log whether previous-match history was loaded fully or partially."""
        home_history_failed = LineupParser._history_failures(home_last)
        away_history_failed = LineupParser._history_failures(away_last)
        if home_last or away_last:
            if home_history_failed or away_history_failed:
                logger.warning(
                    "Partial history loaded for match %s (home_failed=%d/%d, away_failed=%d/%d)",
                    event_id, home_history_failed, len(home_last), away_history_failed, len(away_last),
                )
            else:
                logger.debug(
                    "History loaded for match %s (home=%d, away=%d)",
                    event_id, len(home_last), len(away_last),
                )

    def _bookmakers_url(self) -> str:
        """Build the bookmaker-list endpoint for the current match."""
        geo_params = self._geo_params()
        return (
            f"{ODDS_API_BASE}"
            f"?_hash={HASH_BOOKMAKERS}"
            f"&eventId={self._event_id}"
            f"&projectId={PROJECT_ID}"
            f"&geoIpCode={geo_params['code']}"
            f"&geoIpSubdivisionCode={geo_params['sub']}"
        )

    def _odds_url(self, bookmaker_id: int) -> str:
        """Build the 1X2 odds endpoint for one bookmaker."""
        return (
            f"{ODDS_API_BASE}"
            f"?_hash={HASH_ODDS}"
            f"&eventId={self._event_id}"
            f"&bookmakerId={bookmaker_id}"
            f"&betType={BET_TYPE_HOME_DRAW_AWAY}"
            f"&betScope={BET_SCOPE_FULL_TIME}"
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self, url: str) -> LineupResult:
        """
        Parse a Flashscore match URL and return complete lineup data.

        Args:
            url: The match page URL, for example
                ``https://www.flashscore.com/match/football/.../?mid=nmlFkIYP``.

        Returns:
            A ``LineupResult`` containing the match metadata, both teams,
            and ``odds`` from the available bookmakers.

        Raises:
            InvalidURLError: The ``?mid=`` parameter is missing or the sport is unknown.
            SportNotSupportedError: The sport is neither football nor hockey.
            LineupNotReadyError: Lineups have not been published yet for this match.
            requests.RequestException: A network-level or HTTP failure occurred.
        """
        event_id = self._extract_event_id(url)
        sport = self._extract_sport(url)

        # 1. dsof: teams, logos, and last-event IDs.
        dsof_raw = self._api_get(HASH_MATCH_INFO, event_id)
        dsof = unwrap_event(dsof_raw)

        home_info, away_info = self._parse_teams_info(dsof, event_id)

        # 2. dlie2: current lineups -> status map.
        dlie2_raw = self._api_get(HASH_LINEUPS, event_id)
        dlie2 = unwrap_event(dlie2_raw)

        _, home_status = self._parse_lineup(
            dlie2,
            team_id=home_info["id"],
            side_hint=HOME_SIDE,
            fallback_name=home_info["name"],
        )
        _, away_status = self._parse_lineup(
            dlie2,
            team_id=away_info["id"],
            side_hint=AWAY_SIDE,
            fallback_name=away_info["name"],
        )

        if not home_status and not away_status:
            raise LineupNotReadyError(
                f"No lineup data found for match '{event_id}'. Lineups may not be available yet."
            )

        # Previous match lineups -> last status maps.
        home_last = self._load_status_history(
            home_info["id"], home_info["name"], home_info["last_event_ids"]
        )
        away_last = self._load_status_history(
            away_info["id"], away_info["name"], away_info["last_event_ids"]
        )
        self._log_history_load(event_id, home_last, away_last)

        # Squad HTML: all players, stats, and positions.
        home_players = self._fetch_squad(home_info["slug"], home_info["id"], sport)
        away_players = self._fetch_squad(away_info["slug"], away_info["id"], sport)

        # Apply status maps.
        self._apply_statuses(home_players, home_status, home_last)
        self._apply_statuses(away_players, away_status, away_last)

        # 1X2 odds.
        self._event_id = event_id
        odds = self._fetch_all_odds()

        match = self._build_match(url, sport, home_info, away_info)
        home_team = self._build_team(home_info, home_players)
        away_team = self._build_team(away_info, away_players)

        logger.info(
            "Parsed %s match: %s vs %s (%d + %d players, %d bookmakers)",
            sport.value, home_team.name, away_team.name, len(home_players), len(away_players), len(odds),
        )
        return LineupResult(
            match=match, home_team=home_team, away_team=away_team, odds=odds,
        )

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_event_id(url: str) -> str:
        """Extract ``eventId`` from the ``mid`` query parameter."""
        m = _RE_MID.search(url)
        if not m:
            raise InvalidURLError(f"Missing 'mid' query parameter in URL: {url!r}")
        return m.group(1)

    @staticmethod
    def _extract_sport(url: str) -> Sport:
        """Extract the ``Sport`` enum from the URL path ``/match/{sport}/``."""
        m = _RE_SPORT.search(url)
        if not m:
            raise SportNotSupportedError(
                f"Cannot determine sport from URL: {url!r}. Expected /match/football/ or /match/hockey/."
            )
        sport_name = m.group(1)
        if sport_name == "football":
            return Sport.FOOTBALL
        if sport_name == "hockey":
            return Sport.HOCKEY
        raise SportNotSupportedError(f"Unknown sport: {sport_name!r}")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _api_get(self, hash_name: str, event_id: str) -> dict[str, Any]:
        """Query the GraphQL API endpoint and return parsed JSON."""
        url = (
            f"{API_BASE}"
            f"?_hash={hash_name}"
            f"&eventId={event_id}"
            f"&projectId={PROJECT_ID}"
        )
        return self._request_json(url, context="API", timeout=REQUEST_TIMEOUT)

    def _get_html(self, url: str) -> BeautifulSoup:
        """Query an HTML page and return a BeautifulSoup object."""
        logger.debug("GET HTML %s", url)
        try:
            resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("HTML request failed: %s", url)
            raise
        return BeautifulSoup(resp.text, "lxml")

    # ------------------------------------------------------------------
    # dsof: teams, logos, last-event IDs
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_teams_info(dsof: dict[str, Any], event_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Return the home and away team metadata from the ``dsof`` response.

        Each dictionary includes ``id``, ``name``, ``slug``, ``url``, ``logo_url``, and ``last_event_ids``.
        """
        event_participants: list[dict[str, Any]] = dsof.get("eventParticipants", [])
        if len(event_participants) < 2:
            logger.warning(
                "Unexpected dsof structure: expected at least 2 eventParticipants (event_id=%s, got=%d)",
                event_id, len(event_participants),
            )
            raise ParserError("Could not find both teams in dsof response.")

        # Find the current match start time in either team's ``lastEvents``.
        current_start, found_in_last_events = find_current_start(event_participants, event_id)

        home: dict[str, Any] | None = None
        away: dict[str, Any] | None = None

        for ep in event_participants:
            side = dig(ep, "type", "side", default="").upper()
            name = ep.get("name", "")
            part = first_valid_participant(ep)
            if part is None:
                logger.warning(
                    "dsof eventParticipant has no valid participant (event_id=%s, team_name=%r, side=%r)",
                    event_id, name, side,
                )
                continue

            team_id = part.get("id", "")
            slug = part.get("url", "")
            logo_url = team_logo_url(part.get("images", []))

            info = {
                "id": team_id,
                "name": name,
                "slug": slug,
                "url": f"{BASE_URL}/team/{slug}/{team_id}/",
                "logo_url": logo_url,
                "last_event_ids": previous_event_ids(
                    part.get("lastEvents", []),
                    current_start,
                    found_in_last_events,
                ),
            }

            if side == HOME_SIDE or (home is None and team_id and not away):
                home = info
            elif side == AWAY_SIDE or (away is None and team_id):
                away = info

        if not home or not away:
            logger.error(
                "Could not resolve HOME/AWAY teams from the dsof response (event_id=%s, participants=%d)",
                event_id, len(event_participants),
            )
            raise ParserError("Could not find HOME or AWAY teams in the dsof response.")

        return home, away

    # ------------------------------------------------------------------
    # dlie2: lineup parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_lineup(
        dlie2: dict[str, Any],
        team_id: str | None = None,
        side_hint: str | None = None,
        fallback_name: str | None = None,
    ) -> tuple[str | None, dict[str, SquadStatus]]:
        """
        Return formation and player statuses from the ``dlie2`` feed.

        Target selection follows a stable-to-unstable fallback chain:
        ``participant.id`` -> ``type.side`` -> team name -> normalized team name.

        Returns:
            A tuple containing ``(formation, {participant_id: SquadStatus})``.
        """
        event_participants: list[dict[str, Any]] = dlie2.get("eventParticipants", [])
        if not event_participants:
            logger.warning(
                "dlie2 response has no eventParticipants (team_id=%r, side_hint=%r, fallback_name=%r)",
                team_id, side_hint, fallback_name,
            )
            return None, {}

        target = resolve_lineup_target(event_participants, team_id, side_hint, fallback_name)
        if target is None:
            logger.warning(
                "Team not found in dlie2 (team_id=%r, side_hint=%r, fallback_name=%r, teams=%d)",
                team_id, side_hint, fallback_name, len(event_participants),
            )
            return None, {}

        lineup: dict[str, Any] = target.get("lineup", {})
        if not lineup:
            logger.warning(
                "dlie2 team payload has no lineup (team_id=%r, side_hint=%r, fallback_name=%r, team_name=%r)",
                team_id, side_hint, fallback_name, target.get("name"),
            )
            return None, {}
        formation = dig(lineup, "formation", "name", default=None)

        # Build ``participant_id`` -> ``SquadStatus`` from lineup groups.
        groups: list[dict[str, Any]] = lineup.get("groups", [])
        if not groups:
            logger.warning(
                "dlie2 lineup has no groups (team_id=%r, side_hint=%r, fallback_name=%r, team_name=%r)",
                team_id, side_hint, fallback_name, target.get("name"),
            )
        status_map = build_status_map(groups)

        if groups and not status_map:
            logger.warning(
                "dlie2 lineup groups did not match known group names "
                "(team_id=%r, side_hint=%r, fallback_name=%r, team_name=%r)",
                team_id, side_hint, fallback_name, target.get("name"),
            )

        if not status_map:
            logger.warning(
                "dlie2 lineup groups produced empty status map "
                "(team_id=%r, side_hint=%r, fallback_name=%r, team_name=%r)",
                team_id, side_hint, fallback_name, target.get("name"),
            )

        return formation, status_map

    # ------------------------------------------------------------------
    # Previous match status
    # ------------------------------------------------------------------

    def _fetch_last_status(self, last_event_id: str, team_id: str, team_name: str) -> dict[str, SquadStatus]:
        """
        Fetch the status map for a previous match.

        Returns a mapping from ``participant_id`` to ``SquadStatus``.
        """
        try:
            dlie2_raw = self._api_get(HASH_LINEUPS, last_event_id)
            dlie2 = unwrap_event(dlie2_raw)
            _, status_map = self._parse_lineup(dlie2, team_id=team_id, fallback_name=team_name)
            return status_map
        except requests.RequestException:
            logger.warning(
                "Failed to fetch last match lineup due to HTTP error (last_event_id=%s, team_id=%s, team_name=%r)",
                last_event_id, team_id, team_name, exc_info=True,
            )
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "Failed to parse last match lineup payload (last_event_id=%s, team_id=%s, team_name=%r)",
                last_event_id, team_id, team_name, exc_info=True,
            )
        except Exception:  # noqa
            logger.exception(
                "Unexpected error while fetching last match lineup (last_event_id=%s, team_id=%s, team_name=%r)",
                last_event_id, team_id, team_name,
            )
        return {}

    # ------------------------------------------------------------------
    # 1X2 odds
    # ------------------------------------------------------------------

    def _fetch_all_odds(self) -> list[Odds]:
        """
        Fetch 1X2 odds for all available bookmakers.

        Returns a list of ``Odds`` objects, or an empty list if no odds are available.
        """
        self._bookmakers = self._fetch_bookmakers()
        odds: list[Odds] = []
        for bm in self._bookmakers:
            o = self._fetch_odds_for_bookmaker(bm["id"])
            if o is not None:
                odds.append(o)
        return odds

    @staticmethod
    def _detect_geo() -> dict[str, str]:
        """Detect the country code and subdivision via ip-api.com."""
        try:
            resp = requests.get(
                "https://ip-api.com/json",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                code = data.get("countryCode", "")
                sub = data.get("region", "")
                return {"code": code, "sub": f"{code}{sub}"}
        except requests.RequestException:
            logger.warning("Geo detection failed due to HTTP error", exc_info=True)
        except (ValueError, KeyError, TypeError):
            logger.warning("Geo detection failed while parsing response", exc_info=True)
        except Exception:  # noqa
            logger.exception("Unexpected error during geo detection")
        return {"code": "", "sub": ""}

    def _geo_params(self) -> dict[str, str]:
        """Return cached geo-location parameters."""
        if self._geo is None:
            self._geo = self._detect_geo()
        return self._geo

    def _fetch_bookmakers(self) -> list[dict[str, int | str]]:
        """
        Return the bookmakers available for this match.

        Each entry is ``{"id": int, "name": str}``.
        """
        try:
            url = self._bookmakers_url()
            data = self._request_json(
                url,
                context="bookmaker list",
                timeout=REQUEST_TIMEOUT,
                log_errors=False,
            )
            bookmakers = (
                data.get("data", {})
                .get("getPrematchOddsBettingTypeMenu", {})
                .get("settings", {})
                .get("bookmakers", [])
            )
            return [
                {"id": bm["bookmaker"]["id"], "name": bm["bookmaker"]["name"]}
                for bm in bookmakers
            ]
        except requests.RequestException:
            logger.warning(
                "Failed to fetch bookmaker list due to HTTP error (event_id=%s)",
                self._event_id, exc_info=True,
            )
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "Failed to parse bookmaker list payload (event_id=%s)",
                self._event_id, exc_info=True,
            )
        except Exception:  # noqa
            logger.exception(
                "Unexpected error while fetching bookmaker list (event_id=%s)",
                self._event_id,
            )
        return []

    def _fetch_odds_for_bookmaker(self, bookmaker_id: int) -> Odds | None:
        """
        Fetch 1X2 odds for a single bookmaker.

        Args:
            bookmaker_id: Flashscore internal bookmaker identifier.

        Returns:
            ``Odds`` object or ``None`` if the data is not available.
        """

        def _change(odds_item: dict) -> str | None:
            ch = odds_item.get("change")
            return ch.get("type") if isinstance(ch, dict) else None

        try:
            url = self._odds_url(bookmaker_id)
            data = self._request_json(
                url,
                context="odds",
                timeout=REQUEST_TIMEOUT,
                log_errors=False,
            )
            odds_data = data.get("data", {}).get("findPrematchOddsForBookmaker", {})
            if not odds_data:
                return None
            # Resolve the bookmaker name from the cached bookmaker list.
            name = next(
                (bm["name"] for bm in self._bookmakers if bm["id"] == bookmaker_id),
                str(bookmaker_id),
            )

            return Odds(
                bookmaker=name,
                home=odds_data["home"]["value"],
                draw=odds_data["draw"]["value"],
                away=odds_data["away"]["value"],
                home_change=_change(odds_data["home"]),
                draw_change=_change(odds_data["draw"]),
                away_change=_change(odds_data["away"]),
            )
        except requests.RequestException:
            logger.warning(
                "Failed to fetch odds due to HTTP error (event_id=%s, bookmaker_id=%s)",
                self._event_id, bookmaker_id, exc_info=True,
            )
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "Failed to parse odds payload (event_id=%s, bookmaker_id=%s)",
                self._event_id, bookmaker_id, exc_info=True,
            )
        except Exception:  # noqa
            logger.exception(
                "Unexpected error while fetching odds (event_id=%s, bookmaker_id=%s)",
                self._event_id, bookmaker_id,
            )
        return None

    # ------------------------------------------------------------------
    # Squad HTML: build the full player list with stats, positions, and flags.
    # ------------------------------------------------------------------

    def _fetch_squad(self, slug: str, team_id: str, sport: Sport) -> list[Player]:
        """
        Parse the squad HTML page and return the full player list.

        The result includes player stats, positions from section headers,
        and flag URLs.
        """
        url = SQUAD_URL_FMT.format(slug=slug, team_id=team_id)
        players: list[Player] = []

        try:
            soup = self._get_html(url)
        except requests.RequestException:
            logger.warning(
                "Failed to fetch squad page due to HTTP error for URL: %s", url, exc_info=True)
            raise
        except Exception:  # noqa
            logger.exception("Unexpected error while fetching squad page: %s", url)
            raise

        table = select_squad_table(soup, sport)
        if table is None:
            logger.error("No squad table found for URL: %s", url)
            raise ParserError(f"No squad table found for URL: {url}")

        for group in table.select(".lineupTable"):
            title_el = group.select_one(".lineupTable__title")
            current_position = position_from_title(title_el.get_text(strip=True)) if title_el else Position.UNKNOWN

            for row in group.select(".lineupTable__row"):
                player = self._parse_squad_row(row, sport, current_position)
                if player:
                    players.append(player)

        if not players:
            logger.error("Squad table parsed to zero players for URL: %s", url)
            raise ParserError(f"Squad table parsed to zero players for URL: {url}")
        logger.debug("Parsed %d squad players from URL: %s", len(players), url)

        return players

    @staticmethod
    def _parse_squad_row(row: Tag, sport: Sport, position: Position) -> Player | None:
        """
        Parse a single ``lineupTable__row`` into a ``Player`` or ``IHGoalkeeper``.

        Return ``None`` if the participant ID cannot be extracted.
        """
        # Extract the participant ID and profile URL from the player link.
        a_tag = row.select_one("a[href*='/player/']")
        if not a_tag:
            logger.debug("Squad row without /player/ link - skipping")
            return None
        href = str(a_tag.get("href", ""))
        pm = _RE_PLAYER_ID.search(href)
        if not pm:
            logger.warning("Could not extract player ID from %r", href)
            return None
        participant_id = pm.group(1)
        player_url = f"{BASE_URL}{href}"

        # Player name.
        name = a_tag.get_text(strip=True)

        # Shirt number.
        shirt_number = parse_int_cell(row, '[class*="lineupTable__cell--jersey"]')

        # Flag or emblem.
        # Club squads use CSS to display the country flag instead of an ``<img>`` tag.
        # National teams use an explicit ``<img>`` tag for the emblem.
        flag_url: str | None = None
        flag_cell = row.select_one('[class*="lineupTable__cell--flag"]')
        if flag_cell:
            img = flag_cell.select_one("img")
            if img:
                flag_url = str(img.get("src", "") or "").strip() or None
            else:
                country_name = (flag_cell.get("title") or "").strip()
                if country_name:
                    flag_url = country_to_flag_url(country_name)

        # Age.
        age = parse_int_cell(row, '[class*="lineupTable__cell--age"]')

        # Matches played.
        matches_played = parse_int_cell(
            row,
            '[class*="lineupTable__cell--matchesPlayed"], '
            '[class*="lineupTable__cell--appearances"]'
        ) or 0

        # Sport-specific stats.
        return (
            LineupParser._parse_squad_hockey(
                row, participant_id, name, player_url, shirt_number, flag_url, age, matches_played, position,
            )
            if sport == Sport.HOCKEY
            else LineupParser._parse_squad_football(
                row, participant_id, name, player_url, shirt_number, flag_url, age, matches_played, position,
            )
        )

    @staticmethod
    def _parse_squad_football(
        row: Tag,
        participant_id: str,
        name: str,
        player_url: str,
        shirt_number: int | None,
        flag_url: str | None,
        age: int | None,
        matches_played: int,
        position: Position,
    ) -> Player:
        """Create a ``Player`` from a football squad row."""
        goals_scored = parse_int_cell(
            row,
            '[class*="lineupTable__cell--goal"], '
            '[class*="lineupTable__cell--goals"]',
            default=0,
        ) or 0

        minutes_played = parse_int_cell(
            row,
            '[class*="lineupTable__cell--minutesPlayed"], '
            '[class*="lineupTable__cell--minutes"]',
        )

        return Player(
            participant_id=participant_id,
            name=name,
            url=player_url,
            shirt_number=shirt_number,
            flag_url=flag_url,
            age=age,
            position=position,
            matches_played=matches_played,
            minutes_played=minutes_played,
            goals_scored=goals_scored,
        )

    @staticmethod
    def _parse_squad_hockey(
        row: Tag,
        participant_id: str,
        name: str,
        player_url: str,
        shirt_number: int | None,
        flag_url: str | None,
        age: int | None,
        matches_played: int,
        position: Position,
    ) -> Player:
        """
        Create a ``Player`` or ``IHGoalkeeper`` from a hockey squad row.

        Goalies are detected by save percentage, goals-against average, or shutout columns in the row.
        Dashes (``"-"``) representing missing stats are treated as zero.
        """
        def _parse_goalie_stat(selector: str, cast: type[float] | type[int] = float) -> float:
            cell = row.select_one(selector)
            if not cell:
                return -1.0  # Sentinel: column not present.
            text = cell.get_text(strip=True)
            if text in ("-", "", "—"):
                return 0.0
            try:
                return cast(text)
            except (ValueError, TypeError):
                return -1.0

        sv = _parse_goalie_stat(
            '[class*="lineupTable__cell--savesPercentage"], '
            '[class*="lineupTable__cell--saves"], '
            '[class*="lineupTable__cell--svPercent"]'
        )
        gaa = _parse_goalie_stat(
            '[class*="lineupTable__cell--goalsAgainstAverage"], '
            '[class*="lineupTable__cell--gaa"]'
        )
        so = _parse_goalie_stat(
            '[class*="lineupTable__cell--shutouts"], '
            '[class*="lineupTable__cell--so"]',
            cast=int,
        )

        # Goalie columns in the row indicate an ``IHGoalkeeper``.
        is_goalie = sv >= 0 or gaa >= 0 or so >= 0

        if is_goalie:
            return IHGoalkeeper(
                participant_id=participant_id,
                name=name,
                url=player_url,
                shirt_number=shirt_number,
                flag_url=flag_url,
                age=age,
                matches_played=matches_played,
                sv=sv if sv >= 0 else 0.0,
                gaa=gaa if gaa >= 0 else 0.0,
                so=int(so) if so >= 0 else 0,
            )

        # Hockey skaters store goals in a separate column.
        goals_scored = parse_int_cell(
            row,
            '[class*="lineupTable__cell--goal"], '
            '[class*="lineupTable__cell--goals"]',
            default=0,
        ) or 0

        return Player(
            participant_id=participant_id,
            name=name,
            url=player_url,
            shirt_number=shirt_number,
            flag_url=flag_url,
            age=age,
            position=position,
            matches_played=matches_played,
            goals_scored=goals_scored,
        )

    # ------------------------------------------------------------------
    # Apply status maps to the player list.
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_statuses(
        players: list[Player],
        current_status: dict[str, SquadStatus],
        last_statuses: list[dict[str, SquadStatus]],
    ) -> None:
        """
        Mutate ``players`` in place.

        Set ``squad_status`` from *current_status* and populate the history list
        from *last_statuses*, newest first. Missing data is marked as
        ``ABSENT`` when the previous match was loaded successfully and ``UNKNOWN`` when it was not.
        """

        for p in players:
            history_size = len(p.last_match_statuses)
            p.squad_status = current_status.get(p.participant_id, SquadStatus.ABSENT)
            p.last_match_statuses = [
                ls.get(p.participant_id, SquadStatus.ABSENT if ls else SquadStatus.UNKNOWN)
                for ls in last_statuses
            ] + [SquadStatus.UNKNOWN] * max(0, history_size - len(last_statuses))
