#!/usr/bin/env python3
"""Apply stagger changes to scheduler.py in main PutsEngine dir."""
import sys

filepath = 'putsengine/scheduler.py'

with open(filepath, 'r') as f:
    content = f.read()

changes = 0

# 1. EWS 3PM: minute=0 -> minute=2
old1 = 'CronTrigger(hour=15, minute=0, timezone=EST),\n            id="early_warning_3pm",'
new1 = 'CronTrigger(hour=15, minute=2, timezone=EST),\n            id="early_warning_3pm",'
if old1 in content:
    content = content.replace(old1, new1)
    changes += 1
    print("1. EWS 3PM -> 3:02 PM")
else:
    # Check if already staggered
    if 'minute=2, timezone=EST),\n            id="early_warning_3pm"' in content:
        print("1. EWS 3PM already at 3:02 PM")
    else:
        print("1. WARNING: EWS 3PM pattern not found!")

# Also update the name
old1n = 'Early Warning Scan (3:00 PM ET) - AFTERNOON CLOSE PREP'
new1n = 'Early Warning Scan (3:02 PM ET) - AFTERNOON CLOSE PREP'
if old1n in content:
    content = content.replace(old1n, new1n)

# 2. Weather AM: minute=0 -> minute=5
old2 = 'CronTrigger(hour=9, minute=0, timezone=EST),\n            id="market_weather_0900",'
new2 = 'CronTrigger(hour=9, minute=5, timezone=EST),\n            id="market_weather_0900",'
if old2 in content:
    content = content.replace(old2, new2)
    changes += 1
    print("2. Weather AM 9:00 -> 9:05 AM")
else:
    if 'minute=5, timezone=EST),\n            id="market_weather_0900"' in content:
        print("2. Weather AM already at 9:05 AM")
    else:
        print("2. WARNING: Weather AM pattern not found!")

old2n = 'Market Weather AM (9:00 AM ET)'
new2n = 'Market Weather AM (9:05 AM ET)'
if old2n in content:
    content = content.replace(old2n, new2n)

# 3. Weather PM: minute=0 -> minute=8
old3 = 'CronTrigger(hour=15, minute=0, timezone=EST),\n            id="market_weather_1500",'
new3 = 'CronTrigger(hour=15, minute=8, timezone=EST),\n            id="market_weather_1500",'
if old3 in content:
    content = content.replace(old3, new3)
    changes += 1
    print("3. Weather PM 3:00 -> 3:08 PM")
else:
    if 'minute=8, timezone=EST),\n            id="market_weather_1500"' in content:
        print("3. Weather PM already at 3:08 PM")
    else:
        print("3. WARNING: Weather PM pattern not found!")

old3n = 'Market Weather PM (3:00 PM ET)'
new3n = 'Market Weather PM (3:08 PM ET)'
if old3n in content:
    content = content.replace(old3n, new3n)

with open(filepath, 'w') as f:
    f.write(content)

print(f"\nTotal changes applied: {changes}")
