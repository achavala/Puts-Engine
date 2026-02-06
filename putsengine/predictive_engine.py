"""
🎯 PREDICTIVE ENGINE v3 - TRULY PREDICTIVE (Not Reactive)
==========================================================
Goal: 10 stocks that WILL crash in next 1-2 days
Target: 8/10 success rate

CRITICAL DISTINCTION:
- REACTIVE signals (useless): exhaustion, below_prior_low, pump_reversal
  These trigger AFTER the crash happens!
  
- PREDICTIVE signals (valuable): IPI, dark pool, options flow
  These detect institutional selling BEFORE price drops!

THIS ENGINE USES ONLY PREDICTIVE DATA:
1. EWS IPI scores (Institutional Pressure Index from dark pool + options flow)
2. NOT Gamma Drain (reactive price patterns)
3. NOT Distribution/Liquidity engines (reactive)

The IPI score measures:
- Dark pool selling activity
- Put flow accumulation  
- Institutional hedging
All of which happen BEFORE the price drops!
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict


@dataclass
class PredictiveCandidate:
    """A stock with PREDICTIVE crash signals"""
    symbol: str
    ipi_score: float  # Institutional Pressure Index (0-1)
    confidence: str  # VERY HIGH, HIGH, MEDIUM, LOW
    expected_drop: str
    timeframe: str
    
    # Predictive components
    dark_pool_score: float = 0.0
    options_flow_score: float = 0.0
    iv_score: float = 0.0
    
    # Metadata
    sector: str = "unknown"
    footprint_count: int = 0
    signals: List[str] = field(default_factory=list)
    current_price: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "combined_score": self.ipi_score,
            "confidence": self.confidence,
            "expected_drop": self.expected_drop,
            "timeframe": self.timeframe,
            "scores": {
                "ipi": self.ipi_score,
                "dark_pool": self.dark_pool_score,
                "options_flow": self.options_flow_score,
                "iv": self.iv_score
            },
            "engines_detected": ["EWS IPI"],
            "engine_count": 1,
            "signals": self.signals,
            "sector": self.sector,
            "footprint_count": self.footprint_count,
            "current_price": self.current_price,
            "suggested_strike": "",
            "suggested_expiry": "",
            "potential_mult": "3x-10x"
        }


class PredictiveEngine:
    """
    TRULY PREDICTIVE Engine v3
    
    Uses ONLY predictive signals:
    - EWS IPI (Institutional Pressure Index)
    - Dark pool activity
    - Options flow
    
    Does NOT use reactive signals:
    - Price patterns (exhaustion, breakdown)
    - Volume patterns (high_vol_red)
    - Technical signals (below_prior_low)
    
    IPI Score Interpretation:
    - > 0.9: EXTREME institutional selling (crash imminent)
    - > 0.7: HIGH institutional selling (high probability crash in 1-2 days)
    - > 0.5: MODERATE selling (watch closely)
    - < 0.5: LOW selling (not a crash candidate)
    """
    
    # IPI thresholds
    THRESHOLDS = {
        "extreme": 0.85,     # Very high probability
        "high": 0.70,        # High probability
        "moderate": 0.55,    # Moderate probability
        "low": 0.40          # Low probability
    }
    
    def __init__(self, settings=None):
        self.settings = settings
        self.ews_data = {}
        self.ews_timestamp = None
        
    async def load_data(self):
        """Load EWS data (the only truly predictive source)"""
        ews_path = Path("early_warning_alerts.json")
        if ews_path.exists():
            with open(ews_path) as f:
                data = json.load(f)
                self.ews_data = data.get("alerts", {})
                self.ews_timestamp = data.get("timestamp", "Unknown")
                
    def _analyze_candidate(self, symbol: str, data: Dict) -> PredictiveCandidate:
        """Analyze a single candidate using ONLY predictive signals"""
        ipi = data.get('ipi', 0)
        
        # Determine confidence based on IPI
        if ipi >= self.THRESHOLDS["extreme"]:
            confidence = "VERY HIGH"
            expected_drop = "15-40%"
        elif ipi >= self.THRESHOLDS["high"]:
            confidence = "HIGH"
            expected_drop = "10-25%"
        elif ipi >= self.THRESHOLDS["moderate"]:
            confidence = "MEDIUM"
            expected_drop = "5-15%"
        else:
            confidence = "LOW"
            expected_drop = "0-10%"
            
        # Build signals list
        signals = []
        if ipi > 0.8:
            signals.append("EXTREME institutional pressure")
        elif ipi > 0.6:
            signals.append("HIGH institutional pressure")
            
        # Add dark pool info if available
        dark_pool = data.get('dark_pool_pct', 0)
        if dark_pool > 50:
            signals.append(f"Dark pool: {dark_pool:.0f}%")
            
        # Add options flow info
        put_call = data.get('put_call_ratio', 0)
        if put_call > 1.5:
            signals.append(f"Put/Call: {put_call:.1f}")
            
        # Add footprint info
        footprint = data.get('footprint_count', 0)
        if footprint > 3:
            signals.append(f"{footprint} footprints detected")
            
        return PredictiveCandidate(
            symbol=symbol,
            ipi_score=ipi,
            confidence=confidence,
            expected_drop=expected_drop,
            timeframe="1-2 days",
            dark_pool_score=dark_pool / 100 if dark_pool else 0,
            options_flow_score=min(1.0, put_call / 3) if put_call else 0,
            iv_score=data.get('iv_rank', 0),
            sector=data.get('sector', 'unknown'),
            footprint_count=footprint,
            signals=signals,
            current_price=data.get('price', 0)
        )
        
    async def get_predictions(self) -> List[PredictiveCandidate]:
        """
        Get TOP 10 PREDICTIVE crash candidates
        
        These are stocks with HIGH IPI (institutional selling)
        that HAVEN'T crashed yet but are likely to crash soon.
        """
        await self.load_data()
        
        predictions = []
        
        for symbol, data in self.ews_data.items():
            ipi = data.get('ipi', 0)
            
            # Only include stocks with meaningful IPI
            if ipi >= self.THRESHOLDS["low"]:
                candidate = self._analyze_candidate(symbol, data)
                predictions.append(candidate)
                
        # Sort by IPI score (highest first)
        predictions.sort(key=lambda x: x.ipi_score, reverse=True)
        
        # Return TOP 10
        return predictions[:10]
        
    async def run(self) -> Dict:
        """Run the predictive engine"""
        predictions = await self.get_predictions()
        
        # Count by confidence
        very_high = len([p for p in predictions if p.confidence == "VERY HIGH"])
        high = len([p for p in predictions if p.confidence == "HIGH"])
        medium = len([p for p in predictions if p.confidence == "MEDIUM"])
        
        # Get unique sectors
        sectors = list(set(p.sector for p in predictions if p.sector != "unknown"))
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "ews_timestamp": self.ews_timestamp,
            "engine_version": "v3_predictive",
            "methodology": "EWS IPI Only (Truly Predictive)",
            "note": "Uses ONLY predictive signals (IPI, dark pool, options flow). Does NOT use reactive price patterns.",
            "predictions": [p.to_dict() for p in predictions],
            "summary": {
                "total_candidates": len(predictions),
                "very_high_confidence": very_high,
                "high_confidence": high,
                "medium_confidence": medium,
                "bulletproof": very_high,  # For compatibility
                "sectors_represented": sectors,
                "data_sources": {
                    "ews_alerts_count": len(self.ews_data),
                    "gamma_drain_count": 0,  # Not used - reactive
                    "distribution_count": 0,  # Not used - reactive
                    "liquidity_count": 0      # Not used - reactive
                }
            }
        }
        
        # Save to file
        output_path = Path("logs/predictive_analysis.json")
        output_path.parent.mkdir(exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
            
        return result
        
    def format_result(self, result: Dict) -> str:
        """Format result for display"""
        lines = [
            "=" * 70,
            "🎯 PREDICTIVE ENGINE v3 - TRULY PREDICTIVE",
            "=" * 70,
            f"Methodology: {result.get('methodology', 'EWS IPI Only')}",
            f"EWS Timestamp: {result.get('ews_timestamp', 'Unknown')}",
            "",
            "⚠️ IMPORTANT: These stocks show institutional selling NOW",
            "   but haven't crashed yet. They are PREDICTED to drop.",
            "",
            "📊 TOP 10 PREDICTIVE CRASH CANDIDATES",
            "-" * 70
        ]
        
        for i, pred in enumerate(result['predictions'], 1):
            ipi = pred.get('combined_score', 0)
            conf = pred['confidence']
            
            # Confidence emoji
            if conf == "VERY HIGH":
                conf_emoji = "🔴🔴🔴"
            elif conf == "HIGH":
                conf_emoji = "🔴🔴"
            elif conf == "MEDIUM":
                conf_emoji = "🟡"
            else:
                conf_emoji = "⚪"
                
            lines.append(
                f"{i:2}. {conf_emoji} {pred['symbol']:5} | IPI: {ipi:.0%} | "
                f"Conf: {conf:10} | Drop: {pred['expected_drop']}"
            )
            
            # Show signals
            signals = pred.get('signals', [])[:2]
            if signals:
                lines.append(f"      └─ {', '.join(signals)}")
                
        lines.append("-" * 70)
        summary = result['summary']
        lines.append(
            f"Summary: {summary.get('very_high_confidence', 0)} VERY HIGH, "
            f"{summary.get('high_confidence', 0)} HIGH, "
            f"{summary.get('medium_confidence', 0)} MEDIUM confidence"
        )
        
        return "\n".join(lines)


async def run_predictive_analysis():
    """Run the predictive engine"""
    engine = PredictiveEngine()
    result = await engine.run()
    print(engine.format_result(result))
    return result


if __name__ == "__main__":
    asyncio.run(run_predictive_analysis())
