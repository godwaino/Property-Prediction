"""
PropertyPipeline — runs PipelineState through all agents in sequence.
"""
from __future__ import annotations

import logging
from typing import Optional

from predictelligence.pipeline_state import PipelineState
from predictelligence.agents.data_agent import DataAgent
from predictelligence.agents.preprocess_agent import PreprocessAgent
from predictelligence.agents.model_agent import ModelAgent
from predictelligence.agents.signal_agent import SignalAgent
from predictelligence.agents.evaluator_agent import EvaluatorAgent

logger = logging.getLogger("predictelligence.pipeline")


class PropertyPipeline:
    """
    Linear agent pipeline.  All agents are singletons — they accumulate state
    (scaler fit, rolling BoE history, model weights) across calls.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.data_agent = DataAgent()
        self.preprocess_agent = PreprocessAgent()
        self.model_agent = ModelAgent()
        self.signal_agent = SignalAgent()

        if db_path:
            self.evaluator_agent = EvaluatorAgent(db_path=db_path)
        else:
            self.evaluator_agent = EvaluatorAgent()

        self._agents = [
            self.data_agent,
            self.preprocess_agent,
            self.model_agent,
            self.signal_agent,
            self.evaluator_agent,
        ]

    def run(
        self,
        postcode: str = "SW1A1AA",
        current_valuation: float = 285_000.0,
        comparable_average: float = 285_000.0,
        user_type: str = "investor",
    ) -> PipelineState:
        state = PipelineState(
            postcode=postcode.replace(" ", "").upper(),
            current_valuation=current_valuation,
            comparable_average=comparable_average if comparable_average > 0 else current_valuation,
            user_type=user_type,
        )

        for agent in self._agents:
            try:
                state = agent._safe_run(state)
            except Exception as exc:
                logger.exception("Unhandled error in agent %s: %s", agent.name, exc)
                state.pipeline_errors.append(f"{agent.name}: {exc}")

        return state
