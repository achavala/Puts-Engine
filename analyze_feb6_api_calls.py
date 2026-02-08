#!/usr/bin/env python3
"""
Analyze API calls made on February 6, 2026 for each scheduled job.
Parses scheduler daemon log to extract API call counts per job type.
"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

def parse_scheduler_log(log_file: Path):
    """Parse scheduler log for Feb 6, 2026 and extract API call information."""
    
    jobs_api_calls = defaultdict(lambda: {
        'uw_calls': 0,
        'polygon_calls': 0,
        'alpaca_calls': 0,
        'finviz_calls': 0,
        'runs': 0,
        'tickers_scanned': 0,
        'times': []
    })
    
    current_job = None
    current_timestamp = None
    
    # Patterns to match
    job_patterns = {
        'Early Warning': r'Early Warning.*Scan|run_early_warning',
        'Market Direction': r'Market Direction|MARKETPULSE|run_market_direction',
        'Market Weather': r'Market Weather|run_market_weather',
        'Pre-Market Gap': r'Pre-Market Gap Scan|run_premarket_gap',
        'Zero-Hour Gap': r'Zero-Hour Gap|run_zero_hour',
        'Earnings Priority': r'Earnings Priority|run_earnings_priority',
        'Intraday Big Mover': r'Intraday Big Mover|run_intraday',
        'Pre-Earnings Flow': r'Pre-Earnings Flow|run_precatalyst',
        'Gamma Drain': r'Gamma Drain|run_gamma_drain',
        'Distribution': r'Distribution|run_distribution',
        'Liquidity': r'Liquidity|run_liquidity',
        'After-Hours': r'After-Hours|run_afterhours',
        'Pattern Scan': r'Pattern Scan|run_pattern',
        '48-Hour': r'48-Hour|run_48hour',
    }
    
    api_budget_pattern = r'API Budget Status: Daily: (\d+)/7500'
    uw_rate_limit_pattern = r'UW rate limit|UW API call|UW.*request'
    polygon_pattern = r'Polygon.*request|polygon.*call'
    alpaca_pattern = r'Alpaca.*request|alpaca.*call'
    finviz_pattern = r'FinViz.*request|finviz.*call'
    
    ticker_scan_pattern = r'Scanning (\d+) symbols?|scanned (\d+)'
    
    with open(log_file, 'r') as f:
        for line in f:
            if '2026-02-06' not in line:
                continue
            
            # Extract timestamp
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if timestamp_match:
                current_timestamp = timestamp_match.group(1)
            
            # Identify current job
            for job_name, pattern in job_patterns.items():
                if re.search(pattern, line, re.IGNORECASE):
                    current_job = job_name
                    if 'Complete' in line or 'Starting' in line or 'Running' in line:
                        jobs_api_calls[job_name]['runs'] += 1
                        if current_timestamp:
                            jobs_api_calls[job_name]['times'].append(current_timestamp)
                    break
            
            # Count API budget status (UW calls)
            if 'API Budget Status' in line:
                budget_match = re.search(api_budget_pattern, line)
                if budget_match:
                    # This is cumulative, so we'll track increments
                    pass
            
            # Count UW API calls
            if current_job and (uw_rate_limit_pattern in line.lower() or 'UW API' in line):
                jobs_api_calls[current_job]['uw_calls'] += 1
            
            # Count tickers scanned
            ticker_match = re.search(ticker_scan_pattern, line, re.IGNORECASE)
            if ticker_match and current_job:
                count = int(ticker_match.group(1) or ticker_match.group(2))
                jobs_api_calls[current_job]['tickers_scanned'] = max(
                    jobs_api_calls[current_job]['tickers_scanned'], count
                )
    
    return jobs_api_calls

def extract_api_budget_totals(log_file: Path):
    """Extract total UW API calls from budget status logs."""
    budget_logs = []
    with open(log_file, 'r') as f:
        for line in f:
            if '2026-02-06' in line and 'API Budget Status' in line:
                match = re.search(r'Daily: (\d+)/7500', line)
                if match:
                    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    timestamp = timestamp_match.group(1) if timestamp_match else 'Unknown'
                    budget_logs.append((timestamp, int(match.group(1))))
    
    # Get max (last) value
    if budget_logs:
        return max(budget_logs, key=lambda x: x[1])[1]
    return 0

def main():
    log_file = Path('logs/scheduler_daemon.log')
    
    if not log_file.exists():
        print(f"Error: {log_file} not found")
        return
    
    print("=" * 80)
    print("API CALL ANALYSIS FOR FEBRUARY 6, 2026")
    print("=" * 80)
    print()
    
    # Parse job-specific API calls
    jobs_api_calls = parse_scheduler_log(log_file)
    
    # Get total UW API calls from budget logs
    total_uw_calls = extract_api_budget_totals(log_file)
    
    print(f"📊 TOTAL UNUSUAL WHALES API CALLS: {total_uw_calls:,} / 7,500 ({100*total_uw_calls/7500:.1f}%)")
    print()
    print("=" * 80)
    print("BREAKDOWN BY SCHEDULED JOB")
    print("=" * 80)
    print()
    
    # Sort by runs (most active first)
    sorted_jobs = sorted(jobs_api_calls.items(), key=lambda x: x[1]['runs'], reverse=True)
    
    total_runs = 0
    total_uw_detected = 0
    
    for job_name, data in sorted_jobs:
        if data['runs'] == 0:
            continue
        
        total_runs += data['runs']
        total_uw_detected += data['uw_calls']
        
        print(f"🔹 {job_name}")
        print(f"   Runs: {data['runs']}")
        print(f"   UW API Calls (detected): {data['uw_calls']}")
        print(f"   Tickers Scanned: {data['tickers_scanned']}")
        if data['times']:
            print(f"   First Run: {data['times'][0]}")
            print(f"   Last Run: {data['times'][-1]}")
        print()
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total Scheduled Jobs Executed: {total_runs}")
    print(f"Total UW API Calls (from budget): {total_uw_calls:,}")
    print(f"UW API Calls (detected in logs): {total_uw_detected}")
    print()
    
    # Extract detailed time windows
    print("=" * 80)
    print("TIME WINDOW BREAKDOWN (from API Budget Logs)")
    print("=" * 80)
    print()
    
    with open(log_file, 'r') as f:
        for line in f:
            if '2026-02-06' in line and 'API Budget Status' in line:
                timestamp_match = re.search(r'(\d{2}:\d{2}:\d{2})', line)
                budget_match = re.search(r'Daily: (\d+)/7500.*Window \(([^)]+)\): (\d+)/(\d+)', line)
                if budget_match and timestamp_match:
                    time = timestamp_match.group(1)
                    daily_total = int(budget_match.group(1))
                    window = budget_match.group(2)
                    window_used = int(budget_match.group(3))
                    window_budget = int(budget_match.group(4))
                    print(f"{time} | Daily: {daily_total:,} | Window ({window}): {window_used}/{window_budget}")

if __name__ == '__main__':
    main()
