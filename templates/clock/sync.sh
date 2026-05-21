#!/usr/bin/env bash
# Sync time + 3-day forecast to the Giga Display clock sketch
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"

# Send time and date
echo "T $(date +%H:%M:%S) $(date +%Y-%m-%d)" > "$PORT"

# Fetch forecast and format for the sketch
# Format: "W day0,Mt,Mc,Nt,Nc,Et,Ec,NIt,NIc|day1,...|day2,..."
FORECAST=$(curl -s "wttr.in/?format=j1" | python3 -c "
import json, sys

data = json.load(sys.stdin)
days = data['weather'][:3]
day_names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

parts = []
for day in days:
    from datetime import datetime
    dt = datetime.strptime(day['date'], '%Y-%m-%d')
    name = day_names[dt.weekday()]

    hourly = {int(h['time'])//100: h for h in day['hourly']}
    # Morning=avg(6,9), Noon=12, Evening=18, Night=21
    slots = []
    for hours in [(6,9), (12,), (18,), (21,)]:
        temps = [int(hourly[h]['tempC']) for h in hours if h in hourly]
        codes = [int(hourly[h]['weatherCode']) for h in hours if h in hourly]
        t = sum(temps)//len(temps) if temps else 0
        c = codes[0] if codes else 113
        slots.append(f'{t},{c}')

    parts.append(f'{name},{\",\".join(slots)}')

print('|'.join(parts))
")

sleep 0.1
echo "W $FORECAST" > "$PORT"
echo "Synced: $(date +%H:%M) + forecast"
