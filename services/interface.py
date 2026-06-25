"""PyQt5 user interface for the Lineups application.

This module connects the UI layer to the ``LineupParser`` service and the domain entities.
"""

import base64
import html
import os
import subprocess
import sys
import webbrowser
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import requests
from requests.exceptions import RequestException
from PyQt5 import QtCore, QtGui, QtWidgets

from entities.odds import Odds
from entities.match import Sport
from entities.player import IHGoalkeeper, Player, Position, SquadStatus
from entities.team import Team
from services.config import HISTORY_DEPTH
from services.exceptions import (
    InvalidURLError,
    LineupNotReadyError,
    ParserError,
    SportNotSupportedError,
)
from services.parser import LineupParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Project root: ``sys._MEIPASS`` when bundled by PyInstaller, otherwise ``__file__`` parent.
_BASE = getattr(sys, '_MEIPASS', str(Path(__file__).resolve().parent.parent))
BASE_DIR = Path(_BASE)
ICON_PATH = BASE_DIR / "assets" / ("logo.png" if sys.platform == "linux" else "icon.ico")

MOUSE_BOOKIES = ('1xBet',)

_HISTORY_START_COL = 10
_NOW_COL = _HISTORY_START_COL + HISTORY_DEPTH
_COLUMN_COUNT = _NOW_COL + 1

# Width of each column index, in pixels.
_BASE_COL_WIDTHS: dict[int, int] = {
    0: 30,   # #
    1: 180,  # Name
    2: 30,   # Flag
    3: 30,   # Age
    4: 28,   # Pos
    5: 35,   # MP
    6: 30,   # G
    7: 45,   # SV
    8: 35,   # GAA
    9: 30,   # SO
}
_COL_WIDTHS: dict[int, int] = {
    **_BASE_COL_WIDTHS,
    **{
        _HISTORY_START_COL + i: 20
        for i in range(HISTORY_DEPTH)
    },
    _NOW_COL: 30,
}
_TABLE_MAX_WIDTH = sum(_COL_WIDTHS.values()) + 15  # Extra space for the scrollbar.
_DATA_ROW_HEIGHT = 22
_SEPARATOR_ROW_HEIGHT = 1

_SESSION = requests.Session()
_SESSION.headers.setdefault(
    "User-Agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
)


def _open_url(url: str) -> None:
    """Open *url* in the system browser. This works reliably on Windows, macOS, and Linux."""
    if sys.platform == "win32":
        os.startfile(url)  # Use the native Windows shell handler.
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:  # Linux and other Unix-like systems.
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, webbrowser.Error):
            webbrowser.open(url)


@lru_cache(maxsize=512)
def _img_b64(url: str, width: int | None = None) -> str:
    """Download *url* and return an ``<img>`` tag with cached base64-encoded data."""
    try:
        resp = _SESSION.get(url, timeout=10)
        resp.raise_for_status()
        b64 = base64.b64encode(resp.content).decode()
        mime = resp.headers.get("Content-Type", "image/png")
        size_attr = f' width="{width}"' if width else ""
        return '<img src="data:{};base64,{}"{}>'.format(mime, b64, size_attr)
    except (requests.RequestException, ValueError, TypeError, OSError):
        return ""


def _status_pixmap(status: SquadStatus) -> QtGui.QPixmap:
    """Return a 12x12 colored circle ``QPixmap``."""
    colors = {
        SquadStatus.IN_XI:     QtGui.QColor("#2ecc71"),  # Green.
        SquadStatus.ON_BENCH:  QtGui.QColor("#f1c40f"),  # Yellow.
        SquadStatus.ABSENT:    QtGui.QColor("#e74c3c"),  # Red.
        SquadStatus.UNKNOWN:   QtGui.QColor("#95a5a6"),  # Gray.
    }
    color = colors.get(status, QtGui.QColor("#95a5a6"))
    pix = QtGui.QPixmap(12, 12)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setBrush(QtGui.QBrush(color))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, 12, 12)
    painter.end()
    return pix


def _change_arrow(change: str | None) -> str:
    """Return the arrow symbol for an odds change marker."""
    if change == "UP":
        return "↑"
    if change == "DOWN":
        return "↓"
    return ""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class UiMainWindow:
    """PyQt5 main window: the layout is defined in code and the behavior below."""

    def __init__(self) -> None:
        self.centralwidget: QtWidgets.QWidget | None = None
        self.label: QtWidgets.QLabel | None = None
        self.lineEdit: QtWidgets.QLineEdit | None = None
        self.pushButton: QtWidgets.QPushButton | None = None
        self.label_2: QtWidgets.QLabel | None = None
        self.tableWidget: QtWidgets.QTableWidget | None = None
        self.label_3: QtWidgets.QLabel | None = None
        self.tableWidget_2: QtWidgets.QTableWidget | None = None
        self.statusbar: QtWidgets.QStatusBar | None = None

    def setup_ui(self, main_window: QtWidgets.QMainWindow) -> None:
        """Build and attach the main window widgets and signal wiring."""
        # Generated UI setup.
        main_window.setObjectName("MainWindow")
        main_window.resize(1200, 800)
        main_window.setMinimumSize(QtCore.QSize(900, 600))
        main_window.setWindowTitle("Lineups")
        main_window.setWindowIcon(QtGui.QIcon(str(ICON_PATH)))

        # Central widget and main layout.
        self.centralwidget = QtWidgets.QWidget(main_window)
        self.centralwidget.setObjectName("centralwidget")
        main_layout = QtWidgets.QVBoxLayout(self.centralwidget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Top bar: match URL input.
        top_bar = QtWidgets.QHBoxLayout()
        self.label = QtWidgets.QLabel("URL:")
        self.label.setFixedWidth(40)
        top_bar.addWidget(self.label)

        self.lineEdit = QtWidgets.QLineEdit()
        self.lineEdit.setPlaceholderText("https://www.flashscore.com/match/.../?mid=...")
        top_bar.addWidget(self.lineEdit, 1)  # Expand to fill the available space.

        self.pushButton = QtWidgets.QPushButton("Check lineups")
        self.pushButton.setFixedWidth(120)
        top_bar.addWidget(self.pushButton)

        main_layout.addLayout(top_bar)

        # Team tables side by side.
        tables_layout = QtWidgets.QHBoxLayout()
        tables_layout.setSpacing(10)

        # Home team.
        self.label_2, self.tableWidget = self._build_team_panel(tables_layout)

        # Away team.
        self.label_3, self.tableWidget_2 = self._build_team_panel(tables_layout)

        main_layout.addLayout(tables_layout, 1)
        main_layout.addStretch(0)

        # Start empty so the layout stays stable.
        self.label_2.setText("")
        self.label_3.setText("")

        main_window.setCentralWidget(self.centralwidget)

        self.statusbar = QtWidgets.QStatusBar(main_window)
        self.statusbar.setObjectName("statusbar")
        main_window.setStatusBar(self.statusbar)

        cast(Any, self.pushButton.clicked).connect(self._on_click)

    # Business logic.
    def _on_click(self) -> None:
        """Handle a click on the *Check lineups* button."""
        self._reset_ui()
        self.pushButton.setEnabled(False)

        url = self.lineEdit.text().strip()

        if "flashscore.com/match/" not in url:
            self._show_error("Fill a valid Flashscore match URL to continue!")
            self.pushButton.setEnabled(True)
            return

        _img_b64.cache_clear()
        parser = LineupParser()
        try:
            result = parser.parse(url)
        except InvalidURLError:
            self._show_error("Invalid URL - missing match ID (?mid=)")
        except SportNotSupportedError:
            self._show_error("Only football and hockey matches are supported.")
        except LineupNotReadyError:
            self._show_error("Lineups are not ready for this match yet. Try again later.")
        except RequestException:
            self._show_error("Network error. Check your internet connection or try again later.")
        except ParserError:
            self._show_error("Could not parse match data. The page format may have changed.")
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            self._show_error("Something went wrong. Try again later.")
        else:
            self._render_team(
                result.home_team,
                result.match.sport,
                self.tableWidget,
                self.label_2,
            )
            self._render_team(
                result.away_team,
                result.match.sport,
                self.tableWidget_2,
                self.label_3,
            )
            odds_text = self._render_odds(result.odds)
            self.statusbar.showMessage(
                f"  {result.match.sport.value.capitalize()} | "
                f"{result.home_team.name}  vs  {result.away_team.name}"
                f"{odds_text}"
            )

        self.pushButton.setEnabled(True)

    def _reset_ui(self) -> None:
        """Clear the current match data before loading new results."""
        self.label_2.setText("")
        self.label_3.setText("")
        self.tableWidget.clear()
        self.tableWidget.setRowCount(0)
        self.tableWidget.setColumnCount(0)
        self.tableWidget_2.clear()
        self.tableWidget_2.setRowCount(0)
        self.tableWidget_2.setColumnCount(0)
        self.statusbar.clearMessage()

    @staticmethod
    def _build_team_panel(parent: QtWidgets.QHBoxLayout) -> tuple[QtWidgets.QLabel, QtWidgets.QTableWidget]:
        """Create a team title label and its table inside *parent*."""
        panel = QtWidgets.QVBoxLayout()

        label = QtWidgets.QLabel()
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(60)
        panel.addWidget(label)

        table = QtWidgets.QTableWidget()
        table.setColumnCount(0)
        table.setRowCount(0)
        panel.addWidget(table, 1)

        parent.addLayout(panel, 1)
        return label, table

    # Table rendering.
    @staticmethod
    def _render_team(team: Team, sport: Sport, table: QtWidgets.QTableWidget, label: QtWidgets.QLabel) -> None:
        """Populate *table* and *label* with the data from *team*."""
        # Team header: base64 logo plus team name.
        logo_tag = ""
        if team.logo_url:
            logo_tag = _img_b64(team.logo_url, width=50) + "<br>"
        label.setText(f'<div style="text-align:center">{logo_tag}{html.escape(team.name)}</div>')

        # Show only players with a known position; coaches and staff have none.
        players = sorted(
            (p for p in team.players if p.position is not Position.UNKNOWN),
            key=lambda p: (
                -(p.minutes_played or 0),
                -(p.matches_played or 0),
                -p.goals_scored,
                -p.squad_status.value,
            ),
        )

        sep_after = 11 if sport == Sport.FOOTBALL else 19
        extra_rows = 1 if len(players) > sep_after else 0
        total_rows = len(players) + extra_rows

        table.setRowCount(total_rows)
        table.setColumnCount(_COLUMN_COUNT)

        # Column widths: the name column stretches to fill the remaining space.
        for ci in range(_COLUMN_COUNT):
            table.setColumnWidth(ci, _COL_WIDTHS.get(ci, 35))
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

        # Row heights.
        sep_index = sep_after
        for ri in range(total_rows):
            table.setRowHeight(ri, _SEPARATOR_ROW_HEIGHT if ri == sep_index else _DATA_ROW_HEIGHT)

        # Table styling.
        table.setShowGrid(False)
        table.setStyleSheet("QTableView::item { border-top: 1px solid black; }")
        history_labels = ["<-"] * max(0, HISTORY_DEPTH - 1) + ["Last"]
        table.setHorizontalHeaderLabels([
            "#", "Name", "", "Age", "Pos",
            "MP", "G", "SV", "GAA", "SO",
            *history_labels, "Now",
        ])
        table.verticalHeader().hide()

        # Populate rows.
        row = 0
        for player in players:
            if row == sep_index:
                row += 1  # Skip the separator row.
            _fill_player_row(table, row, player, sport)
            row += 1

    # Odds rendering.
    @staticmethod
    def _render_odds(odds_list: list[Odds]) -> str:
        """Return a status-bar string with 1X2 odds."""
        if not odds_list:
            return ""

        lines: list[str] = []
        visible_odds = [odd for odd in odds_list if odd.bookmaker not in MOUSE_BOOKIES]
        for odd in visible_odds[:3]:
            if odd.bookmaker in MOUSE_BOOKIES:
                continue
            h = odd.home
            d = odd.draw
            a = odd.away
            h_arr = _change_arrow(odd.home_change)
            d_arr = _change_arrow(odd.draw_change)
            a_arr = _change_arrow(odd.away_change)
            lines.append(f"{odd.bookmaker}: {h}{h_arr} - {d}{d_arr} - {a}{a_arr}")
        return "  |  " + "  |  ".join(lines) if lines else ""

    # Error popup.
    def _show_error(self, message: str) -> None:
        msg = QtWidgets.QMessageBox(self.centralwidget)
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setText(message)
        msg.setWindowTitle("Lineups")
        msg.exec_()


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------

def _fill_player_row(table: QtWidgets.QTableWidget, row: int, player: Player, sport: Sport) -> None:
    """Write a single player row into *table* at *row*."""
    is_goalie = isinstance(player, IHGoalkeeper)
    goalie = cast(IHGoalkeeper, player) if is_goalie else None

    # Column 0: shirt number.
    _set_cell(table, row, 0, str(player.shirt_number) if player.shirt_number is not None else "")

    # Column 1: name (hyperlinked if a URL is available).
    if player.url:
        name_html = f'<a href="{html.escape(player.url, quote=True)}">{html.escape(player.name)}</a>'
    else:
        name_html = html.escape(player.name)
    name_label = QtWidgets.QLabel(name_html)
    if sys.platform == "win32":
        name_label.setOpenExternalLinks(True)  # Use the native Windows shell handler.
    else:
        name_label.linkActivated.connect(_open_url)  # Use xdg-open on Unix-like systems.
    table.setCellWidget(row, 1, name_label)

    # Column 2: flag (base64 image in a QLabel).
    if player.flag_url:
        flag_tag = _img_b64(player.flag_url, width=15)
        flag_label = QtWidgets.QLabel(flag_tag)
        flag_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        table.setCellWidget(row, 2, flag_label)

    # Column 3: age.
    _set_cell(table, row, 3, str(player.age) if player.age is not None else "·")

    # Column 4: position.
    _set_cell(table, row, 4, str(player.position.value))

    # Column 5: matches played.
    _set_cell(table, row, 5, str(player.matches_played))

    # Column 6: goals (hockey goalies use SV%/GAA/SO instead).
    if is_goalie and sport == Sport.HOCKEY:
        _set_cell(table, row, 6, "")
    else:
        _set_cell(table, row, 6, str(player.goals_scored))

    # Column 7: SV% (goalie only).
    if goalie is not None:
        _set_cell(table, row, 7, str(goalie.sv) if goalie.sv else "·")
    else:
        _set_cell(table, row, 7, "")

    # Column 8: GAA (goalie only).
    if goalie is not None:
        _set_cell(table, row, 8, str(goalie.gaa) if goalie.gaa else "·")
    else:
        _set_cell(table, row, 8, "")

    # Column 9: SO (goalie only).
    if goalie is not None:
        _set_cell(table, row, 9, str(goalie.so) if goalie.so else "·")
    else:
        _set_cell(table, row, 9, "")

    # History columns run from oldest on the left to newest on the right.
    for i, status in enumerate(reversed(player.last_match_statuses[:HISTORY_DEPTH])):
        pix = _status_pixmap(status)
        lbl = QtWidgets.QLabel()
        lbl.setPixmap(pix)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        table.setCellWidget(row, _HISTORY_START_COL + i, lbl)

    # Final column: current status (colored dot).
    now_pix = _status_pixmap(player.squad_status)
    now_label = QtWidgets.QLabel()
    now_label.setPixmap(now_pix)
    now_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    table.setCellWidget(row, _NOW_COL, now_label)


def _set_cell(table: QtWidgets.QTableWidget, row: int, col: int, text: str) -> None:
    """Set a plain-text cell with centered alignment."""
    item = QtWidgets.QTableWidgetItem(text)
    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    table.setItem(row, col, item)
