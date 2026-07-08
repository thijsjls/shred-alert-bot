#!/usr/bin/env python3
"""
Weekly surf report.

Fetches swell, wind, tide (via sea level height) and water temperature from
Open-Meteo (free, no API key needed for personal use), scores each spot
against the rubric in spots.py, and emails a report.

Zero third-party dependencies -- only the Python standard library.

Config via environment variables (see README.md):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO
"""

import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from spots import SPOTS, WEIGHTS, FORECAST_DAYS, BLOCK_HOURS

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def http_get_json(url, params):
    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    with urllib.request.urlopen(full_url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_marine(spot):
    params = {
        "latitude": spot["lat"],
        "longitude": spot["lon"],
        "hourly": [
            "wave_height",          # combined swell + wind sea -> height score & headline
            "swell_wave_height",    # swell partition only -> secondary reference
            "swell_wave_direction",
            "swell_wave_period",
            "sea_level_height_msl",
            "sea_surface_temperature",
        ],
        "timezone": spot["timezone"],
        "forecast_days": FORECAST_DAYS,
    }
    return http_get_json(MARINE_URL, params)


def fetch_forecast(spot):
    params = {
        "latitude": spot["lat"],
        "longitude": spot["lon"],
        "hourly": ["wind_speed_10m", "wind_direction_10m"],
        "daily": ["sunrise", "sunset"],
        "wind_speed_unit": "kn",
        "timezone": spot["timezone"],
        "forecast_days": FORECAST_DAYS,
    }
    return http_get_json(FORECAST_URL, params)


# --------------------------------------------------------------------------
# Scoring primitives
# --------------------------------------------------------------------------

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def circular_diff(actual, ideal):
    """Signed difference in degrees, in [-180, 180). Positive = clockwise
    (the 'hi' side) of ideal."""
    return (actual - ideal + 180) % 360 - 180


def trapezoid(x, full, zero):
    if zero <= full:
        zero = full + 0.01
    if x <= full:
        return 1.0
    if x >= zero:
        return 0.0
    return 1 - (x - full) / (zero - full)


def direction_score(actual, cfg):
    d = circular_diff(actual, cfg["ideal"])
    if d >= 0:
        return trapezoid(d, cfg["full_hi"], cfg["zero_hi"])
    return trapezoid(-d, cfg["full_lo"], cfg["zero_lo"])


def height_score(h, cfg):
    if h <= cfg["zero_min"] or h >= cfg["zero_max"]:
        return 0.0
    if cfg["ideal_min"] <= h <= cfg["ideal_max"]:
        return 1.0
    if h < cfg["ideal_min"]:
        return (h - cfg["zero_min"]) / (cfg["ideal_min"] - cfg["zero_min"])
    return (cfg["zero_max"] - h) / (cfg["zero_max"] - cfg["ideal_max"])


def period_score(p, cfg):
    if p <= cfg["zero_below"]:
        return 0.0
    if p >= cfg["ideal_above"]:
        return 1.0
    return (p - cfg["zero_below"]) / (cfg["ideal_above"] - cfg["zero_below"])


def wind_speed_score(spd, cfg):
    if spd <= cfg["ideal_max"]:
        return 1.0
    if spd >= cfg["zero_above"]:
        return 0.0
    return 1 - (spd - cfg["ideal_max"]) / (cfg["zero_above"] - cfg["ideal_max"])


def tide_score(norm, rising, style):
    """norm: 0-1 position within this spot's observed tidal range over the
    fetch window. rising: bool."""
    if style == "mid_high_rising":
        if norm < 0.3:
            h = norm / 0.3 * 0.4
        elif norm < 0.55:
            h = 0.4 + (norm - 0.3) / 0.25 * 0.4
        elif norm <= 0.9:
            h = 0.8 + (norm - 0.55) / 0.35 * 0.2
        else:
            h = 1.0 - (norm - 0.9) / 0.1 * 0.3
        bonus = 0.15 if rising else -0.10
        return clamp(h + bonus)
    else:  # any_reef_caution
        if norm < 0.12:
            return 0.5
        return 1.0


def compact_dir(deg):
    """Degrees -> 16-point compass label."""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]


# --------------------------------------------------------------------------
# Data assembly
# --------------------------------------------------------------------------

def build_hourly_records(spot):
    marine = fetch_marine(spot)
    forecast = fetch_forecast(spot)

    m_time = marine["hourly"]["time"]
    f_time = forecast["hourly"]["time"]
    # Use the overlap only, in case one API returned fewer hours than the other.
    n = min(len(m_time), len(f_time))

    wave_h = marine["hourly"]["wave_height"]
    swell_h = marine["hourly"]["swell_wave_height"]
    swell_dir = marine["hourly"]["swell_wave_direction"]
    swell_period = marine["hourly"]["swell_wave_period"]
    sea_level = marine["hourly"]["sea_level_height_msl"]
    sst = marine["hourly"]["sea_surface_temperature"]

    wind_speed = forecast["hourly"]["wind_speed_10m"]
    wind_dir = forecast["hourly"]["wind_direction_10m"]

    # Tide normalisation across the whole fetched window (~14 days covers
    # close to a full spring-neap cycle, so this approximates the real range).
    valid_levels = [v for v in sea_level[:n] if v is not None]
    lvl_min, lvl_max = min(valid_levels), max(valid_levels)
    lvl_range = max(lvl_max - lvl_min, 0.01)

    records = []
    for i in range(n):
        if None in (wave_h[i], swell_h[i], swell_dir[i], swell_period[i], sea_level[i],
                    wind_speed[i], wind_dir[i]):
            continue
        norm = (sea_level[i] - lvl_min) / lvl_range
        prev_level = sea_level[i - 1] if i > 0 and sea_level[i - 1] is not None else sea_level[i]
        rising = sea_level[i] >= prev_level
        records.append({
            "time": datetime.fromisoformat(m_time[i]),
            "wave_h": wave_h[i],
            "swell_h": swell_h[i],
            "swell_dir": swell_dir[i],
            "swell_period": swell_period[i],
            "wind_speed": wind_speed[i],
            "wind_dir": wind_dir[i],
            "tide_norm": norm,
            "tide_rising": rising,
            "sst": sst[i],
        })

    sun = {}
    for d, sr, ss in zip(forecast["daily"]["time"],
                          forecast["daily"]["sunrise"],
                          forecast["daily"]["sunset"]):
        sun[d] = (datetime.fromisoformat(sr), datetime.fromisoformat(ss))

    return records, sun


QUALITY_KEYS = ("direction", "wind_speed", "tide")


def score_record(rec, spot):
    s_dir = direction_score(rec["swell_dir"], spot["swell_dir"])
    w_dir = direction_score(rec["wind_dir"], spot["wind_dir"])
    direction_component = (s_dir + w_dir) / 2
    height_component = height_score(rec["wave_h"], spot["height_m"])
    period_component = period_score(rec["swell_period"], spot["period_s"])
    wind_component = wind_speed_score(rec["wind_speed"], spot["wind_speed_kt"])
    tide_component = tide_score(rec["tide_norm"], rec["tide_rising"], spot["tide"]["style"])

    # Height and period are a multiplicative gate rather than weighted-sum
    # contributors: you need both adequate size and period for a makeable
    # wave at all, so the worse of the two caps the score regardless of how
    # good direction/wind/tide are (a plain weighted sum let those drag a
    # flat day up to 5-6/10).
    gate = min(height_component, period_component)

    quality_weight_sum = sum(WEIGHTS[k] for k in QUALITY_KEYS)
    quality_components = {
        "direction": direction_component,
        "wind_speed": wind_component,
        "tide": tide_component,
    }
    quality = sum(
        WEIGHTS[k] / quality_weight_sum * quality_components[k]
        for k in QUALITY_KEYS
    )

    return gate * quality


def is_offshore(wind_dir, spot):
    """Whether wind direction falls within the 'workable' offshore window."""
    return direction_score(wind_dir, spot["wind_dir"]) > 0


def summarize_block(records, spot):
    n = len(records)
    avg_h = sum(r["wave_h"] for r in records) / n
    avg_swell_h = sum(r["swell_h"] for r in records) / n
    avg_p = sum(r["swell_period"] for r in records) / n
    avg_wind_speed = sum(r["wind_speed"] for r in records) / n
    avg_sst = sum(r["sst"] for r in records) / n
    rising = sum(1 for r in records if r["tide_rising"]) > n / 2
    # circular mean for directions
    import math
    def circ_mean(vals):
        sx = sum(math.sin(math.radians(v)) for v in vals)
        cx = sum(math.cos(math.radians(v)) for v in vals)
        return math.degrees(math.atan2(sx, cx)) % 360
    avg_swell_dir = circ_mean([r["swell_dir"] for r in records])
    avg_wind_dir = circ_mean([r["wind_dir"] for r in records])
    avg_tide_norm = sum(r["tide_norm"] for r in records) / n

    score = sum(score_record(r, spot) for r in records) / n
    offshore = is_offshore(avg_wind_dir, spot)

    return {
        "start": records[0]["time"],
        "end": records[-1]["time"],
        "score": round(score * 10, 1),
        "wave_h": round(avg_h, 1),
        "swell_h": round(avg_swell_h, 1),
        "swell_period": round(avg_p, 0),
        "swell_dir": compact_dir(avg_swell_dir),
        "wind_speed": round(avg_wind_speed),
        "wind_dir": compact_dir(avg_wind_dir),
        "offshore": offshore,
        "tide_norm": round(avg_tide_norm, 2),
        "tide_rising": rising,
        "sst": round(avg_sst, 1),
    }


def build_daily_report(spot):
    records, sun = build_hourly_records(spot)

    by_day = {}
    for r in records:
        by_day.setdefault(r["time"].date(), []).append(r)

    days = []
    for day, day_records in sorted(by_day.items()):
        day_str = day.isoformat()
        if day_str in sun:
            sunrise, sunset = sun[day_str]
        else:
            sunrise, sunset = day_records[0]["time"], day_records[-1]["time"]

        daylight = [r for r in day_records if sunrise <= r["time"] <= sunset]
        if not daylight:
            daylight = day_records

        # split into BLOCK_HOURS-sized chunks by wall clock hour
        blocks = []
        daylight.sort(key=lambda r: r["time"])
        i = 0
        while i < len(daylight):
            block_start_hour = daylight[i]["time"].hour
            block = [daylight[i]]
            j = i + 1
            while j < len(daylight) and daylight[j]["time"].hour < block_start_hour + BLOCK_HOURS:
                block.append(daylight[j])
                j += 1
            blocks.append(block)
            i = j

        summaries = [summarize_block(b, spot) for b in blocks if b]
        if not summaries:
            continue
        best = max(summaries, key=lambda s: s["score"])

        days.append({
            "date": day,
            "sunrise": sunrise,
            "sunset": sunset,
            "best": best,
        })

    return days


# --------------------------------------------------------------------------
# Email rendering
# --------------------------------------------------------------------------

def score_color(score):
    if score >= 7:
        return "#1a7f37"
    if score >= 5:
        return "#9a6700"
    return "#7d1a1a"


def render_html(all_reports):
    parts = [
        "<html><body style='font-family:Arial,sans-serif;color:#222;'>",
        f"<h2>Surf report — {date.today().isoformat()}</h2>",
    ]
    for spot, days in all_reports:
        parts.append(f"<h3 style='margin-top:28px;'>{spot['name']} — {spot['region']}</h3>")
        parts.append(
            "<table cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%;max-width:640px;'>"
        )
        parts.append(
            "<tr style='background:#f0f0f0;text-align:left;'>"
            "<th>Day</th><th>Score</th><th>Best window</th><th>Conditions</th><th>Water</th></tr>"
        )
        for d in days:
            b = d["best"]
            offshore_label = "offshore" if b["offshore"] else "onshore/cross"
            tide_label = "rising" if b["tide_rising"] else "falling"
            conditions = (
                f"{b['wave_h']}m ({b['swell_h']}m swell) @ {b['swell_period']:.0f}s {b['swell_dir']}, "
                f"wind {b['wind_speed']}kt {b['wind_dir']} ({offshore_label}), "
                f"tide {tide_label}"
            )
            window = f"{b['start'].strftime('%H:%M')}–{b['end'].strftime('%H:%M')}"
            color = score_color(b["score"])
            parts.append(
                "<tr style='border-top:1px solid #ddd;'>"
                f"<td>{d['date'].strftime('%a %d %b')}</td>"
                f"<td style='color:{color};font-weight:bold;'>{b['score']}/10"
                f"{' 🤙' if b['score'] > 8 else ''}</td>"
                f"<td>{window}</td>"
                f"<td>{conditions}</td>"
                f"<td>{b['sst']}°C</td>"
                "</tr>"
            )
        parts.append("</table>")
    parts.append(
        "<p style='color:#888;font-size:12px;margin-top:24px;'>"
        "Swell, wind, sea level (tide) and water temp from Open-Meteo. "
        "Score is a weighted personal rubric, not an absolute measure of quality — "
        "tune it in spots.py as you compare against reality."
        "</p>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def send_email(html_body):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["EMAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Surf report — {date.today().strftime('%a %d %b')}"
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())


def main():
    all_reports = []
    for spot in SPOTS:
        print(f"Fetching {spot['name']}...", file=sys.stderr)
        days = build_daily_report(spot)
        all_reports.append((spot, days))

    html = render_html(all_reports)

    if os.environ.get("DRY_RUN"):
        with open("preview.html", "w") as f:
            f.write(html)
        print("DRY_RUN set — wrote preview.html instead of sending email.", file=sys.stderr)
        return

    send_email(html)
    print("Email sent.", file=sys.stderr)


if __name__ == "__main__":
    main()
