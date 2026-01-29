"""
PutsEngine Email Reporter

Sends daily email reports with best PUT picks at 3 PM EST.

Target: Candidates most likely to return 1x-5x (100% to 500%)

SELECTION CRITERIA (Institutional Grade):
1. Score >= 0.35 (CLASS B or higher)
2. Multiple distribution/liquidity signals
3. Price range optimal for options ($10-$500)
4. Expected move -5% to -15% 

EMAIL CONTENT:
- Top 5 picks across all engines
- Strike, expiry, entry price range
- Signal breakdown
- Risk/reward analysis
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import json
import os

import pytz
from loguru import logger


# Email configuration - Set these as environment variables
EMAIL_SENDER = os.environ.get("PUTSENGINE_EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("PUTSENGINE_EMAIL_PASSWORD", "")  # App password for Gmail
EMAIL_RECIPIENT = os.environ.get("PUTSENGINE_EMAIL_RECIPIENT", "")
SMTP_SERVER = os.environ.get("PUTSENGINE_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("PUTSENGINE_SMTP_PORT", "587"))


def get_next_friday(from_date: date = None) -> date:
    """Get the next Friday expiry date."""
    if from_date is None:
        from_date = date.today()
    days_until_friday = (4 - from_date.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    return from_date + timedelta(days=days_until_friday)


def calculate_strike(price: float) -> float:
    """Calculate optimal 10% OTM strike for puts."""
    if price <= 0:
        return 0
    
    raw_strike = price * 0.90  # 10% OTM
    
    # Round to standard increments
    if price >= 200:
        return round(raw_strike / 5) * 5
    elif price >= 50:
        return round(raw_strike / 2.5) * 2.5
    elif price >= 10:
        return round(raw_strike)
    else:
        return round(raw_strike * 2) / 2


def estimate_return_potential(score: float, signals: List[str]) -> str:
    """
    Estimate return potential based on score and signals.
    
    Conservative estimates for institutional-grade picks:
    - Score 0.68+: 2x-5x potential (CLASS A)
    - Score 0.50-0.67: 1.5x-3x potential (STRONG)
    - Score 0.35-0.49: 1x-2x potential (CLASS B)
    """
    high_conviction_signals = [
        "high_rvol_red_day", "failed_breakout", "gap_down_no_recovery",
        "repeated_sell_blocks", "multi_day_weakness"
    ]
    
    signal_count = sum(1 for s in signals if s in high_conviction_signals)
    
    if score >= 0.68:
        if signal_count >= 3:
            return "3x-5x (HIGH CONVICTION)"
        else:
            return "2x-4x (CLASS A)"
    elif score >= 0.50:
        if signal_count >= 2:
            return "2x-3x (STRONG)"
        else:
            return "1.5x-2.5x (MODERATE)"
    elif score >= 0.35:
        if signal_count >= 2:
            return "1.5x-2x (CLASS B)"
        else:
            return "1x-1.5x (SPECULATIVE)"
    else:
        return "< 1x (MONITOR ONLY)"


def select_best_picks(scan_results: Dict, max_picks: int = 5) -> List[Dict]:
    """
    Select the best picks across all 3 engines.
    
    Criteria:
    - Score >= 0.35 (CLASS B minimum)
    - Price between $10 and $500 (optimal for options)
    - Multiple signals (2+)
    - Prioritize: Distribution > Gamma > Liquidity
    """
    all_candidates = []
    
    # Collect from all engines with engine tag
    for engine, candidates in [
        ("GAMMA DRAIN", scan_results.get("gamma_drain", [])),
        ("DISTRIBUTION", scan_results.get("distribution", [])),
        ("LIQUIDITY", scan_results.get("liquidity", []))
    ]:
        for c in candidates:
            c["engine"] = engine
            all_candidates.append(c)
    
    # Filter criteria
    filtered = []
    for c in all_candidates:
        score = c.get("score", 0)
        price = c.get("current_price", 0) or c.get("close", 0)
        signals = c.get("signals", [])
        
        # Must meet minimum criteria
        if score < 0.35:
            continue
        if price < 10 or price > 500:
            continue
        if len(signals) < 1:
            continue
        
        # Add calculated fields
        c["price"] = price
        c["strike"] = calculate_strike(price)
        c["return_potential"] = estimate_return_potential(score, signals)
        c["signal_count"] = len(signals)
        
        filtered.append(c)
    
    # Sort by composite ranking:
    # 1. Score (higher better)
    # 2. Signal count (more signals = more conviction)
    # 3. Engine priority (Distribution > Gamma > Liquidity)
    engine_priority = {"DISTRIBUTION": 3, "GAMMA DRAIN": 2, "LIQUIDITY": 1}
    
    filtered.sort(
        key=lambda x: (
            x.get("score", 0),
            x.get("signal_count", 0),
            engine_priority.get(x.get("engine", ""), 0)
        ),
        reverse=True
    )
    
    return filtered[:max_picks]


def format_email_html(picks: List[Dict], scan_time: str, market_regime: str) -> str:
    """Format the email as HTML for better readability."""
    
    est = pytz.timezone('US/Eastern')
    now = datetime.now(est)
    
    # Get next Friday for expiry
    next_friday = get_next_friday()
    expiry_str = next_friday.strftime("%b %d")
    dte = (next_friday - date.today()).days
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
            h1 {{ color: #ff6b6b; }}
            h2 {{ color: #4ecdc4; border-bottom: 2px solid #4ecdc4; padding-bottom: 10px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
            .header h1 {{ color: white; margin: 0; }}
            .header p {{ color: #ddd; margin: 5px 0 0 0; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
            th {{ background: #2d2d44; color: #4ecdc4; padding: 12px; text-align: left; }}
            td {{ padding: 12px; border-bottom: 1px solid #333; }}
            tr:hover {{ background: #2d2d44; }}
            .score-high {{ color: #4ecdc4; font-weight: bold; }}
            .score-medium {{ color: #ffd93d; }}
            .return-high {{ color: #6bcb77; font-weight: bold; }}
            .signal-badge {{ background: #764ba2; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; margin: 2px; display: inline-block; }}
            .engine-badge {{ background: #ff6b6b; color: white; padding: 4px 10px; border-radius: 4px; font-size: 0.85em; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #333; color: #888; font-size: 0.9em; }}
            .warning {{ background: #ff6b6b22; border-left: 4px solid #ff6b6b; padding: 10px 15px; margin: 20px 0; }}
            .tip {{ background: #4ecdc422; border-left: 4px solid #4ecdc4; padding: 10px 15px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏛️ PUTSENGINE DAILY REPORT</h1>
            <p>Scan Time: {now.strftime('%B %d, %Y at %I:%M %p ET')}</p>
            <p>Market Regime: {market_regime.upper()}</p>
        </div>
        
        <h2>🎯 TOP {len(picks)} PUT CANDIDATES (1x-5x Potential)</h2>
        
        <div class="tip">
            <strong>💡 Expiry:</strong> {expiry_str} ({dte} DTE) | 
            <strong>Strategy:</strong> Buy slightly OTM puts, target 1x-5x return
        </div>
    """
    
    if picks:
        html += """
        <table>
            <tr>
                <th>Symbol</th>
                <th>Engine</th>
                <th>Score</th>
                <th>Price</th>
                <th>Strike</th>
                <th>Est. Premium</th>
                <th>Return Potential</th>
                <th>Signals</th>
            </tr>
        """
        
        for i, pick in enumerate(picks, 1):
            symbol = pick.get("symbol", "N/A")
            engine = pick.get("engine", "N/A")
            score = pick.get("score", 0)
            price = pick.get("price", 0)
            strike = pick.get("strike", 0)
            signals = pick.get("signals", [])
            return_potential = pick.get("return_potential", "N/A")
            
            # Estimate premium (1.5% to 3% of stock price)
            premium_low = price * 0.015
            premium_high = price * 0.03
            
            # Format signals as badges
            signal_badges = " ".join([f'<span class="signal-badge">{s}</span>' for s in signals[:3]])
            
            # Score styling
            score_class = "score-high" if score >= 0.50 else "score-medium"
            
            html += f"""
            <tr>
                <td><strong>{symbol}</strong></td>
                <td><span class="engine-badge">{engine}</span></td>
                <td class="{score_class}">{score:.2f}</td>
                <td>${price:.2f}</td>
                <td>${strike:.0f} P</td>
                <td>${premium_low:.2f} - ${premium_high:.2f}</td>
                <td class="return-high">{return_potential}</td>
                <td>{signal_badges}</td>
            </tr>
            """
        
        html += "</table>"
    else:
        html += """
        <div class="warning">
            <strong>⚠️ No high-conviction picks today.</strong><br>
            All candidates below the 0.35 score threshold or outside optimal price range.
            This is normal - quality over quantity.
        </div>
        """
    
    html += f"""
        <div class="warning">
            <strong>⚠️ RISK DISCLAIMER:</strong><br>
            Options trading involves substantial risk. These are algorithmic signals, not financial advice.
            Never risk more than 2% of your account per trade. Past performance does not guarantee future results.
        </div>
        
        <div class="footer">
            <p>📊 <strong>PutsEngine</strong> - Institutional-Grade PUT Detection</p>
            <p>Scan completed: {scan_time}</p>
            <p>Tickers scanned: 253 | Engines: Gamma Drain, Distribution Trap, Liquidity Vacuum</p>
        </div>
    </body>
    </html>
    """
    
    return html


def format_email_text(picks: List[Dict], scan_time: str, market_regime: str) -> str:
    """Format the email as plain text fallback."""
    
    est = pytz.timezone('US/Eastern')
    now = datetime.now(est)
    next_friday = get_next_friday()
    
    text = f"""
🏛️ PUTSENGINE DAILY REPORT
========================================
Scan Time: {now.strftime('%B %d, %Y at %I:%M %p ET')}
Market Regime: {market_regime.upper()}
Expiry Target: {next_friday.strftime('%b %d')}
========================================

🎯 TOP {len(picks)} PUT CANDIDATES (1x-5x Potential)
----------------------------------------

"""
    
    if picks:
        for i, pick in enumerate(picks, 1):
            symbol = pick.get("symbol", "N/A")
            engine = pick.get("engine", "N/A")
            score = pick.get("score", 0)
            price = pick.get("price", 0)
            strike = pick.get("strike", 0)
            signals = pick.get("signals", [])
            return_potential = pick.get("return_potential", "N/A")
            
            premium_low = price * 0.015
            premium_high = price * 0.03
            
            text += f"""
#{i} {symbol} ({engine})
   Score: {score:.2f}
   Price: ${price:.2f}
   Strike: ${strike:.0f} P
   Est. Premium: ${premium_low:.2f} - ${premium_high:.2f}
   Return Potential: {return_potential}
   Signals: {', '.join(signals[:3])}
"""
    else:
        text += """
⚠️ No high-conviction picks today.
All candidates below threshold or outside optimal price range.
"""
    
    text += f"""
----------------------------------------
⚠️ DISCLAIMER: Options trading involves substantial risk.
These are algorithmic signals, not financial advice.
Never risk more than 2% per trade.

Scan completed: {scan_time}
PutsEngine - Institutional-Grade PUT Detection
"""
    
    return text


def send_email_report(scan_results: Dict) -> bool:
    """
    Send email report with best picks.
    
    Args:
        scan_results: Results from scheduled scan
        
    Returns:
        True if email sent successfully, False otherwise
    """
    # Check email configuration
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
        logger.warning("Email not configured. Set PUTSENGINE_EMAIL_SENDER, PUTSENGINE_EMAIL_PASSWORD, PUTSENGINE_EMAIL_RECIPIENT environment variables.")
        return False
    
    try:
        # Select best picks
        best_picks = select_best_picks(scan_results, max_picks=5)
        
        scan_time = scan_results.get("last_scan", datetime.now().isoformat())
        market_regime = scan_results.get("market_regime", "unknown")
        
        # Create email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🏛️ PutsEngine Daily Report - {len(best_picks)} Picks - {date.today().strftime('%b %d')}"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT
        
        # Attach both text and HTML versions
        text_content = format_email_text(best_picks, scan_time, market_regime)
        html_content = format_email_html(best_picks, scan_time, market_regime)
        
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))
        
        # Send email
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        
        logger.info(f"Email report sent successfully to {EMAIL_RECIPIENT}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email report: {e}")
        return False


def save_report_to_file(scan_results: Dict) -> str:
    """
    Save the report to a file (always works, even without email).
    
    Returns:
        Path to the saved report
    """
    est = pytz.timezone('US/Eastern')
    now = datetime.now(est)
    
    best_picks = select_best_picks(scan_results, max_picks=5)
    scan_time = scan_results.get("last_scan", now.isoformat())
    market_regime = scan_results.get("market_regime", "unknown")
    
    # Save HTML report
    html_content = format_email_html(best_picks, scan_time, market_regime)
    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)
    
    report_path = report_dir / f"daily_report_{now.strftime('%Y%m%d_%H%M')}.html"
    with open(report_path, "w") as f:
        f.write(html_content)
    
    logger.info(f"Report saved to {report_path}")
    
    # Also save JSON for programmatic access
    json_path = report_dir / f"daily_picks_{now.strftime('%Y%m%d_%H%M')}.json"
    with open(json_path, "w") as f:
        json.dump({
            "scan_time": scan_time,
            "market_regime": market_regime,
            "picks": best_picks
        }, f, indent=2, default=str)
    
    return str(report_path)


async def run_daily_report_scan():
    """
    Run the 3 PM daily scan and send email report.
    
    This is called by the scheduler at 3 PM EST.
    """
    from putsengine.scheduler import run_single_scan
    
    logger.info("=" * 60)
    logger.info("DAILY REPORT SCAN (3 PM EST)")
    logger.info("=" * 60)
    
    try:
        # Run fresh scan
        results = await run_single_scan("daily_report")
        
        # Save report to file (always)
        report_path = save_report_to_file(results)
        logger.info(f"Report saved: {report_path}")
        
        # Send email (if configured)
        email_sent = send_email_report(results)
        
        if email_sent:
            logger.info("Daily report email sent successfully")
        else:
            logger.warning("Email not sent - check configuration")
        
        return results
        
    except Exception as e:
        logger.error(f"Daily report scan failed: {e}")
        raise
