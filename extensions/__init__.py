"""Generic extension contracts for future data/model/runtime integrations.

This package intentionally contains no domain-specific business logic. All extension
implementations are opt-in, isolated, separately tested, and separately accepted.
"""

from .contracts import (
    DataStatus,
    ExternalDataEnvelope,
    ExtensionContext,
    ExtensionKind,
    ExtensionLifecycle,
    ExtensionManifest,
    EventLogAdapter,
    FeaturePlugin,
    ModelAdapter,
    OutputAdapter,
    SourceAdapter,
    TaskSchedulerAdapter,
    EntityResolverAdapter,
    validate_external_data_envelope,
    validate_extension_manifest,
)

__all__ = [
    "DataStatus",
    "ExternalDataEnvelope",
    "ExtensionContext",
    "ExtensionKind",
    "ExtensionLifecycle",
    "ExtensionManifest",
    "SourceAdapter",
    "FeaturePlugin",
    "ModelAdapter",
    "TaskSchedulerAdapter",
    "EventLogAdapter",
    "OutputAdapter",
    "EntityResolverAdapter",
    "validate_external_data_envelope",
    "validate_extension_manifest",
]
