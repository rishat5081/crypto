from __future__ import annotations

from .bootstrap import TraderBootstrapMixin
from .execution import TraderExecutionMixin
from .loop import TraderLoopMixin
from .management import TraderManagementMixin
from .market_data import TraderMarketDataMixin
from .models import CandidateSignal, ManagedTrade
from .runtime import TraderRuntimeMixin
from .signals import TraderSignalMixin


class LiveAdaptivePaperTrader(
    TraderBootstrapMixin,
    TraderRuntimeMixin,
    TraderMarketDataMixin,
    TraderSignalMixin,
    TraderManagementMixin,
    TraderExecutionMixin,
    TraderLoopMixin,
):
    pass


__all__ = ["CandidateSignal", "LiveAdaptivePaperTrader", "ManagedTrade"]
