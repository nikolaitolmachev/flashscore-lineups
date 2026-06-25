"""Unit tests for ``services.parser_helpers``: pure functions with no I/O."""

import pytest
from bs4 import BeautifulSoup, Tag

from entities.match import Sport
from entities.player import Position, SquadStatus
from services.parser_helpers import (
    build_status_map,
    country_to_flag_url,
    dig,
    find_current_start,
    first_valid_participant,
    normalize_team_name,
    parse_int_cell,
    position_from_title,
    previous_event_ids,
    resolve_lineup_target,
    select_squad_table,
    team_logo_url,
    unwrap_event,
)


# ---------------------------------------------------------------------------
# dig
# ---------------------------------------------------------------------------

class TestDig:
    def test_shallow_key(self):
        """A single key should be returned directly."""
        assert dig({"a": 1}, "a") == 1

    def test_nested_keys(self):
        """Nested keys should be resolved step by step."""
        assert dig({"a": {"b": {"c": 42}}}, "a", "b", "c") == 42

    def test_missing_key_returns_default(self):
        """Missing keys should return the default value."""
        assert dig({"a": 1}, "b") is None
        assert dig({"a": 1}, "b", default=0) == 0

    def test_non_dict_intermediate(self):
        """Traversal should stop if an intermediate value is not a dict."""
        assert dig({"a": 1}, "a", "b") is None

    def test_empty_dict(self):
        """An empty input should return the default value."""
        assert dig({}, "a") is None


# ---------------------------------------------------------------------------
# normalize_team_name
# ---------------------------------------------------------------------------

class TestNormalizeTeamName:
    def test_removes_special_chars(self):
        """Special characters should be stripped from team names."""
        assert normalize_team_name("Team (U23)") == "team u23"

    def test_collapses_whitespace(self):
        """Repeated whitespace should collapse to a single space."""
        assert normalize_team_name("FC   Barcelona  ") == "fc barcelona"

    def test_lowercases(self):
        """Normalization should be case-insensitive."""
        assert normalize_team_name("ARSENAL") == "arsenal"

    def test_identical_after_normalization(self):
        """Equivalent names should normalize to the same value."""
        a = normalize_team_name("Manchester United")
        b = normalize_team_name("Manchester  United!")
        assert a == b


# ---------------------------------------------------------------------------
# parse_int_cell
# ---------------------------------------------------------------------------

class TestParseIntCell:
    @staticmethod
    def _make_row(html: str) -> Tag:
        soup = BeautifulSoup(f"<table>{html}</table>", "lxml")
        return soup.select_one("tr")  # type: ignore[return-value]

    def test_parses_integer(self):
        """Numeric cells should be parsed as integers."""
        row = self._make_row('<tr><td class="age">25</td></tr>')
        assert parse_int_cell(row, ".age") == 25

    def test_cell_not_found_returns_default(self):
        """Missing cells should return the default value."""
        row = self._make_row("<tr><td>25</td></tr>")
        assert parse_int_cell(row, ".age") is None
        assert parse_int_cell(row, ".age", default=0) == 0

    def test_non_numeric_returns_default(self):
        """Non-numeric cell values should fall back to the default."""
        row = self._make_row('<tr><td class="age">N/A</td></tr>')
        assert parse_int_cell(row, ".age") is None

    def test_minutes_strips_quote(self):
        """Trailing minute quotes should be ignored."""
        row = self._make_row('<tr><td class="min">90\'</td></tr>')
        assert parse_int_cell(row, ".min") == 90


# ---------------------------------------------------------------------------
# unwrap_event
# ---------------------------------------------------------------------------

class TestUnwrapEvent:
    def test_standard_envelope(self):
        """The GraphQL envelope should unwrap to the event payload."""
        data = {"data": {"findEventById": {"key": "value"}}}
        assert unwrap_event(data) == {"key": "value"}

    def test_top_level_fallback(self):
        """Top-level ``findEventById`` should be accepted as a fallback."""
        data = {"findEventById": {"key": "value"}}
        assert unwrap_event(data) == {"key": "value"}

    def test_empty_response(self):
        """An empty response should normalize to an empty dict."""
        assert unwrap_event({}) == {}


# ---------------------------------------------------------------------------
# team_logo_url
# ---------------------------------------------------------------------------

class TestTeamLogoUrl:
    def test_prefers_variant_15(self):
        """Variant 15 should be preferred when available."""
        images = [
            {"variantType": 10, "path": "wrong.png"},
            {"variantType": 15, "path": "correct.png"},
        ]
        url = team_logo_url(images)
        assert url.endswith("correct.png")

    def test_fallback_no_variant_15(self):
        """The first valid image should be used as a fallback."""
        images = [{"variantType": 10, "path": "fallback.png"}]
        url = team_logo_url(images)
        assert url.endswith("fallback.png")

    def test_empty_images(self):
        """No images should yield ``None``."""
        assert team_logo_url([]) is None

    def test_images_without_path(self):
        """Images without a usable path should be ignored."""
        assert team_logo_url([{"variantType": 15}]) is None


# ---------------------------------------------------------------------------
# first_valid_participant
# ---------------------------------------------------------------------------

class TestFirstValidParticipant:
    def test_returns_first_with_id(self):
        """The first participant with an ID should be returned."""
        payload = {
            "participants": [
                {"participant": {"id": "abc", "name": "Test"}},
            ]
        }
        assert first_valid_participant(payload) == {"id": "abc", "name": "Test"}

    def test_skips_empty_participant(self):
        """Empty participant objects should be skipped."""
        payload = {
            "participants": [
                {"participant": {}},
                {"participant": {"id": "xyz"}},
            ]
        }
        assert first_valid_participant(payload) == {"id": "xyz"}

    def test_no_participants(self):
        """Missing participants should return ``None``."""
        assert first_valid_participant({"participants": []}) is None


# ---------------------------------------------------------------------------
# find_current_start
# ---------------------------------------------------------------------------

class TestFindCurrentStart:
    def test_finds_match_in_last_events(self):
        """The current match should be found inside ``lastEvents``."""
        eps = [
            {"participants": [{"participant": {
                "id": "team1",
                "lastEvents": [
                    {"id": "ev1", "startTime": 100},
                    {"id": "target", "startTime": 999},
                ]
            }}]}
        ]
        start, found = find_current_start(eps, "target")
        assert found is True
        assert start == 999

    def test_not_found(self):
        """Missing match IDs should report ``(None, False)``."""
        eps = [
            {"participants": [{"participant": {
                "id": "team1",
                "lastEvents": [{"id": "ev1", "startTime": 100}]
            }}]}
        ]
        start, found = find_current_start(eps, "missing")
        assert found is False
        assert start is None


# ---------------------------------------------------------------------------
# previous_event_ids
# ---------------------------------------------------------------------------

class TestPreviousEventIds:
    def test_empty_last_events(self):
        """No historical events should return an empty list."""
        assert previous_event_ids([], None, False) == []

    def test_not_found_returns_all_up_to_depth(self):
        """If the match is not found, keep only the newest events up to the depth limit."""
        events = [{"id": f"e{i}"} for i in range(10)]
        ids = previous_event_ids(events, None, False)
        from services.config import HISTORY_DEPTH
        assert len(ids) == HISTORY_DEPTH
        assert ids == [f"e{i}" for i in range(HISTORY_DEPTH)]

    def test_found_filters_by_start_time(self):
        """Only events older than the current match should be kept."""
        events = [
            {"id": "old1", "startTime": 100},
            {"id": "old2", "startTime": 200},
            {"id": "current", "startTime": 300},  # Current match.
            {"id": "future", "startTime": 400},
        ]
        ids = previous_event_ids(events, 300, True)
        assert ids == ["old1", "old2"]

    def test_found_no_current_start(self):
        """If the current match start is unknown, return no history."""
        events = [{"id": "e1", "startTime": 100}]
        assert previous_event_ids(events, None, True) == []


# ---------------------------------------------------------------------------
# resolve_lineup_target
# ---------------------------------------------------------------------------

class TestResolveLineupTarget:
    @pytest.fixture
    def participants(self) -> list[dict]:
        return [
            {
                "type": {"side": "HOME"},
                "name": "Real Madrid",
                "participants": [{"participant": {"id": "RM123"}}],
            },
            {
                "type": {"side": "AWAY"},
                "name": "FC Barcelona",
                "participants": [{"participant": {"id": "FCB456"}}],
            },
        ]

    def test_by_team_id(self, participants):
        """A stable team ID should take priority."""
        result = resolve_lineup_target(participants, "FCB456", None, None)
        assert result is not None
        assert result["name"] == "FC Barcelona"

    def test_by_side_hint(self, participants):
        """A side hint should resolve the team when the ID is unavailable."""
        result = resolve_lineup_target(participants, None, "HOME", None)
        assert result is not None
        assert result["name"] == "Real Madrid"

    def test_by_exact_name(self, participants):
        """An exact team name should work as a fallback."""
        result = resolve_lineup_target(participants, None, None, "FC Barcelona")
        assert result is not None
        assert result["name"] == "FC Barcelona"

    def test_by_normalized_name(self, participants):
        """Normalized names should match despite spacing or punctuation differences."""
        result = resolve_lineup_target(participants, None, None, "fc  barcelona !")
        assert result is not None
        assert result["name"] == "FC Barcelona"

    def test_fallback_home(self, participants):
        """The home fallback should return the first participant."""
        result = resolve_lineup_target(participants, None, "HOME", None)
        assert result["name"] == "Real Madrid"

    def test_fallback_away(self, participants):
        """The away fallback should return the second participant."""
        result = resolve_lineup_target(participants, None, "AWAY", None)
        assert result["name"] == "FC Barcelona"

    def test_none_when_no_match(self, participants):
        """Even without a direct match, the function should fall back by side hint."""
        participants[0]["type"]["side"] = "UNKNOWN"
        participants[1]["type"]["side"] = "UNKNOWN"
        result = resolve_lineup_target(participants, None, "HOME", None)
        assert result is not None  # fallback to index 0
        result = resolve_lineup_target(participants, None, "AWAY", "non-existent")
        assert result is not None  # fallback to index 1


# ---------------------------------------------------------------------------
# build_status_map
# ---------------------------------------------------------------------------

class TestBuildStatusMap:
    def test_starters_and_bench(self):
        """Starting lineups and substitutes should map to the correct statuses."""
        groups = [
            {"name": "Starting Lineups", "playerIds": ["p1", "p2"]},
            {"name": "Substitutes", "playerIds": ["p3"]},
        ]
        sm = build_status_map(groups)
        assert sm == {
            "p1": SquadStatus.IN_XI,
            "p2": SquadStatus.IN_XI,
            "p3": SquadStatus.ON_BENCH,
        }

    def test_hockey_lines(self):
        """Hockey lines should count as starters, and substitutes should stay on the bench."""
        groups = [
            {"name": "Line 1", "playerIds": [1, 2, 3]},
            {"name": "Line 2", "playerIds": [4, 5, 6]},
            {"name": "Substitutes", "playerIds": [7]},
        ]
        sm = build_status_map(groups)
        assert sm["1"] == SquadStatus.IN_XI
        assert sm["4"] == SquadStatus.IN_XI
        assert sm["7"] == SquadStatus.ON_BENCH
        assert len(sm) == 7

    def test_unknown_group_skipped(self):
        """Unknown group names should be ignored."""
        groups = [{"name": "Unknown Group", "playerIds": ["x"]}]
        assert build_status_map(groups) == {}

    def test_empty_groups(self):
        """An empty group list should produce an empty map."""
        assert build_status_map([]) == {}


# ---------------------------------------------------------------------------
# select_squad_table
# ---------------------------------------------------------------------------

class TestSelectSquadTable:
    def test_football_selects_overall(self):
        """Football should prefer the overall squad table."""
        soup = BeautifulSoup(
            '<div id="overall-all-table"><div class="lineupTable"></div></div>'
            '<div id="league-table"><div class="lineupTable"></div></div>',
            "lxml",
        )
        table = select_squad_table(soup, Sport.FOOTBALL)
        assert table is not None
        assert table.get("id") == "overall-all-table"

    def test_hockey_prefers_league_table(self):
        """Hockey should prefer the sport-specific table when available."""
        soup = BeautifulSoup(
            '<div id="overall-all-table"><div class="lineupTable"></div></div>'
            '<div id="league-table"><div class="lineupTable"></div></div>',
            "lxml",
        )
        table = select_squad_table(soup, Sport.HOCKEY)
        assert table is not None
        assert table.get("id") == "league-table"

    def test_hockey_fallback_to_overall(self):
        """Hockey should fall back to the overall table if needed."""
        soup = BeautifulSoup(
            '<div id="overall-all-table"><div class="lineupTable"></div></div>',
            "lxml",
        )
        table = select_squad_table(soup, Sport.HOCKEY)
        assert table is not None
        assert table.get("id") == "overall-all-table"

    def test_no_table_found(self):
        """If no acceptable table exists, the helper should return ``None``."""
        soup = BeautifulSoup("<div></div>", "lxml")
        assert select_squad_table(soup, Sport.FOOTBALL) is None


# ---------------------------------------------------------------------------
# position_from_title
# ---------------------------------------------------------------------------

class TestPositionFromTitle:
    def test_goalkeeper(self):
        """Goalkeeper titles should map to ``Position.GOALKEEPER``."""
        assert position_from_title("Goalkeepers") == Position.GOALKEEPER

    def test_defender(self):
        """Defender titles should map to ``Position.DEFENDER``."""
        assert position_from_title("Defenders") == Position.DEFENDER

    def test_midfielder(self):
        """Midfielder titles should map to ``Position.MIDFIELDER``."""
        assert position_from_title("Midfielders") == Position.MIDFIELDER

    def test_forward_variants(self):
        """Forward-like titles should all map to ``Position.FORWARD``."""
        assert position_from_title("Forwards") == Position.FORWARD
        assert position_from_title("Attackers") == Position.FORWARD
        assert position_from_title("Strikers") == Position.FORWARD

    def test_unknown(self):
        """Unknown titles should fall back to ``Position.UNKNOWN``."""
        assert position_from_title("Managers") == Position.UNKNOWN


# ---------------------------------------------------------------------------
# country_to_flag_url
# ---------------------------------------------------------------------------

class TestCountryToFlagUrl:
    def test_known_country(self):
        """Known countries should resolve to a CDN flag URL."""
        url = country_to_flag_url("Russia")
        assert url is not None
        assert url.endswith("ru.png")

    def test_unknown_country(self):
        """Unknown countries should return ``None``."""
        assert country_to_flag_url("Atlantis") is None

    def test_empty_string(self):
        """Empty country names should return ``None``."""
        assert country_to_flag_url("") is None
