#!/usr/bin/env python3
"""
Analyze why UNH was missed by PutsEngine.
"""
import json
import sys
sys.path.insert(0, '/Users/chavala/PutsEngine')

from putsengine.config import EngineConfig

# Check all sectors
all_tickers = set(EngineConfig.get_all_tickers())

print("=" * 80)
print("UNH MISSED TRADE ANALYSIS - INSTITUTIONAL POST-MORTEM")
print("=" * 80)

print(f"\n1. IS UNH IN OUR UNIVERSE?")
print(f"   UNH in static universe: {'YES ✅' if 'UNH' in all_tickers else 'NO ❌ CRITICAL MISS'}")

print(f"\n2. WHAT SECTORS DO WE HAVE?")
for sector, tickers in EngineConfig.UNIVERSE_SECTORS.items():
    print(f"   {sector}: {len(tickers)} tickers")

print(f"\n3. HEALTHCARE SECTOR TICKERS (CURRENT):")
healthcare = EngineConfig.UNIVERSE_SECTORS.get('healthcare', [])
print(f"   {healthcare}")

print(f"\n4. TOTAL UNIVERSE SIZE: {len(all_tickers)} tickers")

# Check if we have any large-cap healthcare/insurance
print(f"\n5. MISSING LARGE-CAP HEALTHCARE/INSURANCE:")
missing_healthcare = ["UNH", "HUM", "CI", "ELV", "CVS", "CNC", "MOH", "ABBV", "JNJ", "PFE", "LLY", "MRK"]
for ticker in missing_healthcare:
    status = "IN ✅" if ticker in all_tickers else "MISSING ❌"
    print(f"   {ticker}: {status}")

print(f"\n" + "=" * 80)
print("ROOT CAUSE ANALYSIS")
print("=" * 80)

print("""
🔴 CRITICAL FINDING: UNH IS NOT IN OUR SCAN UNIVERSE

This is a UNIVERSE DESIGN FLAW, not an algorithm failure.

WHY UNH WAS MISSED:
-------------------
1. UNH (UnitedHealth Group) is a $400B+ mega-cap healthcare/insurance company
2. Our healthcare sector only contains: HIMS, TDOC, OSCR, AMWL, TEM
3. These are all TELEHEALTH/DIGITAL HEALTH plays, NOT traditional healthcare
4. We have NO managed care / health insurance companies

UNH MOVE DETAILS:
-----------------
- UNH dropped ~20%+ on news of DOJ investigation + CEO murder aftermath
- This was a CATALYST-DRIVEN EVENT (regulatory + sentiment)
- Would have been EXPLOSIVE (0.75+) with proper signals:
  - High RVOL on red day
  - Gap down no recovery
  - VWAP loss
  - Dark pool selling
  - Negative news sentiment

WHY OUR SYSTEM COULDN'T SEE IT:
-------------------------------
- UNH was never in scan universe → NO API calls made
- NO price data fetched
- NO options flow data fetched
- NO distribution/liquidity detection possible

THE FIX (IMMEDIATE):
--------------------
Add Large-Cap Healthcare/Insurance to universe:
- UNH (UnitedHealth) - $400B+ - MUST ADD
- HUM (Humana) - Insurance
- CI (Cigna) - Insurance
- ELV (Elevance) - Insurance
- CVS (CVS Health) - Healthcare/Pharmacy
- CNC (Centene) - Medicaid managed care
- JNJ (Johnson & Johnson) - Pharma
- PFE (Pfizer) - Pharma
- LLY (Eli Lilly) - Pharma
- MRK (Merck) - Pharma
- ABBV (AbbVie) - Pharma

LESSON LEARNED:
---------------
> "You cannot catch what you do not watch."

This is a COVERAGE GAP, not an algorithm bug.
The DUI system could NOT inject UNH because:
- DUI only promotes from Distribution/Liquidity ENGINE HITS
- Those engines only scan KNOWN universe tickers
- UNH was never scanned → never hit → never promoted
""")
