from __future__ import annotations


class SlideScoreAPIError(Exception):
    """Structured error from the SlideScore HTTP API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        server_message: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.server_message = server_message
        self.endpoint = endpoint


SlideScoreErrorException = SlideScoreAPIError  # deprecated compatibility alias
