import json, os, re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import yaml
from common import NOTES, age_days, norm, note
from sources import fetch_all
from scorer import freshness, overall, score_job
from research import application_notes, research
from industry import canon, industry_score, screen_industries
from notify import send_email

SEEN_FILE = "seen.json"


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    d = json.load(open(SEEN_FILE))
    if isinstance(d, list):
        d = {i: date.today().isoformat() for i in d}
    cutoff = (date.today() - timedelta(days=120)).isoformat()
    return {k: v for k, v in d.items() if v >= cutoff}


def build_profile():
    p = open("profile.md").read()
    if os.path.exists("feedback.yaml"):
        fb = yaml.safe_load(open("feedback.yaml")) or {}
        lines = [f"- {lab}: {x}" for lab, key in (("LIKED", "liked"), ("DISLIKED", "disliked"))
                 for x in fb.get(key) or []]
        if lines:
            p += "\n\n## Calibration from past emails (learn his taste)\n" + "\n".join(lines)
    return p


def _rank(j):
    return (not j["source"].startswith("alert:"), len(j["description"]))


def merge(jobs):
    """Same job from several boards -> one record, keeping the fullest text and the oldest known date."""
    out = {}
    for j in jobs:
        if not j["title"]:
            continue
        cur = out.get(j["id"])
        if not cur:
            out[j["id"]] = j
            continue
        best, other = (j, cur) if _rank(j) > _rank(cur) else (cur, j)
        best["sources"] = sorted(set(best["sources"] + other["sources"]))
        dated = [x for x in (best, other) if x["posted"]]
        if dated:
            real = [x for x in dated if x["posted_basis"] == "posted"] or dated
            oldest = min(real, key=lambda x: x["posted"])
            best["posted"], best["posted_basis"] = oldest["posted"], oldest["posted_basis"]
        best["salary"] = best["salary"] or other["salary"]
        out[j["id"]] = best
    return list(out.values())


def title_ok(job, s):
    t = job["title"].lower()
    inc, exc = s.get("title_include") or [], s.get("title_exclude") or []
    if inc and not any(re.search(p, t) for p in inc):
        return False
    return not any(re.search(p, t) for p in exc)


def apply_scores(job, sc, ic):
    s = job["scores"]
    job["freshness"] = freshness(job["age_days"], sc)
    s["attainability"] = round(s["attainability_raw"] * job["freshness"])
    # Governance red flags in the industry cost extra points on top of the weighted industry score.
    job["industry_penalty"] = (ic.get("overall_penalty") or {}).get(job.get("industry_gov_level"), 0)
    job["overall"] = max(0, overall(s, sc["weights"]) - job["industry_penalty"])
    s["dd_flag"] = bool(s.get("dd_flag_model") or s.get("dd_flag_research")
                        or s["exit"] < sc.get("dd_flag_below", 50))
    # Hard gates, in his order of priority: never a bad job, not a bad company.
    if s["job_quality"] < sc["gate_job_below"]:
        job["gate"], job["gate_note"] = "bad job", s.get("job_note", "")
    elif s["company_quality"] < sc["gate_company_below"]:
        job["gate"], job["gate_note"] = "bad company", s.get("company_note", "")
    else:
        job["gate"], job["gate_note"] = None, ""


def main():
    cfg = yaml.safe_load(open("config.yaml"))
    sc, search, rc, ic = cfg["scoring"], cfg["search"], cfg.get("research") or {}, cfg.get("industry") or {}
    profile = build_profile()
    watch = [norm(w["name"]) for w in cfg.get("watchlist") or [] if w.get("name")]
    seen = load_seen()

    raw = fetch_all(cfg)
    jobs = merge(raw)
    fresh = []
    for j in jobs:
        a = age_days(j["posted"])
        if j["id"] in seen or not title_ok(j, search):
            continue
        if a is not None and a > search.get("max_ad_age_days", 45):
            continue
        fresh.append(j)
    fresh.sort(key=lambda j: age_days(j["posted"]) if j["posted"] else 30)   # freshest first
    fresh = fresh[: sc["max_jobs_per_run"]]
    print(f"{len(raw)} fetched, {len(jobs)} unique, {len(fresh)} new to score")

    def run(job):
        try:
            c = norm(job["company"])
            job["on_watchlist"] = bool(c) and any(w in c or c in w for w in watch)
            job["age_days"] = age_days(job["posted"])
            s = score_job(job, profile, sc["model"], ic.get("labels"))
            s["attainability_raw"], s["dd_flag_model"] = s["attainability"], s["dd_flag"]
            job["scores"] = s
            return job
        except Exception as ex:
            note(f"Scoring failed for '{job['title']}': {ex}")
            return None

    with ThreadPoolExecutor(4) as pool:
        scored = [j for j in pool.map(run, fresh) if j]

    # Industry screen: one researched, cached screen per industry (governance >> market conditions)
    screens = {}
    if ic.get("enabled") and scored:
        screens = screen_industries([j["scores"]["industry"] for j in scored if j["scores"]["industry"]], ic)
    for j in scored:
        s, scr = j["scores"], screens.get(j["scores"]["industry"])
        j["industry_label"] = canon(s["industry"], ic.get("labels")) or "unspecified"
        if scr:
            s["industry_quality_model"], s["industry_quality"] = s["industry_quality"], industry_score(scr, ic)
            j["industry_screen"], j["industry_gov_level"] = scr, scr["governance"]["level"]
        apply_scores(j, sc, ic)

    # Second pass on the best candidates: live employer research (+ optional application notes)
    if rc.get("enabled"):
        top = sorted((j for j in scored if not j["gate"] and j["overall"] >= sc["min_score"] - 5),
                     key=lambda j: -j["overall"])[: rc.get("top_n", 5)]
        for j in top:
            try:
                r = research(j, profile, rc["model"], rc.get("max_searches", 4))
                j["research"], s = r, j["scores"]
                s["exit"] = max(0, min(100, s["exit"] + r["exit_adjustment"]))
                s["company_quality"] = max(0, min(100, s["company_quality"] + r["company_adjustment"]))
                s["dd_flag_research"] = r["dd_flag"]
                if r["dd_flag"] and r.get("dd_reason"):
                    s["dd_reason"] = r["dd_reason"]
                apply_scores(j, sc, ic)
            except Exception as ex:
                note(f"Research failed for '{j['title']}': {ex}")
            if rc.get("application_notes") and not j["gate"]:
                try:
                    j["application"] = application_notes(j, profile, sc["model"])
                except Exception as ex:
                    note(f"Application notes failed for '{j['title']}': {ex}")

    matches = sorted((j for j in scored if not j["gate"] and j["overall"] >= sc["min_score"]),
                     key=lambda j: -j["overall"])[: sc["top_n_in_email"]]
    rejected = [{"title": j["title"], "company": j["company"], "reason": j["gate"], "note": j["gate_note"]}
                for j in scored if j["gate"]]
    industries = {j["industry_label"]: j["industry_screen"] for j in matches if j.get("industry_screen")}
    send_email(matches, {"fetched": len(raw), "scored": len(scored), "rejected": rejected,
                         "industries": industries}, NOTES)
    print(f"Emailed {len(matches)} matches")

    for j in scored:                                   # saved only after the email succeeds
        seen[j["id"]] = date.today().isoformat()
    json.dump(seen, open(SEEN_FILE, "w"), indent=0)


if __name__ == "__main__":
    main()
