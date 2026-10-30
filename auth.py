"""
auth.py - Login for the Student Support Agent (Assignment 2).

- Passwords are stored ONLY as salted PBKDF2-SHA256 hashes in data/users.json.
- authenticate() returns the user's identity, or None. The same failure is returned
  for an unknown ID and a wrong password, so the login screen never reveals which IDs exist.
- After login, the app keeps the identity in the session. Nothing typed in the chat can change it.
"""
import hashlib
import hmac
import json
import secrets
from pathlib import Path

USERS_FILE = Path(__file__).parent / "data" / "users.json"
ITERATIONS = 200_000


def hash_password(password, salt=None):
    """Return 'pbkdf2_sha256$iterations$salt$hash'."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password, stored):
    """True if `password` matches the stored hash. Constant-time comparison."""
    try:
        algo, iterations, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


def load_users():
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def authenticate(user_id, password):
    """Return {"id", "role", "name"} if the ID and password match, otherwise None."""
    user_id = (user_id or "").strip()
    users = load_users()
    key = next((k for k in users if k.lower() == user_id.lower()), None)
    record = users.get(key) if key else None
    if not record or not password:
        hash_password("dummy")          # same work either way, so timing does not reveal valid IDs
        return None
    if not verify_password(password, record["password_hash"]):
        return None
    return {"id": key, "role": record["role"], "name": record.get("name", key)}
