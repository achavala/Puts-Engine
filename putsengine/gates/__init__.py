"""
Trading Gates Module
====================
Institutional-grade trading gates from Architect-4 Final Report.
"""

from .trading_gates import TradingGates, DailyHardGateReport, BEARISH_KEYWORDS
from .vega_gate import (
    VegaGate, 
    VegaGateResult, 
    VegaDecision,
    apply_vega_gate,
    format_vega_gate_display
)

__all__ = [
    'TradingGates', 
    'DailyHardGateReport', 
    'BEARISH_KEYWORDS',
    'VegaGate',
    'VegaGateResult',
    'VegaDecision',
    'apply_vega_gate',
    'format_vega_gate_display',
]
