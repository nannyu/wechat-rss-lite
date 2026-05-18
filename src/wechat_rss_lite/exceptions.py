class WeChatRssLiteError(Exception):
    """Base exception for package errors."""


class FetchError(WeChatRssLiteError):
    """Raised when an article cannot be fetched."""


class ParseError(WeChatRssLiteError):
    """Raised when article HTML cannot be parsed into a useful article."""


class StorageError(WeChatRssLiteError):
    """Raised when persistence operations fail."""

