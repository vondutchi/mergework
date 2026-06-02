from __future__ import annotations

import json
from datetime import UTC, datetime

from app.db import create_schema, session_scope
from app.ledger.service import (
    GENESIS_SUPPLY_MICRO,
    TREASURY_ACCOUNT,
    add_ledger_entry,
    create_bounty,
    ensure_genesis,
)
from app.ledger.snapshot import build_ledger_snapshot, safe_source_metadata

FIXED_GENERATED_AT = datetime(2026, 6, 2, 15, 21, tzinfo=UTC)


def test_ledger_snapshot_is_deterministic_and_uses_integer_microunits(
    sqlite_url: str,
) -> None:
    create_schema(sqlite_url)
    with session_scope(sqlite_url) as session:
        ensure_genesis(session)
        create_bounty(
            session,
            repo="ramimbo/mergework",
            issue_number=764,
            issue_url="https://github.com/ramimbo/mergework/issues/764",
            title="Ledger snapshot exporter",
            reward_mrwk="700",
            acceptance="Read-only ledger snapshot exporter.",
        )
        first = build_ledger_snapshot(
            session,
            generated_at=FIXED_GENERATED_AT,
            source_metadata={"source_mode": "test", "source_host": None},
        )
        second = build_ledger_snapshot(
            session,
            generated_at=FIXED_GENERATED_AT,
            source_metadata={"source_mode": "test", "source_host": None},
        )

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["schema_version"] == "ledger_snapshot_v1"
    assert first["generated_at"] == "2026-06-02T15:21:00Z"
    assert first["proposal_validation"] == "partial"
    assert first["genesis_supply_microunits"] == GENESIS_SUPPLY_MICRO
    assert first["ledger_anchor"]["latest_sequence"] == 2
    assert first["ledger_anchor"]["latest_entry_hash"]
    assert first["hash_chain"] == {
        "valid": True,
        "entry_count": 2,
        "latest_recomputed_hash": first["ledger_anchor"]["latest_entry_hash"],
    }
    assert first["supply_conservation"] == {
        "valid": True,
        "expected_microunits": GENESIS_SUPPLY_MICRO,
        "actual_microunits": GENESIS_SUPPLY_MICRO,
    }
    assert first["totals"]["total_credited_microunits"] == GENESIS_SUPPLY_MICRO + 700_000000
    assert first["totals"]["total_debited_microunits"] == 700_000000
    assert first["totals"]["net_supply_microunits"] == GENESIS_SUPPLY_MICRO
    assert first["totals"]["account_balance_sum_microunits"] == GENESIS_SUPPLY_MICRO
    assert first["accounts"] == [
        {"account": "reserve:bounty:1", "balance_microunits": 700_000000},
        {
            "account": TREASURY_ACCOUNT,
            "balance_microunits": GENESIS_SUPPLY_MICRO - 700_000000,
        },
    ]
    assert all(isinstance(row["balance_microunits"], int) for row in first["accounts"])


def test_ledger_snapshot_reports_hash_chain_failure(sqlite_url: str) -> None:
    create_schema(sqlite_url)
    with session_scope(sqlite_url) as session:
        entry = ensure_genesis(session)
        entry.entry_hash = "f" * 64
        snapshot = build_ledger_snapshot(
            session,
            generated_at=FIXED_GENERATED_AT,
            source_metadata={"source_mode": "test", "source_host": None},
        )

    assert snapshot["hash_chain"]["valid"] is False
    assert snapshot["ledger_anchor"]["latest_entry_hash"] == "f" * 64
    assert snapshot["hash_chain"]["latest_recomputed_hash"] != "f" * 64
    assert snapshot["supply_conservation"]["valid"] is True


def test_ledger_snapshot_reports_supply_conservation_failure(sqlite_url: str) -> None:
    create_schema(sqlite_url)
    with session_scope(sqlite_url) as session:
        ensure_genesis(session)
        add_ledger_entry(
            session,
            entry_type="manual_adjustment",
            from_account=None,
            to_account="github:extra",
            amount_microunits=1,
            reference="test-extra-credit",
        )
        snapshot = build_ledger_snapshot(
            session,
            generated_at=FIXED_GENERATED_AT,
            source_metadata={"source_mode": "test", "source_host": None},
        )

    assert snapshot["hash_chain"]["valid"] is True
    assert snapshot["supply_conservation"] == {
        "valid": False,
        "expected_microunits": GENESIS_SUPPLY_MICRO,
        "actual_microunits": GENESIS_SUPPLY_MICRO + 1,
    }
    assert snapshot["totals"]["net_supply_microunits"] == GENESIS_SUPPLY_MICRO + 1


def test_ledger_snapshot_source_metadata_does_not_leak_credentials() -> None:
    metadata = safe_source_metadata("postgresql://user:secret@example.com:5432/mergework")

    assert metadata == {"source_mode": "postgresql", "source_host": "example.com"}


def test_ledger_snapshot_script_prints_snapshot_json(
    sqlite_url: str,
    monkeypatch,
    capsys,
) -> None:
    create_schema(sqlite_url)
    with session_scope(sqlite_url) as session:
        ensure_genesis(session)

    monkeypatch.setenv("MERGEWORK_DATABASE_URL", sqlite_url)

    from scripts import ledger_snapshot

    assert ledger_snapshot.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "ledger_snapshot_v1"
    assert payload["source"] == {"source_mode": "sqlite", "source_host": None}
    assert payload["ledger_anchor"]["latest_sequence"] == 1
    assert payload["hash_chain"]["valid"] is True
    assert payload["supply_conservation"]["valid"] is True
