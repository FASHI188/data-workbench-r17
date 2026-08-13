from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from extensions.contracts import (
    DataStatus,
    ExternalDataEnvelope,
    ExtensionKind,
    ExtensionLifecycle,
    ExtensionManifest,
    validate_external_data_envelope,
    validate_extension_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_record() -> ExternalDataEnvelope:
    published = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    available = published + timedelta(minutes=1)
    collected = available + timedelta(minutes=1)
    return ExternalDataEnvelope(event_id="evt-1", idempotency_key="idem-1", event_time=datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc), source="example-official-source", source_ref="snapshot://sha256/example", source_uri="https://example.invalid/source", published_at=published, available_at=available, collected_at=collected, source_sha256="a" * 64, schema_version="source-v1", adapter_version="adapter-v1", parser_version="parser-v1", transform_version="transform-v1", run_id="run-1", task_id="task-1", trace_id="trace-1", upstream_fingerprint="fp-1", data_status=DataStatus.AVAILABLE, revision=1, payload={})


def test_external_envelope_accepts_future_event_announced_earlier() -> None:
    record = _valid_record(); assert record.event_time > record.published_at; validate_external_data_envelope(record)


def test_external_envelope_rejects_future_information_in_pit_order() -> None:
    record = _valid_record()
    with pytest.raises(ValueError, match="available_at"): validate_external_data_envelope(replace(record, available_at=record.published_at - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="collected_at"): validate_external_data_envelope(replace(record, collected_at=record.available_at - timedelta(seconds=1)))


def test_external_envelope_requires_exact_source_hash() -> None:
    with pytest.raises(ValueError, match="source_sha256"): validate_external_data_envelope(replace(_valid_record(), source_sha256="not-a-hash"))


def test_extension_default_is_disabled_and_isolated() -> None:
    manifest = ExtensionManifest(module_id="future-module", module_version="v1", contract_version="V1", kind=ExtensionKind.SOURCE_ADAPTER)
    validate_extension_manifest(manifest); assert manifest.enabled is False; assert manifest.training_allowed is False; assert manifest.live_allowed is False; assert manifest.failure_policy == "ISOLATE_FAIL_CLOSED"; assert manifest.fallback_behavior == "BASELINE_UNCHANGED"


def test_extension_cannot_enable_without_separate_acceptance() -> None:
    with pytest.raises(ValueError, match="acceptance_ref"): validate_extension_manifest(ExtensionManifest(module_id="future-module", module_version="v1", contract_version="V1", kind=ExtensionKind.FEATURE_PLUGIN, lifecycle=ExtensionLifecycle.ENABLED, enabled=True))


def test_extension_cannot_enable_without_rollback_target() -> None:
    with pytest.raises(ValueError, match="rollback target"): validate_extension_manifest(ExtensionManifest(module_id="future-module", module_version="v1", contract_version="V1", kind=ExtensionKind.FEATURE_PLUGIN, lifecycle=ExtensionLifecycle.ENABLED, enabled=True, acceptance_ref="accepted-evidence"))


def test_non_enabled_lifecycle_cannot_sneak_enabled_flag() -> None:
    with pytest.raises(ValueError, match="ENABLED"): validate_extension_manifest(ExtensionManifest(module_id="future-module", module_version="v1", contract_version="V1", kind=ExtensionKind.MODEL_ADAPTER, lifecycle=ExtensionLifecycle.ACCEPTED, enabled=True, acceptance_ref="accepted-evidence"))


def test_registry_reserves_required_interfaces_and_keeps_all_modules_non_enabled() -> None:
    registry = json.loads((ROOT / "governance" / "extension_module_registry.json").read_text())
    assert registry["default_enabled"] is False
    assert all(m["enabled"] is False for m in registry["modules"])
    assert all(m["training_allowed"] is False for m in registry["modules"])
    assert all(m["live_allowed"] is False for m in registry["modules"])
    assert set(registry["required_extension_kinds"]) == {"SOURCE_ADAPTER", "FEATURE_PLUGIN", "MODEL_ADAPTER", "TASK_SCHEDULER", "EVENT_LOG", "OUTPUT_ADAPTER"}
    assert registry["policies"]["no_speculative_business_logic"] is True; assert registry["policies"]["failure_must_not_affect_accepted_baseline"] is True; assert registry["policies"]["shadow_before_enable_required"] is True; assert registry["policies"]["rollback_required"] is True


def test_module_set_fingerprint_is_deterministic() -> None:
    registry = json.loads((ROOT / "governance" / "extension_module_registry.json").read_text()); canonical = json.dumps(registry["modules"], sort_keys=True, separators=(",", ":")).encode(); assert hashlib.sha256(canonical).hexdigest() == registry["module_set_fingerprint"]


def test_registry_locks_current_accepted_baseline_anchor() -> None:
    registry = json.loads((ROOT / "governance" / "extension_module_registry.json").read_text()); anchor = registry["accepted_baseline_anchor"]
    assert anchor["integration_commit"] == "211b022eb3ff0e355de214a6f83c1eabd6d17b10"; assert anchor["stage3_dataset_fingerprint"] == "36bfbe0ae703a923ce2575f111a8c68a64c89177c71eeee2cfd9e1ec47bf535f"; assert anchor["stage4_unlocked"] is False; assert anchor["alpha_training_allowed"] is False; assert anchor["live_signal_allowed"] is False


def test_registry_locks_required_external_lineage_fields() -> None:
    registry = json.loads((ROOT / "governance" / "extension_module_registry.json").read_text()); required = set(registry["external_data_required_fields"])
    for field in {"event_id", "idempotency_key", "event_time", "source", "source_ref", "published_at", "available_at", "collected_at", "source_sha256", "schema_version", "adapter_version", "parser_version", "transform_version", "run_id", "upstream_fingerprint", "revision", "data_status"}: assert field in required


def test_schemas_are_parseable_and_match_contract_version() -> None:
    external = json.loads((ROOT / "schemas" / "external_data_envelope_v1.schema.json").read_text()); manifest = json.loads((ROOT / "schemas" / "extension_module_manifest_v1.schema.json").read_text()); assert external["title"] == "External Data Envelope V1"; assert manifest["title"] == "Extension Module Manifest V1"; assert external["additionalProperties"] is False; assert manifest["additionalProperties"] is False
