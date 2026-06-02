from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.service import (
    GENESIS_SUPPLY_MICRO,
    compute_entry_hash,
    format_mrwk,
    verify_hash_chain,
    verify_supply_conservation,
)
from app.models import LedgerEntry
from app.serializers import public_utc_timestamp

SNAPSHOT_SCHEMA_VERSION = "ledger_snapshot_v1"
PROPOSAL_VALIDATION_MODE = "partial"
PROPOSAL_VALIDATION_NOTE = (
    "Snapshot verifies committed ledger hash-chain and fixed-supply conservation. "
    "It does not replay every historical treasury proposal governance rule."
)


def safe_source_metadata(database_url: str) -> dict[str, str | None]:
    parsed = urlparse(database_url)
    if parsed.scheme.startswith("sqlite"):
        return {"source_mode": "sqlite", "source_host": None}
    if parsed.scheme.startswith(("postgres", "postgresql")):
        return {"source_mode": "postgresql", "source_host": parsed.hostname}
    return {"source_mode": parsed.scheme or "unknown", "source_host": parsed.hostname}


def build_ledger_snapshot(
    session: Session,
    *,
    generated_at: datetime | None = None,
    source_metadata: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    entries = list(session.scalars(select(LedgerEntry).order_by(LedgerEntry.sequence)).all())
    balances: dict[str, int] = {}
    total_credited = 0
    total_debited = 0

    for entry in entries:
        amount = int(entry.amount_microunits)
        if entry.to_account is not None:
            balances[entry.to_account] = balances.get(entry.to_account, 0) + amount
            total_credited += amount
        if entry.from_account is not None:
            balances[entry.from_account] = balances.get(entry.from_account, 0) - amount
            total_debited += amount

    latest_entry = entries[-1] if entries else None
    net_supply = total_credited - total_debited
    source = source_metadata or {"source_mode": "database", "source_host": None}

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": public_utc_timestamp(generated_at),
        "source": {
            "source_mode": source.get("source_mode"),
            "source_host": source.get("source_host"),
        },
        "proposal_validation": PROPOSAL_VALIDATION_MODE,
        "proposal_validation_note": PROPOSAL_VALIDATION_NOTE,
        "ledger_anchor": {
            "latest_sequence": latest_entry.sequence if latest_entry else None,
            "latest_entry_hash": latest_entry.entry_hash if latest_entry else None,
        },
        "genesis_supply_microunits": GENESIS_SUPPLY_MICRO,
        "accounts": [
            {"account": account, "balance_microunits": balance}
            for account, balance in sorted(balances.items())
        ],
        "totals": {
            "total_credited_microunits": total_credited,
            "total_debited_microunits": total_debited,
            "net_supply_microunits": net_supply,
            "net_supply_mrwk": format_mrwk(net_supply),
            "account_balance_sum_microunits": sum(balances.values()),
        },
        "hash_chain": {
            "valid": verify_hash_chain(session),
            "entry_count": len(entries),
            "latest_recomputed_hash": compute_entry_hash(latest_entry)
            if latest_entry is not None
            else None,
        },
        "supply_conservation": {
            "valid": verify_supply_conservation(session),
            "expected_microunits": GENESIS_SUPPLY_MICRO,
            "actual_microunits": net_supply,
        },
    }
