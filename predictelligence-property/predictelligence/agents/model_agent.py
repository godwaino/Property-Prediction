from __future__ import annotations

from sklearn.linear_model import SGDRegressor

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class ModelAgent(BaseAgent):
    def __init__(self):
        super().__init__("ModelAgent")
        self.model = SGDRegressor(learning_rate="adaptive", eta0=0.01, max_iter=1, warm_start=True)
        self.n_trained = 0

    def run(self, state: PipelineState) -> PipelineState:
        X = state.features
        y = [state.target]
        self.model.partial_fit(X, y)
        self.n_trained += 1
        state.cycle = self.n_trained
        state.model_ready = self.n_trained >= 3

        if state.model_ready:
            pred = float(self.model.predict(X)[0])
        else:
            pred = state.current_valuation
        state.prediction = pred

        cv = max(state.current_valuation, 1.0)
        if pred > cv * 1.005:
            state.direction = "UP"
        elif pred < cv * 0.995:
            state.direction = "DOWN"
        else:
            state.direction = "SIDEWAYS"

        state.predicted_change_pct = ((pred - cv) / cv) * 100
        state.confidence = min(70 + self.n_trained * 2, 95)
        state.error = abs(state.target - pred)
        return state
