from __future__ import annotations

from typing import Dict, Optional

from .types import MarketStructure


class StrategyTradeLevelsMixin:
    def _build_trade_levels(
        self,
        side: str,
        signal_type: str,
        entry: float,
        atr_v: float,
        structure: MarketStructure,
        extra: Optional[Dict],
    ) -> tuple[float, float]:
        support_ref = self._support_reference(structure)
        resistance_ref = self._resistance_reference(structure)
        stop_buffer = atr_v * self.params.sr_stop_buffer_atr
        target_buffer = atr_v * self.params.sr_target_buffer_atr
        rr_multiplier = self.params.risk_reward
        if signal_type == "STRUCTURE":
            rr_multiplier = max(self.params.risk_reward, self.params.structure_risk_reward)
        elif signal_type == "PULLBACK":
            rr_multiplier = max(self.params.risk_reward, self.params.pullback_risk_reward)
        elif signal_type == "BREAKDOWN":
            rr_multiplier = max(self.params.risk_reward, self.params.breakdown_risk_reward)
        elif signal_type == "CONTINUATION":
            rr_multiplier = max(self.params.risk_reward, self.params.continuation_risk_reward)

        sl_distance = atr_v * self.params.atr_multiplier
        if side == "LONG":
            stop_loss = entry - sl_distance
            if signal_type == "STRUCTURE":
                structure_stop_limit = atr_v * self.params.structure_stop_max_atr
                swing_buffer = max(stop_buffer, atr_v * self.params.structure_stop_buffer_atr)
                pattern = str((extra or {}).get("pattern") or "")
                candidates = [stop_loss]
                break_level = (extra or {}).get("break_level")
                for candidate in (
                    (float(break_level) - swing_buffer) if break_level is not None and float(break_level) < entry else None,
                    (support_ref - stop_buffer) if support_ref is not None and support_ref < entry else None,
                    (structure.recent_swing_low - swing_buffer) if structure.recent_swing_low is not None and structure.recent_swing_low < entry else None,
                ):
                    if candidate is not None and 0 < entry - candidate <= structure_stop_limit:
                        candidates.append(candidate)
                stop_loss = min(candidates)
                sl_distance = max(entry - stop_loss, atr_v * (0.6 if "break" in pattern else 0.75))
            take_profit = entry + (sl_distance * rr_multiplier)
            if resistance_ref is not None and resistance_ref > entry:
                capped_tp = resistance_ref - target_buffer
                target_distance = take_profit - entry
                should_cap = signal_type not in ("STRUCTURE", "PULLBACK", "BREAKDOWN", "CONTINUATION") or (capped_tp - entry) <= (target_distance * 0.5)
                if capped_tp > entry and should_cap:
                    take_profit = min(take_profit, capped_tp)
            return (stop_loss, take_profit)

        stop_loss = entry + sl_distance
        if signal_type == "STRUCTURE":
            structure_stop_limit = atr_v * self.params.structure_stop_max_atr
            swing_buffer = max(stop_buffer, atr_v * self.params.structure_stop_buffer_atr)
            pattern = str((extra or {}).get("pattern") or "")
            candidates = [stop_loss]
            break_level = (extra or {}).get("break_level")
            for candidate in (
                (float(break_level) + swing_buffer) if break_level is not None and float(break_level) > entry else None,
                (structure.recent_swing_high + swing_buffer) if structure.recent_swing_high is not None and structure.recent_swing_high > entry else None,
                (resistance_ref + stop_buffer) if resistance_ref is not None and resistance_ref > entry else None,
            ):
                if candidate is not None and 0 < candidate - entry <= structure_stop_limit:
                    candidates.append(candidate)
            stop_loss = max(candidates)
            sl_distance = max(stop_loss - entry, atr_v * (0.6 if "break" in pattern else 0.75))
        take_profit = entry - (sl_distance * rr_multiplier)
        if support_ref is not None and support_ref < entry:
            capped_tp = support_ref + target_buffer
            target_distance = entry - take_profit
            should_cap = signal_type not in ("STRUCTURE", "PULLBACK", "BREAKDOWN", "CONTINUATION") or (entry - capped_tp) <= (target_distance * 0.5)
            if capped_tp < entry and should_cap:
                take_profit = max(take_profit, capped_tp)
        return (stop_loss, take_profit)

