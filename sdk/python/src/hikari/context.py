"""Context propagation helpers using ``contextvars``.

Provides per-async-task storage of ``pipeline_id`` and ``stage`` so that
provider patches can read them without explicit parameter threading.
"""

from __future__ import annotations

import contextvars

_pipeline_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "hikari_pipeline_id", default=None
)
_stage: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "hikari_stage", default=None
)


def get_pipeline_id() -> str | None:
    """Return the current pipeline ID, or ``None`` if not set."""
    return _pipeline_id.get()


def set_pipeline_id(pipeline_id: str) -> None:
    """Set the pipeline ID on the current async context."""
    _pipeline_id.set(pipeline_id)


def get_stage() -> str | None:
    """Return the current stage override, or ``None`` if not set."""
    return _stage.get()


def set_stage(stage: str) -> None:
    """Override the auto-derived stage name on the current async context."""
    _stage.set(stage)
