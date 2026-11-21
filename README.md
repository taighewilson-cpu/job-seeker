# Daily Job Agent

Every morning it gathers jobs, scores them with Claude and emails the best ones.

**Your ranking: job quality > company quality > industry quality.** Each posting is scored on:
job quality, company quality, industry quality, likelihood (resume vs requirements, then reduced for
older ads) and exit risk. There are two hard gates: a bad job or a bad company is rejected outright
(listed under "Rejected" in the email so you can sanity-check). Each job also shows an estimated total
remuneration and expected hours. The top matches get live employer research (which can raise or lower
company quality and exit).

## Industry screen
Each industry your jobs fall into (e.g. private credit) is researched with live web search and cached for a
week (`industry.refresh_days`). It looks at **governance** (fraud, opaque valuations, regulator action, frozen
redemptions) and **market conditions**. Governance is weighted far more heavily: a serious governance problem
cuts the industry score by 30 points and takes extra points off the job's overall score, while bubble talk or
cyclical softness costs almost nothing. Market conditions only bite if they are genuinely bad. The penalties
are all in `config.yaml` under `industry`, and the email opens with a short industry screen plus a red flag
on any affected job.

## Setup (about 30 minutes)
1. Create a **private** GitHub repo and push this folder (it contains your essay and resume facts).
2. Fill in the "Industry views" lines at the bottom of `profile.md`.
3. Keys: Anthropic API key (console.anthropic.com), Adzuna id/key (developer.adzuna.com, free),
   Gmail app password (myaccount.google.com/apppasswords, needs 2FA).
4. Repo > Settings > Secrets and variables > Actions, add:
   `ANTHROPIC_API_KEY, ADZUNA_APP_ID, ADZUNA_APP_KEY, SMTP_USER, SMTP_PASS, EMAIL_TO`
   (the same Gmail login reads alerts; optionally add IMAP_USER / IMAP_PASS for a different inbox).
5. **Email alerts (SEEK + LinkedIn first; Indeed optional; skip Jora, it mostly duplicates the others):**
   - On each site, save a search (e.g. "real estate credit", Sydney) with a **daily** email alert.
   - In Gmail, create a label `job-alerts` and a filter that applies it to those senders.
   - The agent reads unread emails in that label, extracts the jobs, and marks them read.
6. Actions tab > "Daily job search" > Run workflow to test. It then runs daily.

## Run locally
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=... ADZUNA_APP_ID=... ADZUNA_APP_KEY=... SMTP_USER=... SMTP_PASS=...
    python main.py

## Tuning (all in config.yaml)
- Too many rejections / too few: `gate_job_below`, `gate_company_below`.
- Too many/few emailed jobs: `min_score`, `top_n_in_email`. Priorities: `scoring.weights`.
- Ad-age curve: `scoring.freshness` (ads over 45 days old are dropped).
- Cost: lower `max_jobs_per_run` / `research.top_n`, or `research.enabled: false`.
- Teach it your taste: add lines to `feedback.yaml`. Target employers: `watchlist`.

## Honest limitations
- Ads rarely reveal job or company quality. When the evidence is thin, the agent scores about 50-55 and
  says "unverified" instead of rejecting. Rejection needs real negative evidence.
- Pay and hours are estimates unless the ad states them. Check the confidence label.
- Employer research is only as good as what web search finds; unknown firms get a DD flag.
- Alert emails give short snippets and the date they arrived (the ad may be older).
- Careers pages that load via JavaScript may return nothing (the email footer tells you).
