from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from predictelligence.pipeline_state import PipelineState


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)

    @abstractmethod
    def run(self, state: PipelineState) -> PipelineState:
        ...
