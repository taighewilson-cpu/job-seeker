import os
import requests
from common import clean, make_job, note, parse_date
from extract import from_url
from alerts import fetch_alert_jobs

H = {"User-Agent": "job-agent/1.0"}


def fetch_adzuna(cfg):
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        note("Adzuna: keys missing, skipped")
        return []
    s, jobs = cfg["search"], []
    for kw in s["keywords"]:
        try:
            r = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/{s['country']}/search/1",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": 50, "what": kw,
                        "where": s.get("location", ""), "max_days_old": s.get("max_age_days", 7),
                        "sort_by": "date", "content-type": "application/json"},
                headers=H, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            note(f"Adzuna '{kw}' failed: {e}")
            continue
        for j in r.json().get("results", []):
            lo, hi = j.get("salary_min"), j.get("salary_max")
            sal = ""
            if lo or hi:
                sal = f"${(lo or hi):,.0f}" + (f" - ${hi:,.0f}" if lo and hi and hi != lo else "")
                if str(j.get("salary_is_predicted")) == "1":
                    sal += " (Adzuna's own prediction, not stated by employer)"
            jobs.append(make_job("adzuna", j.get("title"), j.get("company", {}).get("display_name"),
                                 j.get("location", {}).get("display_name"), j.get("redirect_url"),
                                 j.get("description"), posted=parse_date(j.get("created")), salary=sal))
    return jobs


def _greenhouse(token, name=None):
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                         params={"content": "true"}, headers=H, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        note(f"Greenhouse {token} failed: {e}")
        return []
    out = []
    for j in r.json().get("jobs", []):
        first = j.get("first_published")
        out.append(make_job("greenhouse", j["title"], name or token, j.get("location", {}).get("name"),
                            j["absolute_url"], j.get("content"),
                            posted=parse_date(first or j.get("updated_at")),
                            posted_basis="posted" if first else "last updated (may be older)"))
    return out


def _lever(token, name=None):
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"},
                         headers=H, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        note(f"Lever {token} failed: {e}")
        return []
    return [make_job("lever", j["text"], name or token, j.get("categories", {}).get("location"),
                     j["hostedUrl"], j.get("descriptionPlain"), posted=parse_date(j.get("createdAt")))
            for j in r.json()]


def fetch_watchlist(cfg):
    jobs = []
    model = cfg["scoring"].get("extract_model", cfg["scoring"]["model"])
    for w in cfg.get("watchlist") or []:
        name = w.get("name")
        if w.get("greenhouse"): jobs += _greenhouse(w["greenhouse"], name)
        if w.get("lever"): jobs += _lever(w["lever"], name)
        if w.get("careers_url"): jobs += from_url(w["careers_url"], f"careers:{name}", name, model)
    return jobs


def fetch_all(cfg):
    src, jobs = cfg["sources"], []
    if src.get("adzuna"): jobs += fetch_adzuna(cfg)
    jobs += fetch_watchlist(cfg)
    jobs += fetch_alert_jobs(cfg)
    return jobs
