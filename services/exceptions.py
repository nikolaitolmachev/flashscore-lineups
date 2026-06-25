"""Exception hierarchy for the Flashscore lineup parser."""


class ParserError(Exception):
    """Base class for all parser errors."""


class InvalidURLError(ParserError):
    """
    Raised when the Flashscore match URL is invalid.

    This error is raised when the ``mid`` query parameter is missing or
    the sport cannot be determined from the URL path.
    """


class SportNotSupportedError(ParserError):
    """Raised when the match sport is not supported."""


class LineupNotReadyError(ParserError):
    """Raised when lineups are not available yet for the match."""
