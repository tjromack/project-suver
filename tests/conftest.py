"""Test session setup — keep every test deterministic and OFFLINE.

The product now defaults to the real model when an `ANTHROPIC_API_KEY` is present (see `app/config.py`). Tests
must not depend on that: force the offline `stub` provider before `app.config` is imported, so the suite runs
with no network/key regardless of a local `.env`. (`load_dotenv` won't override an already-set env var.)
"""

import os

os.environ["PROVIDER"] = "stub"
