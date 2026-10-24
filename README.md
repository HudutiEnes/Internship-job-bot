# Internship funnel bot

Polls Greenhouse / Lever / Ashby company boards + WeWorkRemotely + Remotive,
filters by level + role + location, sends new matches to Telegram.
Runs free on GitHub Actions. State (seen_jobs.json) is committed back to the repo.

## Setup

### 1. Telegram bot
1. Telegram -> search @BotFather -> `/newbot` -> copy the **token**.
2. Open your new bot and send it any message (e.g. "hi").
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser.
   Find `"chat":{"id":123456789` -> that number is your **chat id**.

### 2. Test locally (optional)
    pip install -r requirements.txt
    export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...
    python job_bot.py
Without the env vars it just prints matches to the terminal.

### 3. GitHub
1. Create a repo, push these files (keep the `.github/workflows` folder).
2. Repo -> Settings -> Secrets and variables -> Actions -> New repository secret:
   `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Repo -> Settings -> Actions -> General -> Workflow permissions -> **Read and write**.
4. Actions tab -> job-bot -> **Run workflow** to test. After that it runs by itself.

### Minutes / cost
- **Public repo: unlimited free minutes.** Secrets stay private; only companies.json and seen_jobs.json are visible.
- Private repo: 2000 free min/month. Every 15 min is roughly 2900 runs/month, so use `*/30` or go public.
- Scheduled runs are best-effort: expect delays of 5-20 min sometimes.
- GitHub pauses scheduled workflows on repos with no activity for 60 days. Check the Actions tab now and then.

## Adding companies
Open a company's careers page and look at where "Apply" goes:
- `boards.greenhouse.io/SLUG` or `job-boards.greenhouse.io/SLUG` -> add SLUG under "greenhouse"
- `jobs.lever.co/SLUG` -> "lever"
- `jobs.ashbyhq.com/SLUG` -> "ashby"
Wrong slugs just log a warning and are skipped.

## Tuning
Edit the regexes at the top of `job_bot.py`: LEVEL (intern/junior...), ROLE (devops/cloud...), LOCAL (cities), EU_REMOTE.
Matching is on the job **title** only. If you get junk, tighten ROLE. If you miss things, loosen it.

## Not included (on purpose)
Local boards (kariera.mk, kosovajob.com): no API, markup changes break scrapers. Add them after v1 works,
or just use their email alerts. LinkedIn: use its built-in alerts, don't scrape.
