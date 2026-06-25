"""Shared pytest fixtures for lineup parser tests.

Fixtures defined here are auto-discovered by pytest — no manual
import needed in test modules.  Plain helper factories live in
``tests/helpers.py`` and are imported explicitly where used.
"""

import os

import pytest


# Qt needs an offscreen context before any QPixmap/QPainter is created.
os.environ["QT_QPA_PLATFORM"] = "offscreen"


# ---------------------------------------------------------------------------
# Qt fixture — shared across interface smoke tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """One-shot QApplication for the entire test session."""
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


# ---------------------------------------------------------------------------
# Shared API fixtures — minimal payloads for parser and parser_helpers tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_dsof() -> dict:
    """Minimal dsof response with two teams and lastEvents."""
    return {
        "eventParticipants": [
            {
                "type": {"side": "HOME"},
                "name": "Team Home",
                "participants": [{
                    "participant": {
                        "id": "home1",
                        "url": "team-home",
                        "images": [],
                        "lastEvents": [
                            {"id": "ev1", "startTime": 100},
                            {"id": "ev2", "startTime": 200},
                            {"id": "ev3", "startTime": 300},
                            {"id": "ev4", "startTime": 400},
                            {"id": "ev5", "startTime": 500},
                        ],
                    }
                }],
            },
            {
                "type": {"side": "AWAY"},
                "name": "Team Away",
                "participants": [{
                    "participant": {
                        "id": "away1",
                        "url": "team-away",
                        "images": [],
                        "lastEvents": [
                            {"id": "evA1", "startTime": 150},
                            {"id": "evA2", "startTime": 250},
                        ],
                    }
                }],
            },
        ]
    }


@pytest.fixture
def sample_dlie2() -> dict:
    """Minimal dlie2 response with starters, bench, and formation."""
    return {
        "eventParticipants": [
            {
                "type": {"side": "HOME"},
                "name": "Team Home",
                "participants": [{"participant": {"id": "home1"}}],
                "lineup": {
                    "formation": {"name": "4-4-2"},
                    "groups": [
                        {"name": "Starting Lineups", "playerIds": ["p1", "p2", "p3"]},
                        {"name": "Substitutes", "playerIds": ["p4", "p5"]},
                    ],
                    "players": [
                        {
                            "id": "p1", "listName": "Player One",
                            "fieldName": "One", "number": "1",
                            "playerRoles": [{"suffix": "(G)", "title": "Goalkeeper"}],
                            "participant": {"url": "player-one"},
                            "teamName": "Club One",
                        },
                        {
                            "id": "p2", "listName": "Player Two",
                            "fieldName": "Two", "number": "2",
                            "playerRoles": [{"suffix": "(D)", "title": "Defender"}],
                            "participant": {"url": "player-two"},
                            "teamName": "Club Two",
                        },
                        {
                            "id": "p3", "listName": "Player Three",
                            "fieldName": "Three", "number": "3",
                            "playerRoles": [{"suffix": "(M)", "title": "Midfielder"}],
                            "participant": {"url": "player-three"},
                            "teamName": "Club Three",
                        },
                        {
                            "id": "p4", "listName": "Player Four",
                            "fieldName": "Four", "number": "4",
                            "playerRoles": [{"suffix": "(A)", "title": "Forward"}],
                            "participant": {"url": "player-four"},
                            "teamName": "Club Four",
                        },
                        {
                            "id": "p5", "listName": "Player Five",
                            "fieldName": "Five", "number": "5",
                            "playerRoles": [{"suffix": "(M)", "title": "Midfielder"}],
                            "participant": {"url": "player-five"},
                            "teamName": "Club Five",
                        },
                    ],
                },
            },
            {
                "type": {"side": "AWAY"},
                "name": "Team Away",
                "participants": [{"participant": {"id": "away1"}}],
                "lineup": {
                    "formation": {"name": "3-5-2"},
                    "groups": [
                        {"name": "Starting Lineups", "playerIds": ["a1", "a2"]},
                        {"name": "Substitutes", "playerIds": ["a3"]},
                    ],
                },
            },
        ]
    }
