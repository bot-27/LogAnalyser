"""
Custom exceptions for the API layer.

Routes catch these and map them to appropriate HTTP responses.
"""


class ValidationError(Exception):
    """Raised by controllers when input validation fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(Exception):
    """Raised by services when a requested resource does not exist."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ServiceError(Exception):
    """Raised by services on unexpected business-logic failures."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
