"""
PropertyPipeline — runs PipelineState through all agents in sequence.
Supports save/load of agent state for persistence across restarts.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from predictelligence.pipeline_state import PipelineState
from predictelligence.agents.data_agent import DataAgent
from predictelligence.agents.preprocess_agent import PreprocessAgent
from predictelligence.agents.model_agent import ModelAgent
from predictelligence.agents.signal_agent import SignalAgent
from predictelligence.agents.evaluator_agent import EvaluatorAgent

logger = logging.getLogger("predictelligence.pipeline")

# How many cycles between auto-saves (saves every N training cycles)
_SAVE_EVERY_N_CYCLES = 10


class PropertyPipeline:
    """
    Linear agent pipeline.  All agents are singletons — they accumulate state
    (scaler fit, rolling BoE history, model weights) across calls.
    """

    def __init__(self, db_path: Optional[str] = None, state_dir: Optional[str] = None) -> None:
        self.data_agent = DataAgent()
        self.preprocess_agent = PreprocessAgent()
        self.model_agent = ModelAgent()
        self.signal_agent = SignalAgent()
        self.evaluator_agent = EvaluatorAgent(db_path=db_path) if db_path else EvaluatorAgent()

        self._agents = [
            self.data_agent,
            self.preprocess_agent,
            self.model_agent,
            self.signal_agent,
            self.evaluator_agent,
        ]

        # Persistence paths
        if state_dir:
            self._model_path = os.path.join(state_dir, "model.pkl")
            self._scaler_path = os.path.join(state_dir, "scaler.pkl")
        else:
            self._model_path = None
            self._scaler_path = None

    def load_state(self) -> bool:
        """Restore model and scaler from disk. Returns True if both loaded."""
        if not self._model_path or not self._scaler_path:
            return False
        m = self.model_agent.load(self._model_path)
        s = self.preprocess_agent.load(self._scaler_path)
        if m and s:
            logger.info(
                "State restored from disk. Model cycles: %d",
                self.model_agent._n_trained,
            )
        return m and s

    def save_state(self) -> None:
        """Persist model and scaler to disk."""
        if not self._model_path or not self._scaler_path:
            return
        self.model_agent.save(self._model_path)
        self.preprocess_agent.save(self._scaler_path)
        logger.debug("State saved to disk (cycles=%d)", self.model_agent._n_trained)

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

        # Auto-save every N cycles so we don't lose training progress
        if (
            self._model_path
            and state.model_ready
            and self.model_agent._n_trained % _SAVE_EVERY_N_CYCLES == 0
        ):
            self.save_state()

        return state
