"""Internship funnel bot: polls job sources, filters, sends new matches to Telegram."""

import datetime
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "seen_jobs.json"
CFG = json.loads((ROOT / "companies.json").read_text())
HEADERS = {"User-Agent": "job-bot/1.0 (personal use)"}
MAX_MESSAGES = 30  # per run, avoids spam on first run

# ---------- FILTERS (edit these) ----------
LEVEL = re.compile(
    r"\b(intern|internship|trainee|junior|graduate|entry[- ]level|working student|apprentice|student|early career|new grad)\b",
    re.I,
)
ROLE = re.compile(
    r"devops|cloud|sre|site reliability|platform|infrastructure|sysadmin|system admin|linux|"
    r"network|backend|back-end|software|developer|engineer|it support|security|automation",
    re.I,
)
# Local (Skopje/Tetovo/Prishtina) roles often say just "DevOps Engineer" with ~1 year required.
# For those, accept core DevOps-type titles even without a level word, unless clearly senior.
ROLE_CORE = re.compile(
    r"devops|sre|site reliability|cloud|infrastructure|platform|sysadmin|system admin|systems engineer",
    re.I,
)
SENIOR = re.compile(
    r"senior|sr\.?\b|lead|principal|staff|head|manager|director|architect|\biii\b|\bii\b",
    re.I,
)
LOCAL = re.compile(
    r"tetovo|skopje|prishtina|pristina|kosovo|kosova|north macedonia|macedonia", re.I
)
EU_REMOTE = re.compile(
    r"europe|emea|\beu\b|worldwide|anywhere|global|north macedonia|kosovo", re.I
)


def classify(location, remote):
    """Return a tag if the location is acceptable, else None."""
    loc = (location or "").strip()
    if LOCAL.search(loc):
        return "📍 local (check on-site/hybrid)"
    if remote or re.search(
        r"remote|home[- ]?based|work from home|distributed", loc, re.I
    ):
        if EU_REMOTE.search(loc):
            return "🌍 remote (EU/worldwide)"
        if loc.lower() in ("", "remote", "anywhere"):
            return "🌍 remote (region unclear)"
    return None


# ---------- SOURCES ----------
def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r


def greenhouse(slug):
    for j in get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").json()[
        "jobs"
    ]:
        yield dict(
            title=j["title"],
            company=slug,
            url=j["absolute_url"],
            location=(j.get("location") or {}).get("name", ""),
            remote=False,
        )


def lever(slug):
    for j in get(f"https://api.lever.co/v0/postings/{slug}?mode=json").json():
        cats = j.get("categories") or {}
        loc = ", ".join(cats.get("allLocations") or [cats.get("location", "")])
        yield dict(
            title=j["text"],
            company=slug,
            url=j["hostedUrl"],
            location=loc,
            remote=j.get("workplaceType") == "remote",
        )


def ashby(slug):
    for j in get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json()[
        "jobs"
    ]:
        locs = [j.get("location", "")] + [
            s.get("location", "") if isinstance(s, dict) else str(s)
            for s in j.get("secondaryLocations") or []
        ]
        yield dict(
            title=j["title"],
            company=slug,
            url=j["jobUrl"],
            location=", ".join(l for l in locs if l),
            remote=bool(j.get("isRemote")),
        )


def weworkremotely():
    root = ET.fromstring(
        get(
            "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"
        ).content
    )
    for item in root.iter("item"):
        company, _, title = (item.findtext("title") or "").partition(": ")
        yield dict(
            title=title or company,
            company=company,
            url=item.findtext("link"),
            location=item.findtext("region") or "Remote",
            remote=True,
        )


def remotive(query):
    for j in get(f"https://remotive.com/api/remote-jobs?search={query}").json()["jobs"]:
        yield dict(
            title=j["title"],
            company=j["company_name"],
            url=j["url"],
            location=j.get("candidate_required_location", ""),
            remote=True,
        )


# ---------- STATE / NOTIFY ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen": {}, "last": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


def notify(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(text, "\n")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    r.raise_for_status()


def main():
    state = load_state()
    seen, last = state["seen"], state["last"]

    # (name, fetcher, min seconds between runs). Slow sources are throttled to be polite.
    sources = []
    for s in CFG.get("greenhouse", []):
        sources.append((f"gh:{s}", lambda s=s: greenhouse(s), 0))
    for s in CFG.get("lever", []):
        sources.append((f"lever:{s}", lambda s=s: lever(s), 0))
    for s in CFG.get("ashby", []):
        sources.append((f"ashby:{s}", lambda s=s: ashby(s), 0))
    sources.append(("wwr", weworkremotely, 3600))
    for q in CFG.get("remotive_queries", []):
        sources.append(
            (f"remotive:{q}", lambda q=q: remotive(q), 6 * 3600)
        )  # Remotive asks for few calls/day

    found = []
    failed = []
    for name, fn, gap in sources:
        if gap and time.time() - last.get(name, 0) < gap:
            continue
        try:
            jobs = list(fn())
        except Exception as e:
            print(f"[warn] {name} failed: {e}")
            failed.append(name)
            continue
        if gap:
            last[name] = time.time()
        level_ok = sum(1 for j in jobs if LEVEL.search(j["title"]))
        print(f"[info] {name}: {len(jobs)} jobs, {level_ok} intern/junior titles")
        for j in jobs:
            if not j["url"] or j["url"] in seen:
                continue
            if os.environ.get("DEBUG") and LEVEL.search(j["title"]):
                print(
                    f"[debug] {j['title']} | {j['location']} | role_ok={bool(ROLE.search(j['title']))} "
                    f"| loc={classify(j['location'], j['remote'])}"
                )
            title = j["title"]
            tag = classify(j["location"], j["remote"])
            if not tag:
                continue
            if LEVEL.search(title) and ROLE.search(title):
                pass
            elif (
                tag.startswith("📍")
                and ROLE_CORE.search(title)
                and not SENIOR.search(title)
            ):
                tag += " | no level in title, check requirements"
            else:
                continue
            found.append((tag, j))
            seen[j["url"]] = datetime.date.today().isoformat()

    for tag, j in found[:MAX_MESSAGES]:
        notify(f"{tag}\n{j['title']} @ {j['company']}\n{j['location']}\n{j['url']}")
    if len(found) > MAX_MESSAGES:
        notify(f"+{len(found) - MAX_MESSAGES} more new matches (check the run log).")

    if failed:
        print("[summary] failed sources (check slugs): " + ", ".join(failed))
    save_state(state)  # only reached if notifications succeeded
    print(f"Done. {len(found)} new matches.")


if __name__ == "__main__":
    main()
