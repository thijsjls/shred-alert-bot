"""Mocks the two API calls with synthetic-but-realistic data so the whole
scoring/rendering pipeline can be validated without network access."""
import json
from datetime import datetime, timedelta
import random

import surf_report as sr
from spots import SPOTS

random.seed(42)


FLAT_HOUR = 0  # hour index forced to genuinely flat conditions (regression case for Bug 1)


def fake_marine(spot):
    hours = 24 * 5
    start = datetime(2026, 7, 6, 0, 0)
    times = [(start + timedelta(hours=i)).isoformat() for i in range(hours)]
    swell_h = [round(1.0 + 1.2 * abs(random.gauss(0, 1)), 2) for _ in range(hours)]
    swell_period = [round(6 + 6 * random.random(), 1) for _ in range(hours)]
    swell_h[FLAT_HOUR] = 0.1
    swell_period[FLAT_HOUR] = 4.0
    wave_h = [round(h * 1.8, 2) for h in swell_h]  # combined swell+windsea > swell partition alone
    return {
        "hourly": {
            "time": times,
            "wave_height": wave_h,
            "swell_wave_height": swell_h,
            "swell_wave_direction": [round(spot["swell_dir"]["ideal"] + random.gauss(0, 30)) % 360 for _ in range(hours)],
            "swell_wave_period": swell_period,
            # simple sine tide with ~12.4h period
            "sea_level_height_msl": [round(1.5 * __import__("math").sin(i / 12.4 * 2 * __import__("math").pi), 2) for i in range(hours)],
            "sea_surface_temperature": [round(17 + random.random(), 1) for _ in range(hours)],
        }
    }


def fake_forecast(spot):
    hours = 24 * 5
    start = datetime(2026, 7, 6, 0, 0)
    times = [(start + timedelta(hours=i)).isoformat() for i in range(hours)]
    days = [(start + timedelta(days=d)).date().isoformat() for d in range(5)]
    return {
        "hourly": {
            "time": times,
            "wind_speed_10m": [round(5 + 10 * random.random(), 1) for _ in range(hours)],
            "wind_direction_10m": [round(spot["wind_dir"]["ideal"] + random.gauss(0, 40)) % 360 for _ in range(hours)],
        },
        "daily": {
            "time": days,
            "sunrise": [f"{d}T06:30" for d in days],
            "sunset": [f"{d}T21:30" for d in days],
        },
    }


sr.fetch_marine = fake_marine
sr.fetch_forecast = fake_forecast

# Regression test for Bug 1: flat swell (0.1m, 4s) must score near-zero even
# when direction/wind/tide are all perfect -- a weighted sum let those drag
# a flat day up to 5-6/10, the height/period gate must prevent that.
flat_spot = SPOTS[0]
flat_rec = {
    "wave_h": 0.1,
    "swell_h": 0.1,
    "swell_dir": flat_spot["swell_dir"]["ideal"],
    "swell_period": 4.0,
    "wind_speed": 5.0,
    "wind_dir": flat_spot["wind_dir"]["ideal"],
    "tide_norm": 0.7,
    "tide_rising": True,
}
flat_score = sr.score_record(flat_rec, flat_spot) * 10
assert flat_score < 1.0, f"flat conditions should score near 0, got {flat_score}"
print(f"Flat-conditions regression check OK: score={flat_score:.2f}/10")

all_reports = []
for spot in SPOTS:
    days = sr.build_daily_report(spot)
    assert days, f"no days produced for {spot['name']}"
    for d in days:
        b = d["best"]
        assert 0 <= b["score"] <= 10
        assert b["start"] < b["end"]
    all_reports.append((spot, days))
    print(f"{spot['name']}: {len(days)} days OK, sample best={days[0]['best']}")

html = sr.render_html(all_reports)
assert "<table" in html and "La Palue" in html and "Rocky Point" in html
with open("preview.html", "w") as f:
    f.write(html)
print("\nAll checks passed. preview.html written.")
