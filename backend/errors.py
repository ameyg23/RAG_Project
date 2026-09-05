"""Shared API error type. Routes raise this; main.py's exception handler
converts it to the sanitized {"error": {"code", "message"}} shape from
docs/API.md / docs/SECURITY.md (Error Leakage).
"""


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)
