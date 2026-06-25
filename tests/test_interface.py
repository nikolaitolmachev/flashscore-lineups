"""Smoke tests for the ``services.interface`` UI helpers."""

import pytest

from entities.player import SquadStatus
from services.config import HISTORY_DEPTH


@pytest.mark.usefixtures("qapp")
class TestStatusPixmap:
    def test_returns_pixmap_for_each_status(self):
        """Every squad status should produce a valid pixmap."""
        from services.interface import _status_pixmap
        for status in SquadStatus:
            pix = _status_pixmap(status)
            assert pix is not None
            assert not pix.isNull()

    def test_different_statuses_have_different_colors(self):
        """All four statuses produce visually distinct pixmaps."""
        from services.interface import _status_pixmap
        pixmaps = {s: _status_pixmap(s) for s in SquadStatus}
        data = {s: p.toImage().pixelColor(6, 6).name() for s, p in pixmaps.items()}
        assert len(set(data.values())) == 4, f"Expected 4 unique colors, got {data}"


class TestHistoryDepthIntegration:
    """Verify that the interface module picks up HISTORY_DEPTH correctly."""

    def test_column_count_scales_with_history(self):
        """The history columns and final status column should stay aligned."""
        from services.interface import _HISTORY_START_COL, _NOW_COL, _COLUMN_COUNT
        assert _NOW_COL == _HISTORY_START_COL + HISTORY_DEPTH
        assert _COLUMN_COUNT == _NOW_COL + 1
        for i in range(HISTORY_DEPTH):
            col = _HISTORY_START_COL + i
            assert 0 <= col < _NOW_COL
        assert _NOW_COL < _COLUMN_COUNT
