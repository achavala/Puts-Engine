"""
Trade Attribution Module
========================
Post-trade attribution system for tracking outcomes by structure.
Mandatory for capital scaling - proves Vega Gate effectiveness.
"""

from .trade_attribution import (
    TradeRecord,
    TradeOutcome,
    TradeStructure,
    record_trade_entry,
    record_trade_exit,
    load_attribution_history,
    calculate_attribution_summary,
    get_vega_gate_effectiveness_report,
    get_open_trades,
    get_recent_trades,
)

__all__ = [
    'TradeRecord',
    'TradeOutcome',
    'TradeStructure',
    'record_trade_entry',
    'record_trade_exit',
    'load_attribution_history',
    'calculate_attribution_summary',
    'get_vega_gate_effectiveness_report',
    'get_open_trades',
    'get_recent_trades',
]
