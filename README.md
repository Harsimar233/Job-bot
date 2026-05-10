# 🤖 Remote Radar — Job Alert Bot

Automatically finds remote jobs from 12 global sources.
Sends personalised daily alerts to users on Telegram — 3× per day.

---

## Stack

| Layer | Tool | Cost |
|-------|------|------|
| Hosting | Vercel (serverless) | Free |
| Database | Supabase | Free |
| Bot | Telegram Bot API | Free |

---

## Setup (15 minutes)

### Step 1 — Create your Telegram bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → choose a name → choose a username ending in `bot`
3. Copy the token it gives you (looks like `7123456789:AAFxxx...`)

### Step 2 — Get your Chat ID (for testing)

1. Search **@userinfobot** → press Start
2. It shows your ID (e.g. `123456789`)

### Step 3 — Set up Supabase

1. Go to [supabase.com](https://supabase.com) → create a new project
2. Go to **SQL Editor** → paste the contents of `supabase_schema.sql` → click Run
3. Go to **Settings > API** → copy:
   - **Project URL** (looks like `https://xxxx.supabase.co`)
   - **anon/public key**

### Step 4 — Fork & deploy to Vercel

1. Fork this repo on GitHub
2. Go to [vercel.com](https://vercel.com) → Add New Project → pick your fork
3. Under **Environment Variables**, add these:

| Name | Value |
|------|-------|
| `JOB_BOT_TOKEN` | Your BotFather token |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase anon key |
| `BOT_USERNAME` | Your bot's username (without @) |
| `LOG_LEVEL` | `INFO` (use `DEBUG` while testing) |
| `SCRAPER_KEY` | Optional: ScraperAPI key for Web3.career |

4. Click **Deploy**

### Step 5 — Register the webhook

After deploy, open this URL in your browser (replace values):

```
https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_DOMAIN>/api/webhook
```

### Step 6 — Test

1. In Vercel → **Functions** tab → find `api/scan` → click **Test**
2. Open your bot on Telegram and send `/start`
3. You should receive a welcome message within seconds

---

## When does it run?

Automatically 3 times a day (UTC):
- **9:00 AM**
- **3:00 PM**
- **9:00 PM**

Trigger manually any time from the Vercel Functions tab.

---

## Bot commands

| Command | What it does |
|---------|-------------|
| `/start` | Welcome + onboarding |
| `/find` | Find jobs right now |
| `/keywords web3, community` | Update your keywords |
| `/saved` | View bookmarked jobs |
| `/watch Coinbase` | Get alerts when Coinbase posts |
| `/status` | View your preferences |
| `/invite` | Get your referral link |
| `/stop` | Pause alerts |
| `/delete` | Delete all your data |
| `/help` | Show all commands |

---

## Troubleshooting

- **No messages**: Check `JOB_BOT_TOKEN` and `SUPABASE_KEY` in Vercel env vars
- **No jobs matched**: Broaden your keywords or change seniority to "All Levels"
- **Vercel errors**: Check Function Logs in your Vercel dashboard — errors are now properly logged
- **Webhook not responding**: Re-run the `setWebhook` URL above

---

## Architecture

```
Telegram User
     │
     ▼
api/webhook.py  ← handles all messages & button taps
     │
     ▼
Supabase        ← stores users, jobs, sent history, analytics

[Cron 3×/day]
     │
     ▼
api/scan.py     ← fetches jobs, matches users, sends alerts
     │
     ▼
api/jobs.py     ← scrapes 12 job sources in parallel
```
