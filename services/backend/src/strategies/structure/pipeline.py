from __future__ import annotations

from typing import Dict, Optional

from .contracts import StrategyDecision, StrategyRequest
from .engine import StrategyEngine


class StructureStrategyPipeline:
    def __init__(self, engine: StrategyEngine):
        self.engine = engine

    def run(self, request: StrategyRequest) -> StrategyDecision:
        diagnostics: Dict[str, int] = request.diagnostics if request.diagnostics is not None else {}
        signal = self.engine.evaluate(
            request.symbol,
            request.timeframe,
            request.candles,
            request.market,
            diagnostics=diagnostics,
        )
        rejection_reason: Optional[str] = None
        if signal is None and diagnostics:
            rejection_reason = max(diagnostics.items(), key=lambda item: item[1])[0]
        return StrategyDecision(
            strategy_name="structure",
            should_open_trade=signal is not None,
            signal=signal,
            diagnostics=diagnostics,
            rejection_reason=rejection_reason,
        )
