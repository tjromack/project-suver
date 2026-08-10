"""Test session setup — keep every test deterministic and OFFLINE.

The product now defaults to the real model when an `ANTHROPIC_API_KEY` is present (see `app/config.py`). Tests
must not depend on that: force the offline `stub` provider before `app.config` is imported, so the suite runs
with no network/key regardless of a local `.env`. (`load_dotenv` won't override an already-set env var.)
"""

import os
import tempfile
from pathlib import Path

os.environ["PROVIDER"] = "stub"

# Accounts/persistence (DEC 034): point the SQLite store at a throwaway DB so tests never touch a real one, and
# start each session clean. Set before `app.config` is imported (like PROVIDER).
_test_db = Path(tempfile.gettempdir()) / "suver_test.db"
for p in (_test_db, Path(str(_test_db) + "-wal"), Path(str(_test_db) + "-shm")):
    try:
        p.unlink()
    except FileNotFoundError:
        pass
os.environ["SUVER_DB"] = str(_test_db)

import pytest


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiter():
    """The auth rate limiter (DEC 035) is in-memory and keyed by client IP; TestClient shares one IP, so clear it
    before each test — otherwise auth POSTs bleed across tests and trip the limit."""
    import app.main as _m
    _m._auth_hits.clear()
    yield
