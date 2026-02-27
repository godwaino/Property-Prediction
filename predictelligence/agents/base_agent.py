"""Abstract base class for all pipeline agents."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from predictelligence.pipeline_state import PipelineState


class BaseAgent(ABC):
    """Every agent has a name, a logger, and a run() method."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = logging.getLogger(f"predictelligence.{name}")

    @abstractmethod
    def run(self, state: PipelineState) -> PipelineState:
        """Process state and return the (modified) state."""
        ...

    def _safe_run(self, state: PipelineState) -> PipelineState:
        """Wrap run() with error capture so pipeline never hard-crashes."""
        try:
            return self.run(state)
        except Exception as exc:
            self.logger.exception("Agent %s failed: %s", self.name, exc)
            state.pipeline_errors.append(f"{self.name}: {exc}")
            return state
