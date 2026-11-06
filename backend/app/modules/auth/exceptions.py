"""Authentication application outcomes without HTTP or database dependencies."""


class AuthenticationError(Exception):
    """Credentials do not identify a current active account; keep the reason private."""


class RefreshRejectedError(AuthenticationError):
    """A refresh credential cannot be used; clear only this request's cookies."""


class CsrfError(Exception):
    """Origin/client marker or token-bound CSRF proof is missing or invalid."""


class EmailAlreadyRegisteredError(Exception):
    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class AuthStorageUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Authentication storage is temporarily unavailable.")
