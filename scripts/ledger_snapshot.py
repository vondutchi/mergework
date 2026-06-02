from __future__ import annotations

import json

from app.config import get_settings
from app.db import session_scope
from app.ledger.snapshot import build_ledger_snapshot, safe_source_metadata


def main() -> int:
    settings = get_settings()
    with session_scope(settings.database_url) as session:
        snapshot = build_ledger_snapshot(
            session,
            source_metadata=safe_source_metadata(settings.database_url),
        )
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
