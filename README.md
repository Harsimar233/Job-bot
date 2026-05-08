# 🤖 Job Bot

Automatically finds crypto/web3 jobs from LinkedIn, CryptoJobsList, Web3.career, and Wellfound.
Sends the best matches to your Telegram — 3 times a day.

---

## Setup (10 minutes, no coding)

### Step 1 — Get your Telegram Bot token

1. Open Telegram and search for **@BotFather**
2. Send him: `/newbot`
3. Choose any name (e.g. `My Job Bot`)
4. Choose any username ending in `bot` (e.g. `myjobs_bot`)
5. BotFather sends you a token that looks like: `7123456789:AAFxxx...`
6. **Copy and save this token**

---

### Step 2 — Get your Telegram Chat ID

1. Open Telegram and search for **@userinfobot**
2. Press Start
3. It replies with your ID, something like: `123456789`
4. **Copy and save this number**

---

### Step 3 — Put the bot on GitHub

1. Go to this GitHub repo and click **Fork** (top right)
2. That creates a copy in your own GitHub account

---

### Step 4 — Deploy to Vercel

1. Go to [vercel.com](https://vercel.com) and log in with GitHub
2. Click **Add New Project**
3. Choose the forked repo (`job-bot`)
4. Before clicking Deploy, click **Environment Variables** and add these 3:

| Name | Value |
|------|-------|
| `BOT_TOKEN` | The token from BotFather |
| `CHAT_ID` | Your ID from userinfobot |
| `KEYWORDS` | `web3,crypto,blockchain,solidity,react,typescript,telegram,defi,nft,dao` |

5. Click **Deploy**

---

### Step 5 — Test it

1. In your Vercel project, go to the **Functions** tab
2. Find `api/scan` and click **Test**
3. Check your Telegram — you should get job matches within 30 seconds

---

## When does it run?

Automatically 3 times a day:
- 9:00 AM UTC
- 3:00 PM UTC
- 9:00 PM UTC

You can also trigger it manually anytime from the Vercel Functions tab.

---

## Customizing keywords

In Vercel, go to **Settings > Environment Variables** and edit `KEYWORDS`.
Add or remove skills/topics separated by commas. No spaces needed.

Example (already set for your profile):
```
community,ambassador,growth,web3,discord,telegram,dao,defi,nft,kol,galxe,zealy,moderator,ecosystem,protocol
```

---

## Something not working?

- **No messages in Telegram**: Double check `BOT_TOKEN` and `CHAT_ID` are correct in Vercel env vars
- **Bot found but no jobs**: Try broadening your `KEYWORDS` (fewer, more generic terms)
- **Vercel errors**: Check the Function Logs in your Vercel dashboard
