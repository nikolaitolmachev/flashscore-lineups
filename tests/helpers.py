"""Reusable test factories — not pytest fixtures, imported directly."""

from unittest.mock import MagicMock

import requests


def json_response(data: dict) -> MagicMock:
    """Return a mock response whose ``.json()`` yields *data*."""
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def html_response(html: str) -> MagicMock:
    """Return a mock response whose ``.text`` is *html*."""
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def make_session(mock_get: MagicMock) -> requests.Session:
    """Return a ``Session`` whose ``get`` is replaced by *mock_get*."""
    session = requests.Session()
    session.get = mock_get
    return session
