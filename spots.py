"""
Spot definitions and scoring rubric.

This is the only file you should need to touch to tune the rating, add a new
spot, or adjust thresholds after a few weeks of comparing the report against
reality.

Every "direction" field is in degrees, using the meteorological convention
(the direction the swell/wind is coming FROM). 0=N, 90=E, 180=S, 270=W.

Scoring shape for direction and wind is a trapezoid:
    - within +/- full_lo / full_hi degrees of `ideal`      -> score 1.0
    - between full and zero                                 -> linear falloff
    - beyond +/- zero_lo / zero_hi degrees                  -> score 0.0
`full_lo`/`zero_lo` apply to the counter-clockwise side of `ideal`,
`full_hi`/`zero_hi` to the clockwise side (handles asymmetric windows and
wraps correctly around 360/0).

Height and period use simple ramps/trapezoids in metres and seconds.
"""

SPOTS = [
    {
        "key": "la_palue",
        "name": "La Palue",
        "region": "Crozon, Brittany",
        "lat": 48.228,
        "lon": -4.556,
        "timezone": "Europe/Paris",

        "swell_dir": {
            "ideal": 247,       # WSW
            "full_lo": 15, "full_hi": 15,
            "zero_lo": 45, "zero_hi": 45,   # zero outside SW(202)-NW(292)
        },
        "height_m": {
            "ideal_min": 1.2, "ideal_max": 2.5,
            "zero_min": 0.4, "zero_max": 4.0,
        },
        "period_s": {
            "zero_below": 5.0,
            "ideal_above": 10.0,
        },
        "wind_dir": {
            "ideal": 90,        # offshore = East
            "full_lo": 15, "full_hi": 15,
            "zero_lo": 45, "zero_hi": 45,   # zero outside NE(45)-SE(135)
        },
        "wind_speed_kt": {
            "ideal_max": 15.0,
            "zero_above": 25.0,
        },
        "tide": {
            "style": "mid_high_rising",
            # reef/shallow caution not relevant here, it's sand
        },
    },
    {
        "key": "rocky_point",
        "name": "Rocky Point (Inside)",
        "region": "Corralejo, Fuerteventura",
        "lat": 28.735,
        "lon": -13.862,
        "timezone": "Atlantic/Canary",

        "swell_dir": {
            "ideal": 315,       # NW
            "full_lo": 10, "full_hi": 15,
            "zero_lo": 20, "zero_hi": 45,   # zero outside NW(295)-N(360)
        },
        "height_m": {
            "ideal_min": 2.5, "ideal_max": 4.0,
            "zero_min": 1.0, "zero_max": 5.5,
        },
        "period_s": {
            "zero_below": 7.0,
            "ideal_above": 12.0,
        },
        "wind_dir": {
            "ideal": 225,       # offshore = SW
            "full_lo": 10, "full_hi": 15,
            "zero_lo": 23, "zero_hi": 45,   # zero outside SW(202)-W(270)
        },
        "wind_speed_kt": {
            "ideal_max": 15.0,
            "zero_above": 25.0,
        },
        "tide": {
            "style": "any_reef_caution",   # small penalty at dead low, shallow reef
        },
    },
]

# Relative importance of each factor in the final 0-10 score.
# Must sum to 1.0. Change freely -- this was Thijs's ranking:
# direction > height > period > wind speed > tide.
WEIGHTS = {
    "direction": 0.30,
    "height": 0.25,
    "period": 0.20,
    "wind_speed": 0.15,
    "tide": 0.10,
}

# How many days ahead to request (marine wave models may return fewer than
# this depending on model coverage -- the script uses whatever comes back).
FORECAST_DAYS = 14

# Block size for "when's the best window today" -- 3 hours per your request.
BLOCK_HOURS = 3
