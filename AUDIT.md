# Super Job Bot — A–Z Audit

## Current product

The project is a Telegram-first job discovery bot with:

- local, hybrid, remote and worldwide matching;
- hospitality-to-director job categories;
- 12+ scraper/API/ATS sources plus optional OpenAI web discovery;
- visa-first relocation filtering;
- saved jobs, feedback, watchlists and scheduled alerts;
- an owner-only, review-first Apply Agent.

## User experience after simplification

### Regular user

1. `/start`
2. Enter target role
3. Pick level
4. Pick location
5. Receive matches

Startup/established company selection was removed from new onboarding because
it added friction and many listings do not contain reliable company-type data.

Regular users do not see application-preparation buttons. Auto Apply surfaces
explain that it is a private beta and link directly to `@Harsimarhs`.

### `@Harsimarhs`

1. `/autoapply`
2. Accept the privacy notice and upload a resume
3. Add application contact details
4. Matching jobs enter `/applications`
5. Prepare, approve, open the employer form, then mark submitted

The bot never reports a submission merely because a URL was opened.

## Issues fixed in this audit

- Locked Apply Agent commands, callbacks, resume uploads and scheduled queuing
  to the configured owner.
- Added an optional numeric chat-ID lock, stronger than username matching.
- Made Telegram webhook-secret validation mandatory.
- Made cron bearer-secret validation mandatory.
- Added webhook payload-size protection.
- Hid Apply controls from regular users and added a direct owner-DM route.
- Reduced onboarding from four decisions to three.
- Made `/find` start setup directly for new users.
- Fixed **Resume Alerts** so it resumes instead of restarting onboarding.
- Added a user-confirmed **Mark as Submitted** state.
- Fixed visa false positives such as “we do not sponsor” and normalized
  hyphenated wording.
- Parallelized bounded OpenAI discovery calls.
- Added explicit Vercel function durations and excluded tests from bundles.
- Aligned the default bot username with the landing-page Telegram link.
- Verified desktop semantics and 390 px responsive layout with no overflow.

## Required deployment configuration

Do not deploy without these:

- `JOB_BOT_TOKEN`
- `BOT_USERNAME=RemoteJobsAlertBot` (change if the real bot differs)
- `SUPABASE_URL`
- server-side Supabase `service_role` key in `SUPABASE_KEY`
- `CRON_SECRET`
- `TELEGRAM_WEBHOOK_SECRET`
- `AUTO_APPLY_OWNER_USERNAME=Harsimarhs`
- preferably `AUTO_APPLY_ALLOWED_CHAT_ID=<numeric owner chat ID>`

Run `supabase_schema.sql`, redeploy, then register the webhook using the same
`TELEGRAM_WEBHOOK_SECRET`.

## Remaining limitations

### Before public Auto Apply

- It prepares a draft and opens the employer form; it does not yet fill and
  submit arbitrary websites.
- Resume contents are not parsed, so the draft uses only candidate-entered
  facts and the job description.
- Real automation needs a durable browser worker, encrypted resume storage,
  audited Greenhouse/Lever/Ashby adapters, CAPTCHA handoff and submission
  receipts.

### Reliability

- The scheduled scan still runs as one serverless invocation. A durable queue
  and database-backed scan lock should be added as usage grows.
- Job sources can change or fail. Add a source-health dashboard and expiry job.
- Review each source's API terms before commercial/public scale.

### Code structure

`api/webhook.py` is still the largest maintenance risk. `process_update` should
eventually be split into command routing, callback routing, onboarding,
applications and Telegram transport modules. This is an internal refactor; it
should not delay testing the current private beta.

### Trust and compliance

- Add a privacy policy, retention period and explicit resume-delete command
  before inviting public Apply Agent users.
- Visa support is a listing-text filter, not legal or immigration advice.
- Never request payment from candidates or guarantee a visa/job outcome.
