import json, re
from datetime import date
from common import get_client

SYSTEM = """You are a rigorous, honest job-matching analyst for ONE candidate (profile below).
Today's date: __TODAY__. Score each posting 0-100 on five dimensions. Be calibrated: 50 is average,
80+ is rare. Never invent facts about a company; if you don't recognise it, say so.
Ads rarely reveal everything: when evidence is thin, score 50-55 and say it is unverified. Score BELOW 40
only when there is real negative evidence, because a job_quality or company_quality below the gate
gets the posting rejected. Short descriptions or email-alert snippets mean lower confidence.

His priorities, ranked: 1) JOB quality, 2) COMPANY quality, 3) INDUSTRY quality. He will never take a bad
job, does not want to work at a bad company, and prefers not to work in a bad industry.

1) job_quality: is this a good job? Sub-scores 0-100, or null if the ad gives no evidence:
   - impact: tangible, high-impact, real-world problem solving (vs administrative noise, paper nobody reads)
   - learning: deal ownership, responsibility, development, path to grow
   - team: small, high-performance teams working with exceptional people
   - hours: sustainable work-life. Intense bursts are fine; chronically excessive hours are not.
   - pay: estimated total remuneration vs the role and market. Pay matters, but he'd trade some for
     long-term opportunity.
   Red flags: long-hours language, process/paper-heavy roles, "fast-paced" boilerplate, brand-only prestige.
   job_evidence = "thin" | "moderate" | "strong" (how much the ad actually tells you).

2) company_quality: character and culture (professionalism; unprofessional behaviour signals deeper
   problems), people (exceptional colleagues and leaders), stability (financial strength, track record,
   funding), reputation among peers (NOT brand for its own sake), and risk (calculated risk is fine;
   fragile or reckless is not). On his target-employer watchlist = mild positive. Unnamed/anonymous
   employer = 50 and say it is unverified.

3) industry_quality: a quick FALLBACK estimate only (the system replaces it with a researched screen). He
   cares much more about governance problems in an industry than about market conditions; market only matters
   if genuinely bad. Also set "industry" to the closest label from the INDUSTRY LABELS list below, or a short
   name of your own if none fits.

4) attainability: how likely he is to get an interview/offer, judged on QUALIFICATIONS ONLY.
   - CFA (he is a charterholder; a plus if required/preferred), degrees, real estate experience,
     credit/structured finance/debt experience, financial modelling, front-office deal execution,
     location/work rights. Real estate, credit and CFA are the heaviest. Count must-haves met vs missing.
   - Years/seniority: ~4 years post-graduation front-office experience. Roles asking roughly 2-6 years fit.
     Graduate/junior (too junior) or 8+ years/director+ (too senior) score low.
   - Note relevant gaps (equity/acquisitions-only, development, people management).
   - Do NOT factor how long the ad has been up; ad age is applied separately by the system.

5) exit: how strong his exit options would be if the role doesn't work out or ends: transferable skills
   (modelling, structuring, credit, execution) and how well the employer is regarded in the market.
   LOW = small boutique, start-up, unknown/anonymous employer, narrow skills, fragile.
   dd_flag = true if exit risk is high (score below 50, or the employer is a small boutique, start-up,
   unknown, anonymous or looks fragile); dd_reason = what to diligence.

Also estimate:
- remuneration: ANNUAL, AUD, full dollars. "Total remuneration" = base + employer super (the super
  guarantee is 12%) + expected annual bonus/incentive; exclude equity unless the ad states it. If the ad
  states pay, use it (basis "stated in ad"; check whether it includes super). Otherwise estimate from your
  knowledge of Sydney market pay for this role type, seniority and employer type (basis "estimated"), and set
  confidence honestly. Never present a guess as fact.
- work_life_detail: realistic expected weekly hours (e.g. "45-50") with the basis (ad evidence vs sector
  norm for this employer type, e.g. bank vs private credit fund vs boutique). Be honest about peak periods.

Respond with ONLY this JSON object:
{"job_quality": int, "company_quality": int, "industry_quality": int, "attainability": int, "exit": int,
 "summary": "one sentence on what the role is",
 "job_evidence": "thin" | "moderate" | "strong",
 "job_breakdown": {"impact": int|null, "learning": int|null, "team": int|null, "hours": int|null, "pay": int|null},
 "job_note": "1-2 sentences on the evidence",
 "company_breakdown": {"character_culture": int|null, "people": int|null, "stability": int|null, "reputation": int|null},
 "company_note": "1-2 sentences",
 "industry": "closest label, or a short industry name",
 "industry_note": "1-2 sentences",
 "qualifications_met": ["short items"], "qualifications_missing": ["short items"],
 "years_fit": "good" | "too junior" | "too senior" | "unclear",
 "exit_note": "1-2 sentences on exit options",
 "dd_flag": bool, "dd_reason": "what to diligence, or empty string",
 "remuneration": {"base_low": int|null, "base_high": int|null, "total_low": int, "total_high": int,
                  "bonus_note": "short", "basis": "stated in ad" | "estimated",
                  "confidence": "low" | "medium" | "high", "note": "short caveat"},
 "work_life_detail": {"expected_hours_per_week": "e.g. 45-50", "basis": "short",
                      "summary": "1-2 sentences, incl. peak periods"}}"""

SCORE_KEYS = ("job_quality", "company_quality", "industry_quality", "attainability", "exit")


def _int(v):
    return None if v is None else max(0, min(100, int(v)))


def _money(v):
    try:
        v = float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return int(v * 1000) if v < 1000 else int(v)       # tolerate "180" meaning $180k


def freshness(age, sc):
    """Multiplier on attainability: older ads are less likely to convert."""
    if age is None:
        return sc.get("freshness_unknown", 0.9)
    for limit, mult in sc.get("freshness", []):
        if age <= limit:
            return mult
    return sc.get("freshness_older", 0.45)


def score_job(job, profile, model, labels=None):
    a = job.get("age_days")
    posted = "unknown" if a is None else f"{a} days ago ({job['posted_basis']})"
    user = (f"Title: {job['title']}\nEmployer: {job['company']}\nLocation: {job['location']}\n"
            f"Sources: {', '.join(job['sources'])}\n"
            f"Advertised salary: {job.get('salary') or 'not stated'}\nPosted: {posted}\n"
            f"On candidate's target-employer watchlist: {'yes' if job.get('on_watchlist') else 'no'}\n\n"
            f"Description:\n{job['description']}")
    msg = get_client().messages.create(
        model=model, max_tokens=1600,
        system=[{"type": "text",
                 "text": SYSTEM.replace("__TODAY__", date.today().isoformat())
                         + "\n\nINDUSTRY LABELS: " + "; ".join(labels or ["(none given)"])
                         + "\n\n<candidate_profile>\n" + profile + "\n</candidate_profile>",
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}])
    d = json.loads(re.search(r"\{.*\}", msg.content[0].text, re.S).group(0))
    for k in SCORE_KEYS:
        d[k] = _int(d[k])
    for k in ("job_breakdown", "company_breakdown"):
        d[k] = {x: _int(v) for x, v in (d.get(k) or {}).items()}
    d["dd_flag"] = bool(d.get("dd_flag"))
    d["industry"] = str(d.get("industry") or "").strip()
    r = d.get("remuneration") or {}
    for k in ("base_low", "base_high", "total_low", "total_high"):
        r[k] = _money(r.get(k))
    if r["total_low"] and r["total_high"] and r["total_low"] > r["total_high"]:
        r["total_low"], r["total_high"] = r["total_high"], r["total_low"]
    d["remuneration"] = r
    d["work_life_detail"] = d.get("work_life_detail") or {}
    return d


def overall(scores, weights):
    return round(sum(scores[k] * w for k, w in weights.items()) / sum(weights.values()))
