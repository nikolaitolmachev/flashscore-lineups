"""
Parser configuration and shared constants.

This module contains service-level settings such as API endpoints,
HTTP parameters, and the CDN base URL. Domain-specific constants such
as group names and regular expressions remain in the parser module.
"""

# ---------------------------------------------------------------------------
# Application-wide constants
# ---------------------------------------------------------------------------

# Number of previous-match status indicators shown per player.
# Keep this value in sync with:
#   - entities/player.py         - Player.last_match_statuses default size
#   - services/parser_helpers.py - previous_event_ids() cap
#   - services/interface.py      - history columns and header labels
HISTORY_DEPTH = 4

# Team side markers used in Flashscore responses.
HOME_SIDE = "HOME"
AWAY_SIDE = "AWAY"

# ---------------------------------------------------------------------------
# Flashscore GraphQL API
# ---------------------------------------------------------------------------

API_BASE = "https://2.ds.lsapp.eu/pq_graphql"
ODDS_API_BASE = "https://global.ds.lsapp.eu/odds/pq_graphql"
PROJECT_ID = 2              # Flashscore project ID: 2 = web / desktop.
HASH_MATCH_INFO = "dsof"    # Basic match info and last events.
HASH_LINEUPS = "dlie2"      # Full lineups, formation, and players.
HASH_BOOKMAKERS = "pobtm"   # Bookmaker list for odds.
HASH_ODDS = "ope2"          # 1X2 odds for a bookmaker.
BET_TYPE_HOME_DRAW_AWAY = "HOME_DRAW_AWAY"
BET_SCOPE_FULL_TIME = "FULL_TIME"

# ---------------------------------------------------------------------------
# Flashscore website
# ---------------------------------------------------------------------------

BASE_URL = "https://www.flashscore.com"
SQUAD_URL_FMT = f"{BASE_URL}/team/{{slug}}/{{team_id}}/squad/"

# ---------------------------------------------------------------------------
# Flashscore CDN
# ---------------------------------------------------------------------------

CDN_BASE = "https://static.flashscore.com/res/"

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.6265.0 Safari/537.36"
)
