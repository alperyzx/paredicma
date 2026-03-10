# pareAuth.py - Session authentication for Paredicma

import secrets
import string

# ── State (module-level singletons) ──────────────────────────────────────────
APP_PASSWORD: str = ""
_active_sessions: dict = {}   # token -> True
_failed_attempts: int = 0
_locked: bool = False

MAX_SESSIONS = 2
MAX_FAILURES = 2


def generate_password(length: int = 8) -> str:
    """Generate a cryptographically strong random password."""
    upper    = string.ascii_uppercase
    lower    = string.ascii_lowercase
    digits   = string.digits
    specials = "!@#$%^&*"
    alphabet = upper + lower + digits + specials
    # Guarantee at least one char from each category
    pwd = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(specials),
    ]
    pwd += [secrets.choice(alphabet) for _ in range(length - 4)]
    # Fisher-Yates shuffle using cryptographic randomness
    for i in range(len(pwd) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        pwd[i], pwd[j] = pwd[j], pwd[i]
    return "".join(pwd)


def init_auth() -> str:
    """Generate and store the session password. Call once at startup."""
    global APP_PASSWORD
    APP_PASSWORD = generate_password()
    return APP_PASSWORD


def is_locked() -> bool:
    return _locked


def session_count() -> int:
    return len(_active_sessions)


def check_session(token) -> bool:
    """Return True if token is a valid active session."""
    return bool(token) and token in _active_sessions


def do_login(password: str):
    """
    Attempt login with the given password.
    Returns (success: bool, result: str)
      success=True  -> result is the new session token
      success=False -> result is one of: "LOCKED", "MAX_SESSIONS", "WRONG"
    """
    global _failed_attempts, _locked
    if _locked:
        return False, "LOCKED"
    if len(_active_sessions) >= MAX_SESSIONS:
        return False, "MAX_SESSIONS"
    if password == APP_PASSWORD:
        token = secrets.token_urlsafe(32)
        _active_sessions[token] = True
        return True, token
    _failed_attempts += 1
    if _failed_attempts >= MAX_FAILURES:
        _locked = True
    return False, "WRONG"


def do_logout(token: str):
    """Remove a session token."""
    _active_sessions.pop(token, None)


def attempts_left() -> int:
    return max(0, MAX_FAILURES - _failed_attempts)
