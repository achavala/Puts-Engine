#!/usr/bin/env python3
"""List all scheduled scan jobs with times."""

import re

# Read scheduler.py
with open('putsengine/scheduler.py', 'r') as f:
    content = f.read()

# Split into add_job blocks
blocks = re.split(r'self\.scheduler\.add_job\(', content)

jobs = []
for block in blocks[1:]:  # Skip first split (before any add_job)
    # Look for CronTrigger with hour and minute
    cron_match = re.search(r'CronTrigger\(hour=(\d+),\s*minute=(\d+)', block)
    name_match = re.search(r'name="([^"]+)"', block)
    
    if cron_match and name_match:
        jobs.append({
            'hour': int(cron_match.group(1)),
            'minute': int(cron_match.group(2)),
            'name': name_match.group(1),
            'type': 'cron'
        })
    else:
        # Check for IntervalTrigger
        interval_match = re.search(r'IntervalTrigger\(minutes=(\d+)', block)
        if interval_match and name_match:
            jobs.append({
                'hour': 99,  # Sort at end
                'minute': int(interval_match.group(1)),
                'name': name_match.group(1),
                'type': 'interval'
            })

# REMOVED: Pattern scans every 30 min (optimization Feb 4, 2026)
# The scheduler.py now only has ONE pattern scan at 4:00 PM

# Sort by time
jobs.sort(key=lambda x: (x['hour'], x['minute']))

def format_time(job):
    if job['type'] == 'interval':
        return f"Every {job['minute']}m"
    hour = job['hour']
    minute = job['minute']
    period = 'AM' if hour < 12 else 'PM'
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour:2}:{minute:02d} {period}"

print("=" * 90)
print(f"{'PUTSENGINE SCAN SCHEDULE - ' + str(len(jobs)) + ' JOBS':^90}")
print("=" * 90)
print()

# Pre-Market
print("🌅 PRE-MARKET SCANS (4:00 AM - 9:00 AM ET)")
print("-" * 90)
count = 0
for job in jobs:
    if job['type'] == 'cron' and 4 <= job['hour'] < 9:
        print(f"  {format_time(job):>10}  |  {job['name']}")
        count += 1
print(f"  ({count} scans)")
print()

# Market Hours
print("📈 MARKET HOURS SCANS (9:00 AM - 4:00 PM ET)")
print("-" * 90)
count = 0
for job in jobs:
    if job['type'] == 'cron' and 9 <= job['hour'] < 16:
        print(f"  {format_time(job):>10}  |  {job['name']}")
        count += 1
print(f"  ({count} scans)")
print()

# After Hours
print("🌙 AFTER-HOURS & OVERNIGHT SCANS (4:00 PM - 11:00 PM ET)")
print("-" * 90)
count = 0
for job in jobs:
    if job['type'] == 'cron' and job['hour'] >= 16:
        print(f"  {format_time(job):>10}  |  {job['name']}")
        count += 1
print(f"  ({count} scans)")
print()

# Interval
print("🔄 INTERVAL SCANS (Run Throughout Day)")
print("-" * 90)
for job in jobs:
    if job['type'] == 'interval':
        print(f"  {format_time(job):>10}  |  {job['name']}")
print()

print("=" * 90)
print(f"TOTAL: {len(jobs)} scheduled scan jobs")
print("=" * 90)
