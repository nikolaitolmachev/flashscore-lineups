"""Bookmaker odds entity."""

from dataclasses import dataclass


@dataclass
class Odds:
    """
    1X2 odds for a single bookmaker.

    Attributes:
        bookmaker: Bookmaker name.
        home: Home win odds.
        draw: Draw odds.
        away: Away win odds.
        home_change: Direction of change since opening, or ``None``.
        draw_change: Direction of change since opening, or ``None``.
        away_change: Direction of change since opening, or ``None``.
    """

    bookmaker: str
    home: str
    draw: str
    away: str
    home_change: str | None = None
    draw_change: str | None = None
    away_change: str | None = None
