#!/usr/bin/env python3
"""
PutsEngine Runner Script.

Usage:
    python run.py                    # Run daily pipeline (dry run)
    python run.py --live             # Run daily pipeline (live trading)
    python run.py analyze AAPL       # Analyze single symbol
    python run.py regime             # Check market regime
"""

from putsengine.cli import main

if __name__ == "__main__":
    main()
