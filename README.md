# Surf report

Weekly email with a scored surf forecast for your spots, delivered every
Monday morning. Zero paid services, zero pip installs — just Python's
standard library and Open-Meteo's free API.

## How it works

- **Swell, tide, water temp** → [Open-Meteo Marine API](https://open-meteo.com/en/docs/marine-weather-api)
  (free, no key). Tide comes from `sea_level_height_msl`, which Open-Meteo
  itself flags as approximate near the coast — fine for "rising vs falling /
  roughly how high", not survey-grade.
- **Wind, sunrise/sunset** → [Open-Meteo Forecast API](https://open-meteo.com/en/docs) (same deal).
- **Scoring** → `spots.py`, a rubric you tune yourself (see below).
- **Delivery** → plain SMTP email, sent from a GitHub Actions cron job, so
  there's no server to keep running.

Note: the marine model's documented forecast window is shorter than the
14 days you get from the regular weather API (it's model-dependent, usually
7-8 days out reliably). The script just uses whatever Open-Meteo returns —
you'll typically see a solid week of swell data and a couple of extra
lower-confidence days beyond that.

## One-time setup

### 1. Get an app password for sending email

If using Gmail: turn on 2-Step Verification, then create an
[App Password](https://myaccount.google.com/apppasswords). Use that (not
your normal password) as `SMTP_PASS`.

### 2. Fork/push this repo to GitHub

```
cd surf-report
git init
git add .
git commit -m "Surf report bot"
git remote add origin <your-repo-url>
git push -u origin main
```

### 3. Add repo secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Example |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `youraddress@gmail.com` |
| `SMTP_PASS` | the app password from step 1 |
| `EMAIL_TO` | `thijs.jls@gmail.com` |

### 4. Test it

Go to the **Actions** tab → "Weekly Surf Report" → **Run workflow** to
trigger it manually and check your inbox. It'll otherwise run automatically
every Monday at 06:00 UTC.

## Tuning the rubric

Everything worth adjusting lives in `spots.py`:
- Add a new spot by copying one of the dicts in `SPOTS` and updating
  coordinates + thresholds.
- Change `WEIGHTS` to shift how much swell direction, height, period, wind
  speed, or tide matter to the final score.
- Adjust the `ideal`/`full`/`zero` bounds per spot as you compare the report
  against what you actually find in the water.

## Local testing without sending email

```
DRY_RUN=1 python3 surf_report.py
```

Writes `preview.html` instead of emailing, so you can open it in a browser.

There's also `test_offline.py`, which mocks the API responses entirely —
useful if you want to test scoring logic changes without burning API calls.

```
python3 test_offline.py
```
