"""
PutsEngine - Institutional PUT Options Trading Engine

A sophisticated algorithm for identifying -5% to -20% moves 1-10 days ahead
with asymmetric put P&L, based on dealer microstructure and options flow analysis.
"""

__version__ = "1.0.0"
__author__ = "TradeNova"

from putsengine.config import Settings
from putsengine.engine import PutsEngine

__all__ = ["PutsEngine", "Settings", "__version__"]
