from __future__ import annotations

import copy
from typing import Dict, Optional

from .contracts import StrategyDecision, StrategyRequest
from .engine import StrategyEngine
from .pipeline import StructureStrategyPipeline


class StrategyService:
    def __init__(self, strategy_name: str, pipeline: StructureStrategyPipeline):
        self.strategy_name = strategy_name
        self.pipeline = pipeline

    @classmethod
    def from_config(cls, payload: Dict) -> "StrategyService":
        strategy_name = str(payload.get("name", "structure")).strip().lower() or "structure"
        if strategy_name != "structure":
            raise ValueError(f"Unsupported strategy service '{strategy_name}'")
        engine = StrategyEngine.from_dict(copy.deepcopy(payload))
        return cls(strategy_name=strategy_name, pipeline=StructureStrategyPipeline(engine))

    @property
    def engine(self) -> StrategyEngine:
        return self.pipeline.engine

    @property
    def params(self):
        return self.engine.params

    def evaluate_request(self, request: StrategyRequest) -> StrategyDecision:
        return self.pipeline.run(request)

    def evaluate(
        self,
        symbol: str,
        timeframe: str,
        candles,
        market,
        diagnostics: Optional[Dict[str, int]] = None,
    ):
        decision = self.evaluate_request(
            StrategyRequest(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles,
                market=market,
                diagnostics=diagnostics,
            )
        )
        return decision.signal

    def adaptive_tune_after_trade(self, trade_result: str) -> None:
        self.engine.adaptive_tune_after_trade(trade_result)
