from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ExtensionKind(str, Enum):
    SOURCE_ADAPTER = "SOURCE_ADAPTER"
    FEATURE_PLUGIN = "FEATURE_PLUGIN"
    MODEL_ADAPTER = "MODEL_ADAPTER"
    TASK_SCHEDULER = "TASK_SCHEDULER"
    EVENT_LOG = "EVENT_LOG"
    OUTPUT_ADAPTER = "OUTPUT_ADAPTER"
    ENTITY_RESOLVER = "ENTITY_RESOLVER"


class ExtensionLifecycle(str, Enum):
    REGISTERED = "REGISTERED"
    SHADOW = "SHADOW"
    TESTED = "TESTED"
    ACCEPTED = "ACCEPTED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"
    ROLLED_BACK = "ROLLED_BACK"


class DataStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    STALE = "STALE"
    INVALID = "INVALID"
    ERROR_FAIL_CLOSED = "ERROR_FAIL_CLOSED"


@dataclass(frozen=True)
class ExtensionContext:
    run_id: str
    task_id: str
    trace_id: str
    as_of: datetime
    module_id: str
    module_version: str


@dataclass(frozen=True)
class ExternalDataEnvelope:
    event_id: str
    idempotency_key: str
    event_time: datetime
    source: str
    source_ref: str
    published_at: datetime
    available_at: datetime
    collected_at: datetime
    source_sha256: str
    schema_version: str
    adapter_version: str
    parser_version: str
    transform_version: str
    run_id: str
    upstream_fingerprint: str
    data_status: DataStatus
    payload: Mapping[str, Any] = field(default_factory=dict)
    source_uri: str | None = None
    task_id: str | None = None
    trace_id: str | None = None
    entity_id: str | None = None
    instrument_id: str | None = None
    revision: int = 1
    supersedes_event_id: str | None = None


@dataclass(frozen=True)
class ExtensionManifest:
    module_id: str
    module_version: str
    contract_version: str
    kind: ExtensionKind
    lifecycle: ExtensionLifecycle = ExtensionLifecycle.REGISTERED
    enabled: bool = False
    input_schema: str | None = None
    output_schema: str | None = None
    dependencies: tuple[str, ...] = ()
    training_allowed: bool = False
    live_allowed: bool = False
    failure_policy: str = "ISOLATE_FAIL_CLOSED"
    fallback_behavior: str = "BASELINE_UNCHANGED"
    timeout_seconds: int = 60
    max_retries: int = 0
    acceptance_ref: str | None = None
    rollback_target_module_version: str | None = None
    rollback_target_module_set_fingerprint: str | None = None


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def validate_external_data_envelope(record: ExternalDataEnvelope) -> None:
    """Validate generic lineage/PIT invariants only; no domain logic lives here."""

    for name in (
        "event_id",
        "idempotency_key",
        "source",
        "source_ref",
        "schema_version",
        "adapter_version",
        "parser_version",
        "transform_version",
        "run_id",
        "upstream_fingerprint",
    ):
        _require_nonempty(name, getattr(record, name))

    for name in ("event_time", "published_at", "available_at", "collected_at"):
        _require_aware(name, getattr(record, name))

    if record.available_at < record.published_at:
        raise ValueError("available_at must not precede published_at")
    if record.collected_at < record.available_at:
        raise ValueError("collected_at must not precede available_at")
    if not _SHA256_RE.fullmatch(record.source_sha256):
        raise ValueError("source_sha256 must be a lowercase 64-character SHA-256 hex digest")
    if record.revision < 1:
        raise ValueError("revision must be >= 1")
    if record.supersedes_event_id == record.event_id:
        raise ValueError("supersedes_event_id must not equal event_id")


def validate_extension_manifest(manifest: ExtensionManifest) -> None:
    """Enforce opt-in, isolation and acceptance boundaries for extension modules."""

    for name in ("module_id", "module_version", "contract_version"):
        _require_nonempty(name, getattr(manifest, name))
    if manifest.failure_policy != "ISOLATE_FAIL_CLOSED":
        raise ValueError("extensions must use ISOLATE_FAIL_CLOSED failure policy")
    if manifest.fallback_behavior != "BASELINE_UNCHANGED":
        raise ValueError("extensions must preserve the accepted baseline on failure")
    if manifest.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")
    if manifest.max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    if manifest.lifecycle != ExtensionLifecycle.ENABLED and manifest.enabled:
        raise ValueError("only an ENABLED lifecycle module may set enabled=true")
    if manifest.lifecycle == ExtensionLifecycle.ENABLED:
        if not manifest.enabled:
            raise ValueError("ENABLED lifecycle requires enabled=true")
        if not manifest.acceptance_ref:
            raise ValueError("ENABLED lifecycle requires an acceptance_ref")
        if not manifest.rollback_target_module_set_fingerprint:
            raise ValueError("ENABLED lifecycle requires a rollback target module-set fingerprint")


@runtime_checkable
class SourceAdapter(Protocol):
    manifest: ExtensionManifest

    def collect(self, context: ExtensionContext) -> Iterable[ExternalDataEnvelope]: ...


@runtime_checkable
class FeaturePlugin(Protocol):
    manifest: ExtensionManifest

    def transform(
        self,
        records: Sequence[ExternalDataEnvelope],
        context: ExtensionContext,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class ModelAdapter(Protocol):
    manifest: ExtensionManifest

    def run(self, request: Mapping[str, Any], context: ExtensionContext) -> Mapping[str, Any]: ...


@runtime_checkable
class TaskSchedulerAdapter(Protocol):
    manifest: ExtensionManifest

    def submit(self, task: Mapping[str, Any], context: ExtensionContext) -> str: ...

    def status(self, task_handle: str) -> Mapping[str, Any]: ...

    def cancel(self, task_handle: str) -> None: ...


@runtime_checkable
class EventLogAdapter(Protocol):
    manifest: ExtensionManifest

    def append(self, event: Mapping[str, Any], context: ExtensionContext) -> None: ...

    def query(self, query: Mapping[str, Any], context: ExtensionContext) -> Sequence[Mapping[str, Any]]: ...


@runtime_checkable
class OutputAdapter(Protocol):
    manifest: ExtensionManifest

    def emit(self, output: Mapping[str, Any], context: ExtensionContext) -> None: ...


@runtime_checkable
class EntityResolverAdapter(Protocol):
    manifest: ExtensionManifest

    def resolve(self, record: ExternalDataEnvelope, context: ExtensionContext) -> Mapping[str, Any]: ...
