# Super Job Bot

A Telegram-first job discovery engine for local, hybrid and remote work—from
restaurant and retail jobs to engineering, healthcare and director-level roles.

See [AUDIT.md](./AUDIT.md) for the complete product, security and UX review.

## What changed

- Existing 12-source scraper engine remains available.
- OpenAI Responses API web search is an optional discovery source.
- AI searches are demand-driven: similar user role/location preferences are
  clustered so the app does not make one paid request per user.
- Hospitality, retail, logistics, healthcare, education, trades, services and
  government roles are included in the job taxonomy.
- Users can enter any city, region or country during onboarding.
- Dedicated **Abroad + Work Visa** mode with comma-separated target countries.
- Visa mode rejects jobs requiring existing local work rights and only matches
  explicit sponsorship/work-permit support or overseas-candidate acceptance.
- Jobs now store work mode, employment type, category, experience, discovery
  method and evidence.
- Missing Supabase schema is included.
- Cron endpoint supports bearer-token protection.
- `/find` pagination and keyword refresh bugs are fixed.
- Owner-only, review-first **Apply Agent** stores one resume reference and
  candidate profile, auto-queues matches, drafts truthful cover letters, and
  asks for approval before opening the original employer form.

## Discovery architecture

```text
Telegram users
    |
    +-- preferences: role, level, location, remote/local
    |
Scheduled scan
    |
    +-- public APIs, RSS and ATS feeds (deterministic)
    +-- OpenAI web search scout (optional, demand-driven)
    |
Normalize -> validate URL/date -> deduplicate -> Supabase
    |
Match and rank -> Telegram alerts
    |
Opt-in Apply Agent -> queue -> draft -> user approval -> employer form
```

OpenAI is not treated as the database. It discovers and extracts recent
postings; the bot still validates required fields, keeps the original apply URL,
deduplicates results and stores normalized records.

## Apply Agent

The private beta is restricted to `@Harsimarhs` by default. Other users see a
button to DM the owner instead of application controls. For the strongest lock,
set `AUTO_APPLY_ALLOWED_CHAT_ID` to the owner's numeric Telegram chat ID; when
that variable is set, it overrides username matching.

The owner runs `/autoapply`, accepts the privacy notice, then uploads a
PDF/DOC/DOCX resume and enters the contact details applications should use.
When review mode is on:

1. New personalized matches are added to `applications`.
2. `/applications` shows the pending queue.
3. **Prepare Application** generates a job-specific draft. Contact details and
   the Telegram resume file ID are not sent to OpenAI.
4. The candidate approves the draft and opens the original employer form.

This is intentionally review-first. The app does not claim a submission
succeeded when it only opened a URL, does not invent experience or work
authorization, and does not bypass CAPTCHA. `api/apply_agent.py` identifies
Greenhouse, Lever, Ashby, Workday and generic forms so audited site-specific
submission adapters can be added later without changing the queue or consent
model.

Resume files are not copied into Supabase; only Telegram's private `file_id` and
basic metadata are stored. Database tables use RLS and are accessed only with
the server-side Supabase service-role key.

For relocation searches, the discovery prompt states that the candidate is
currently in India. A local validation gate then rejects results unless the
structured result confirms employer visa/work-permit support or explicit
acceptance of overseas applicants. Generic phrases such as "must have work
authorization" are not treated as sponsorship.

## Setup

1. Create a Telegram bot with `@BotFather`.
2. Create a Supabase project.
3. Run [`supabase_schema.sql`](./supabase_schema.sql) in the Supabase SQL Editor.
4. Deploy the repository to Vercel.
5. Add the environment variables shown in [`.env.example`](./.env.example).
6. Generate a random `TELEGRAM_WEBHOOK_SECRET`, add it to the deployment, and
   register the Telegram webhook with the same value:

```text
https://api.telegram.org/bot<JOB_BOT_TOKEN>/setWebhook?url=https://<DOMAIN>/api/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

The webhook rejects requests whose
`X-Telegram-Bot-Api-Secret-Token` header does not match.

### Important Supabase key rule

`SUPABASE_KEY` must be the server-side `service_role` key—not the public anon
key. Store it only in Vercel/GitHub secrets. Never expose it in frontend code.

### OpenAI web discovery

Set `OPENAI_API_KEY` to enable it. Without this key, all non-AI job sources keep
working normally.

Cost and coverage controls:

- `OPENAI_MAX_SEARCHES`: maximum clustered searches per scan; default `6`.
- `OPENAI_RESULTS_PER_SEARCH`: requested jobs per search; default `12`.
- `OPENAI_MODEL`: model used for search and structured extraction.
- `OPENAI_TIMEOUT`: request timeout in seconds.

Only listings with a valid direct URL, company, title and parseable posting date
within 30 days are accepted. The prompt prefers jobs from the last 7 days.

## Required environment variables

| Variable | Purpose |
|---|---|
| `JOB_BOT_TOKEN` | Telegram BotFather token |
| `BOT_USERNAME` | Bot username without `@` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase `service_role` key |
| `CRON_SECRET` | Protects `/api/scan` |
| `TELEGRAM_WEBHOOK_SECRET` | Verifies Telegram webhook requests |
| `AUTO_APPLY_OWNER_USERNAME` | Private beta owner; default `Harsimarhs` |
| `AUTO_APPLY_ALLOWED_CHAT_ID` | Recommended numeric owner ID; overrides username |

Optional: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_MAX_SEARCHES`,
`OPENAI_RESULTS_PER_SEARCH`, `OPENAI_TIMEOUT`, `SCRAPER_KEY`, `LOG_LEVEL`.

## Scheduling

Vercel runs scans at 09:00, 15:00 and 21:00 UTC. The GitHub workflow is manual
only, avoiding a duplicate 09:00 broadcast.

For a manual protected call:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://<DOMAIN>/api/scan"
```

## Job source policy

Prefer official APIs, RSS feeds, public employer ATS endpoints and licensed job
data providers. Do not scrape sources whose terms or robots policy prohibit it.
Keep source attribution and always link users to the original listing.

Good next source adapters include Adzuna, USAJOBS and country-specific public
employment portals. API credentials can be added independently without changing
the matching layer.

## Commands

- `/start` — onboarding
- `/find` — personalized jobs
- `/search waiter` — one-off search
- `/abroad UAE, Japan, Singapore, New Zealand` — turn on visa-first matching
- `/local` — turn off relocation mode
- `/autoapply` — owner-only Apply Agent; others get a DM link
- `/applications` — owner-only application review queue
- `/keywords` — update target roles
- `/saved` — bookmarks
- `/watch Company` — company watchlist
- `/status` — preferences
- `/stop` — pause alerts
- `/delete` — delete account data

## Before production

- Expand adapter and end-to-end webhook test coverage.
- Add a database-backed scan lock for horizontally concurrent invocations.
- Move long scans to a queue/worker if the source count grows substantially.
- Add source health, cost and job-expiry dashboards.
- Add audited ATS adapters and a durable browser worker before enabling any
  real cross-site submission. Keep final submission opt-in and user-approved.
- Verify every overseas offer and recruiting agent before sharing documents or
  money; the bot is a discovery tool, not an immigration adviser.
