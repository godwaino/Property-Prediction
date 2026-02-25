from __future__ import annotations

from predictelligence.agents.data_agent import DataAgent
from predictelligence.agents.evaluator_agent import EvaluatorAgent
from predictelligence.agents.model_agent import ModelAgent
from predictelligence.agents.preprocess_agent import PreprocessAgent
from predictelligence.agents.signal_agent import SignalAgent
from predictelligence.pipeline_state import PipelineState


class PropertyPipeline:
    def __init__(self):
        self.agents = [
            DataAgent(),
            PreprocessAgent(),
            ModelAgent(),
            SignalAgent(),
            EvaluatorAgent(),
        ]

    def run(self, postcode, current_valuation, comparable_average, user_type) -> PipelineState:
        state = PipelineState(
            postcode=postcode.replace(" ", "").upper(),
            current_valuation=float(current_valuation),
            comparable_average=float(comparable_average),
            user_type=user_type,
        )
        for agent in self.agents:
            state = agent.run(state)
        return state
