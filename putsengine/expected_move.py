"""
Expected Move Calculator - Calculate implied move from ATM straddle

PURPOSE: For earnings plays, calculate the expected move from the ATM straddle price.
This is what market makers use to price earnings risk.

INSTITUTIONAL LOGIC:
- ATM straddle price = market's expectation of move magnitude
- Straddle = ATM Call + ATM Put
- Expected move % = Straddle Price / Stock Price
- Downside target = Stock Price * (1 - Expected Move)
- Upside target = Stock Price * (1 + Expected Move)

For PUT plays:
- Use downside target to select strike
- Add 10-20% buffer for aggressive plays
- Use 50% of expected move for conservative plays
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Tuple
from loguru import logger
from dataclasses import dataclass


@dataclass
class ExpectedMove:
    """Expected move calculation from straddle."""
    symbol: str
    stock_price: float
    atm_call_price: float
    atm_put_price: float
    straddle_price: float
    expected_move_pct: float
    expected_move_dollars: float
    downside_target: float
    upside_target: float
    recommended_put_strike_aggressive: float
    recommended_put_strike_moderate: float
    recommended_put_strike_conservative: float
    calculation_time: str


class ExpectedMoveCalculator:
    """
    Calculate expected move from ATM straddle.
    
    This is the institutional method for pricing earnings risk.
    """
    
    def __init__(self, polygon_client, alpaca_client):
        self.polygon = polygon_client
        self.alpaca = alpaca_client
    
    async def get_atm_strike(self, symbol: str, expiration: date) -> Optional[float]:
        """Get ATM strike for given expiration."""
        try:
            # Get current price
            bars = await self.alpaca.get_bars(symbol, "1Day", limit=1)
            if not bars:
                return None
            
            current_price = bars[-1].close
            
            # Round to nearest $5 for stocks > $100, $2.5 for $25-100, $1 for < $25
            if current_price >= 100:
                increment = 5
            elif current_price >= 25:
                increment = 2.5
            else:
                increment = 1
            
            atm_strike = round(current_price / increment) * increment
            return atm_strike
            
        except Exception as e:
            logger.error(f"Failed to get ATM strike for {symbol}: {e}")
            return None
    
    async def get_atm_options(self, symbol: str, expiration: date) -> Tuple[Optional[float], Optional[float]]:
        """
        Get ATM call and put prices.
        
        Returns:
            Tuple of (call_price, put_price) or (None, None) if unavailable
        """
        try:
            atm_strike = await self.get_atm_strike(symbol, expiration)
            if not atm_strike:
                return None, None
            
            # Get options chain from Polygon
            chain = await self.polygon.get_options_chain(
                symbol=symbol,
                expiration=expiration
            )
            
            if not chain:
                return None, None
            
            # Find ATM call and put
            atm_call = None
            atm_put = None
            
            for contract in chain:
                if contract.strike == atm_strike:
                    if contract.option_type == "call":
                        atm_call = contract
                    elif contract.option_type == "put":
                        atm_put = contract
            
            if not atm_call or not atm_put:
                return None, None
            
            # Use mid price
            call_price = atm_call.mid_price if hasattr(atm_call, 'mid_price') else (atm_call.bid + atm_call.ask) / 2
            put_price = atm_put.mid_price if hasattr(atm_put, 'mid_price') else (atm_put.bid + atm_put.ask) / 2
            
            return call_price, put_price
            
        except Exception as e:
            logger.debug(f"Failed to get ATM options for {symbol}: {e}")
            return None, None
    
    async def calculate_expected_move(
        self,
        symbol: str,
        expiration: date
    ) -> Optional[ExpectedMove]:
        """
        Calculate expected move from ATM straddle.
        
        Args:
            symbol: Stock ticker
            expiration: Options expiration date
            
        Returns:
            ExpectedMove object or None if calculation fails
        """
        try:
            # Get current stock price
            bars = await self.alpaca.get_bars(symbol, "1Day", limit=1)
            if not bars:
                return None
            
            stock_price = bars[-1].close
            
            # Get ATM call and put prices
            call_price, put_price = await self.get_atm_options(symbol, expiration)
            
            if call_price is None or put_price is None:
                logger.debug(f"Could not get ATM options for {symbol}")
                return None
            
            # Calculate straddle
            straddle_price = call_price + put_price
            
            # Calculate expected move
            expected_move_pct = straddle_price / stock_price
            expected_move_dollars = stock_price * expected_move_pct
            
            # Calculate targets
            downside_target = stock_price * (1 - expected_move_pct)
            upside_target = stock_price * (1 + expected_move_pct)
            
            # Calculate recommended strikes
            # Aggressive: 1.2x expected move (further OTM)
            # Moderate: 1.0x expected move (at expected move)
            # Conservative: 0.7x expected move (closer to ATM)
            
            aggressive_distance = expected_move_dollars * 1.2
            moderate_distance = expected_move_dollars * 1.0
            conservative_distance = expected_move_dollars * 0.7
            
            # Round strikes
            if stock_price >= 100:
                increment = 5
            elif stock_price >= 25:
                increment = 2.5
            else:
                increment = 1
            
            aggressive_strike = round((stock_price - aggressive_distance) / increment) * increment
            moderate_strike = round((stock_price - moderate_distance) / increment) * increment
            conservative_strike = round((stock_price - conservative_distance) / increment) * increment
            
            return ExpectedMove(
                symbol=symbol,
                stock_price=stock_price,
                atm_call_price=call_price,
                atm_put_price=put_price,
                straddle_price=straddle_price,
                expected_move_pct=expected_move_pct,
                expected_move_dollars=expected_move_dollars,
                downside_target=downside_target,
                upside_target=upside_target,
                recommended_put_strike_aggressive=aggressive_strike,
                recommended_put_strike_moderate=moderate_strike,
                recommended_put_strike_conservative=conservative_strike,
                calculation_time=datetime.now().isoformat()
            )
            
        except Exception as e:
            logger.error(f"Failed to calculate expected move for {symbol}: {e}")
            return None


async def get_expected_move_for_earnings(
    symbol: str,
    polygon_client,
    alpaca_client,
    earnings_date: date
) -> Optional[ExpectedMove]:
    """
    Get expected move for a stock with earnings.
    
    Uses the nearest Friday expiration after earnings date.
    """
    # Get next Friday after earnings
    days_until_friday = (4 - earnings_date.weekday() + 7) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    expiration = earnings_date + timedelta(days=days_until_friday)
    
    calculator = ExpectedMoveCalculator(polygon_client, alpaca_client)
    return await calculator.calculate_expected_move(symbol, expiration)
