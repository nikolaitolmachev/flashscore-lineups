"""Mixed unit and integration tests for ``services.parser`` with mocked HTTP."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from entities.player import Player, Position, SquadStatus
from services.config import HISTORY_DEPTH
from services.parser import LineupParser
from services.exceptions import InvalidURLError, SportNotSupportedError
from tests.helpers import json_response, html_response, make_session


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

class TestExtractEventId:
    def test_extracts_mid(self):
        """A valid ``mid`` parameter should be extracted unchanged."""
        url = "https://www.flashscore.com/match/football/x/y/?mid=abc123"
        assert LineupParser._extract_event_id(url) == "abc123"

    def test_missing_mid_raises(self):
        """Missing ``mid`` parameters should raise ``InvalidURLError``."""
        with pytest.raises(InvalidURLError):
            LineupParser._extract_event_id("https://example.com/match/x/y/")


class TestExtractSport:
    def test_football(self):
        """Football URLs should map to ``Sport.FOOTBALL``."""
        from entities.match import Sport
        url = "https://www.flashscore.com/match/football/x/y/?mid=abc"
        assert LineupParser._extract_sport(url) == Sport.FOOTBALL

    def test_hockey(self):
        """Hockey URLs should map to ``Sport.HOCKEY``."""
        from entities.match import Sport
        url = "https://www.flashscore.com/match/hockey/x/y/?mid=abc"
        assert LineupParser._extract_sport(url) == Sport.HOCKEY

    def test_unknown_sport_raises(self):
        """Unsupported sports should raise ``SportNotSupportedError``."""
        with pytest.raises(SportNotSupportedError):
            LineupParser._extract_sport("https://www.flashscore.com/match/tennis/x/y/?mid=abc")


# ---------------------------------------------------------------------------
# _parse_teams_info
# ---------------------------------------------------------------------------

class TestParseTeamsInfo:
    def test_extracts_home_and_away(self, sample_dsof):
        """The helper should extract both teams from the dsof payload."""
        home, away = LineupParser._parse_teams_info(sample_dsof, "ev100")
        assert home["name"] == "Team Home"
        assert home["id"] == "home1"
        assert away["name"] == "Team Away"
        assert away["id"] == "away1"

    def test_previous_event_ids_when_match_not_found(self, sample_dsof):
        """If the current match is not found, keep the newest previous IDs."""
        home, _ = LineupParser._parse_teams_info(sample_dsof, "future_match")
        assert len(home["last_event_ids"]) == HISTORY_DEPTH
        assert home["last_event_ids"] == ["ev1", "ev2", "ev3", "ev4"]

    def test_previous_event_ids_when_match_found(self, sample_dsof):
        """Only matches before the current event should be returned."""
        home, _ = LineupParser._parse_teams_info(sample_dsof, "ev3")
        # ``ev3`` starts at 300, so only ``ev1`` and ``ev2`` come before it.
        assert home["last_event_ids"] == ["ev1", "ev2"]

    def test_raises_when_less_than_two_participants(self):
        """A malformed dsof payload should raise ``ParserError``."""
        dsof = {"eventParticipants": [{"type": {"side": "HOME"}, "name": "Solo"}]}
        from services.exceptions import ParserError
        with pytest.raises(ParserError):
            LineupParser._parse_teams_info(dsof, "ev1")


# ---------------------------------------------------------------------------
# _parse_lineup
# ---------------------------------------------------------------------------

class TestParseLineup:
    def test_extracts_formation_and_statuses(self, sample_dlie2):
        """Formation and player statuses should be extracted from the lineup."""
        formation, status_map = LineupParser._parse_lineup(
            sample_dlie2, side_hint="HOME"
        )
        assert formation == "4-4-2"
        assert status_map == {
            "p1": SquadStatus.IN_XI,
            "p2": SquadStatus.IN_XI,
            "p3": SquadStatus.IN_XI,
            "p4": SquadStatus.ON_BENCH,
            "p5": SquadStatus.ON_BENCH,
        }

    def test_finds_by_team_id(self, sample_dlie2):
        """A stable team ID should locate the correct lineup block."""
        formation, status_map = LineupParser._parse_lineup(
            sample_dlie2, team_id="away1"
        )
        assert formation == "3-5-2"
        assert status_map == {
            "a1": SquadStatus.IN_XI,
            "a2": SquadStatus.IN_XI,
            "a3": SquadStatus.ON_BENCH,
        }

    def test_empty_participants_returns_empty(self):
        """An empty lineup payload should produce an empty status map."""
        _, sm = LineupParser._parse_lineup({"eventParticipants": []}, side_hint="HOME")
        assert sm == {}

    def test_hockey_lines(self):
        """Hockey lines should map to starters and substitutes correctly."""
        dlie2 = {
            "eventParticipants": [{
                "type": {"side": "HOME"},
                "name": "Hockey Team",
                "lineup": {
                    "groups": [
                        {"name": "Line 1", "playerIds": [10, 20]},
                        {"name": "Line 2", "playerIds": [30, 40]},
                        {"name": "Substitutes", "playerIds": [50]},
                    ],
                },
            }]
        }
        _, sm = LineupParser._parse_lineup(dlie2, side_hint="HOME")
        assert sm == {
            "10": SquadStatus.IN_XI,
            "20": SquadStatus.IN_XI,
            "30": SquadStatus.IN_XI,
            "40": SquadStatus.IN_XI,
            "50": SquadStatus.ON_BENCH,
        }


# ---------------------------------------------------------------------------
# _apply_statuses
# ---------------------------------------------------------------------------

class TestApplyStatuses:
    def test_applies_current_and_last_statuses(self):
        """Current and historical statuses should be applied in place."""
        players = [
            Player(participant_id="p1", name="One", url=""),
            Player(participant_id="p2", name="Two", url=""),
            Player(participant_id="p3", name="Three", url=""),
        ]
        current = {"p1": SquadStatus.IN_XI, "p2": SquadStatus.ON_BENCH}
        # ``p3`` is absent from the current lineup, so it defaults to ``ABSENT``.

        last = [
            {"p1": SquadStatus.IN_XI, "p2": SquadStatus.ON_BENCH, "p3": SquadStatus.IN_XI},
            {"p1": SquadStatus.IN_XI, "p2": SquadStatus.ABSENT, "p3": SquadStatus.ON_BENCH},
        ]

        LineupParser._apply_statuses(players, current, last)

        assert players[0].squad_status == SquadStatus.IN_XI
        assert players[1].squad_status == SquadStatus.ON_BENCH
        assert players[2].squad_status == SquadStatus.ABSENT

        # History is stored newest first and padded to ``HISTORY_DEPTH``.
        assert len(players[0].last_match_statuses) == HISTORY_DEPTH
        assert players[0].last_match_statuses[0] == SquadStatus.IN_XI   # ``last[0]``
        assert players[0].last_match_statuses[1] == SquadStatus.IN_XI   # ``last[1]``
        assert players[0].last_match_statuses[2] == SquadStatus.UNKNOWN  # Padding.
        assert players[0].last_match_statuses[3] == SquadStatus.UNKNOWN  # Padding.

    def test_empty_last_statuses_all_unknown(self):
        """No previous history should leave every history slot unknown."""
        players = [Player(participant_id="p1", name="One", url="")]
        LineupParser._apply_statuses(players, {}, [])
        assert players[0].squad_status == SquadStatus.ABSENT
        assert all(s == SquadStatus.UNKNOWN for s in players[0].last_match_statuses)

    def test_failed_last_request_becomes_unknown(self):
        """An empty history entry means the previous request failed, so the status stays unknown."""
        players = [Player(participant_id="p1", name="One", url="")]
        LineupParser._apply_statuses(players, {"p1": SquadStatus.IN_XI}, [{}])
        # Empty dict means ``UNKNOWN``, not ``ABSENT``.
        assert players[0].last_match_statuses[0] == SquadStatus.UNKNOWN


# ---------------------------------------------------------------------------
# _fetch_squad (HTML parsing)
# ---------------------------------------------------------------------------

SQUAD_HTML = """
<div id="overall-all-table">
  <div class="lineupTable">
    <div class="lineupTable__title">Goalkeepers</div>
    <div class="lineupTable__row">
      <a href="/player/team-slug/playerId123/">John Doe</a>
      <div class="lineupTable__cell--jersey">1</div>
      <div class="lineupTable__cell--age">28</div>
      <div class="lineupTable__cell--matchesPlayed">15</div>
      <div class="lineupTable__cell--goal">0</div>
      <div class="lineupTable__cell--minutesPlayed">1350'</div>
      <div class="lineupTable__cell--flag" title="USA"></div>
    </div>
  </div>
  <div class="lineupTable">
    <div class="lineupTable__title">Defenders</div>
    <div class="lineupTable__row">
      <a href="/player/team-slug/playerId456/">Jane Smith</a>
      <div class="lineupTable__cell--jersey">4</div>
      <div class="lineupTable__cell--age">25</div>
      <div class="lineupTable__cell--matchesPlayed">20</div>
      <div class="lineupTable__cell--goal">2</div>
      <div class="lineupTable__cell--minutesPlayed">1800'</div>
      <div class="lineupTable__cell--flag"><img src="https://cdn.example.com/flags/br.png" /></div>
    </div>
  </div>
</div>
"""


class TestFetchSquad:
    def test_parses_players_from_html(self):
        """The squad HTML should produce fully populated player objects."""
        mock_get = MagicMock()
        mock_get.side_effect = [
            html_response(SQUAD_HTML),  # squad page
        ]
        mock_get.return_value = None  # any subsequent call would fail

        parser = LineupParser(session=make_session(mock_get))
        players = parser._fetch_squad("team-slug", "teamId", __import__("entities.match").match.Sport.FOOTBALL)

        assert len(players) == 2

        gk = players[0]
        assert gk.name == "John Doe"
        assert gk.participant_id == "playerId123"
        assert gk.shirt_number == 1
        assert gk.age == 28
        assert gk.matches_played == 15
        assert gk.goals_scored == 0
        assert gk.minutes_played == 1350
        assert gk.position == Position.GOALKEEPER
        assert gk.flag_url and gk.flag_url.endswith("us.png")

        df = players[1]
        assert df.name == "Jane Smith"
        assert df.participant_id == "playerId456"
        assert df.shirt_number == 4
        assert df.position == Position.DEFENDER
        assert df.flag_url and df.flag_url.endswith("br.png")
        assert df.goals_scored == 2


# ---------------------------------------------------------------------------
# Full parse() integration test
# ---------------------------------------------------------------------------

class TestParseIntegration:
    @pytest.fixture
    def dsof_json(self) -> dict:
        return {
            "data": {"findEventById": {
                "eventParticipants": [
                    {
                        "type": {"side": "HOME"},
                        "name": "Home FC",
                        "participants": [{"participant": {
                            "id": "HFC",
                            "url": "home-fc",
                            "images": [],
                            "lastEvents": [
                                {"id": "lastH1", "startTime": 100},
                                {"id": "lastH2", "startTime": 200},
                            ],
                        }}],
                    },
                    {
                        "type": {"side": "AWAY"},
                        "name": "Away United",
                        "participants": [{"participant": {
                            "id": "AU",
                            "url": "away-united",
                            "images": [],
                            "lastEvents": [
                                {"id": "lastA1", "startTime": 150},
                            ],
                        }}],
                    },
                ]
            }}
        }

    @pytest.fixture
    def dlie2_json(self) -> dict:
        return {
            "data": {"findEventById": {
                "eventParticipants": [
                    {
                        "type": {"side": "HOME"},
                        "name": "Home FC",
                        "lineup": {
                            "formation": {"name": "4-3-3"},
                            "groups": [
                                {"name": "Starting Lineups", "playerIds": ["hp1"]},
                                {"name": "Substitutes", "playerIds": ["hp2"]},
                            ],
                        },
                    },
                    {
                        "type": {"side": "AWAY"},
                        "name": "Away United",
                        "lineup": {
                            "formation": {"name": "5-4-1"},
                            "groups": [
                                {"name": "Starting Lineups", "playerIds": ["ap1"]},
                                {"name": "Substitutes", "playerIds": ["ap2"]},
                            ],
                        },
                    },
                ]
            }}
        }

    @pytest.fixture
    def last_dlie2_json(self) -> dict:
        """Simulate a previous match where only one player was in the XI."""
        return {
            "data": {"findEventById": {
                "eventParticipants": [
                    {
                        "type": {"side": "HOME"},
                        "name": "Home FC",
                        "lineup": {
                            "groups": [
                                {"name": "Starting Lineups", "playerIds": ["hp1"]},
                                {"name": "Substitutes", "playerIds": ["hp2"]},
                            ],
                        },
                    },
                ]
            }}
        }

    @pytest.fixture
    def squad_html(self) -> str:
        return """
        <div id="overall-all-table">
          <div class="lineupTable">
            <div class="lineupTable__title">Goalkeepers</div>
            <div class="lineupTable__row">
              <a href="/player/x/hp1/">Alpha</a>
              <div class="lineupTable__cell--jersey">1</div>
              <div class="lineupTable__cell--age">30</div>
              <div class="lineupTable__cell--matchesPlayed">10</div>
              <div class="lineupTable__cell--goal">0</div>
              <div class="lineupTable__cell--flag" title="Russia"></div>
            </div>
            <div class="lineupTable__row">
              <a href="/player/x/hp2/">Beta</a>
              <div class="lineupTable__cell--jersey">7</div>
              <div class="lineupTable__cell--age">22</div>
              <div class="lineupTable__cell--matchesPlayed">5</div>
              <div class="lineupTable__cell--goal">3</div>
              <div class="lineupTable__cell--flag" title="USA"></div>
            </div>
          </div>
        </div>
        """

    def test_full_parse(self, dsof_json, dlie2_json, last_dlie2_json, squad_html):
        """A full parser run should stitch together match, squads, history, and odds."""
        mock_get = MagicMock()
        mock_get.side_effect = [
            json_response(dsof_json),        # 0: dsof
            json_response(dlie2_json),       # 1: dlie2 current
            json_response(last_dlie2_json),  # 2: lastH1
            json_response(last_dlie2_json),  # 3: lastH2
            json_response(last_dlie2_json),  # 4: lastA1
            html_response(squad_html),       # 5: home squad
            html_response(squad_html),       # 6: away squad
            # 7+: bookmaker list request returns empty bookmakers, so ``odds`` stays empty.
            json_response({}),
        ]
        mock_get.return_value = json_response({})

        parser = LineupParser(session=make_session(mock_get))
        # ``_detect_geo()`` uses module-level ``requests.get``, not the session.
        # Mock it so the test stays fully hermetic and makes no real HTTP call.
        with patch("services.parser.requests.get") as mock_requests_get:
            mock_requests_get.side_effect = requests.ConnectionError("offline")
            result = parser.parse(
                "https://www.flashscore.com/match/football/x/y/?mid=test01"
            )

        assert result.match.home_team_name == "Home FC"
        assert result.match.away_team_name == "Away United"
        assert result.match.sport.value == "football"
        # Odds stay empty because the bookmaker list was empty.
        assert result.odds == []

        # Home team.
        ht = result.home_team
        assert ht.name == "Home FC"
        assert len(ht.players) == 2

        alpha = ht.players[0]
        assert alpha.name == "Alpha"
        assert alpha.shirt_number == 1
        assert alpha.squad_status == SquadStatus.IN_XI
        assert alpha.last_match_statuses[0] == SquadStatus.IN_XI    # From the previous match.

        beta = ht.players[1]
        assert beta.name == "Beta"
        assert beta.squad_status == SquadStatus.ON_BENCH
        assert beta.last_match_statuses[0] == SquadStatus.ON_BENCH  # From the previous match.
