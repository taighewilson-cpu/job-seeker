"""Industry screen: current news on governance (heavily weighted) and market conditions (lightly weighted).
Each industry is researched once and cached, so it costs little."""
import json, os
from datetime import date, timedelta
from common import note
from research import search_json

CACHE = "industry_cache.json"

SYSTEM = """You are screening an INDUSTRY for a candidate choosing a career in Sydney, Australia.
Today's date: __TODAY__. Use web search (prefer the last 6-12 months) to find what a careful person should know about
this industry right now, in two categories:

GOVERNANCE (weighted heavily): fraud, misvalued or opaquely valued assets, conflicts of interest,
regulator investigations or enforcement (ASIC, APRA, SEC and similar), redemption freezes/gating, fund or
firm failures, auditor problems, whistleblowers, loss of investor trust, sector-wide concerns about
transparency or valuation practices.
MARKET (weighted lightly): downturns, defaults, funding stress, bubble talk, valuation worries, structural
decline.

Every industry has bad news, so judge relative to normal. Governance problems are MUCH worse than market
problems. Market conditions matter only if genuinely bad; bubble talk, valuation worries and cyclical
softness are minor. Judge the industry as named, and include any parent/adjacent-sector problems that
directly apply (for example, issues in private credit generally apply to private real estate credit).
Report ONLY what you actually find, with dates; never invent. If you find little, say so and set confidence low.

Levels:
- governance: "clean" = nothing beyond normal background noise; "isolated" = one-off incidents at individual
  firms, no sector-wide pattern; "serious" = multiple firms and/or regulator scrutiny or sector-wide concerns
  about valuation, transparency, conflicts or redemptions; "severe" = systemic misconduct or collapses, major
  enforcement, investor trust badly damaged.
- market: "fine"; "choppy" = cyclical softness, valuation/bubble worries, slower deal flow; "weak" = sustained
  downturn but the sector is functioning; "genuinely bad" = collapse, mass defaults/insolvencies or
  structural decline.

Respond with ONLY this JSON object:
{"industry": str,
 "governance": {"level": "clean"|"isolated"|"serious"|"severe", "findings": "1-3 sentences with specifics and dates, or 'none found'"},
 "market": {"level": "fine"|"choppy"|"weak"|"genuinely bad", "findings": "1-2 sentences"},
 "outlook": "one sentence on durability of demand for real estate credit/finance skills here",
 "summary": "2 sentences: the headline he should know",
 "confidence": "low"|"medium"|"high"}"""


def canon(label, labels):
    label = (label or "").strip()
    for x in labels or []:
        if x.lower() == label.lower():
            return x
    return label


def _load():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def _screen(label, ic):
    from datetime import date as _d
    r = search_json(ic["model"], SYSTEM.replace("__TODAY__", _d.today().isoformat()),
                    f"Industry to screen: {label}", ic.get("max_searches", 4), max_tokens=1500)
    gl, ml = r["governance"]["level"].strip().lower(), r["market"]["level"].strip().lower()
    if gl not in ic["governance_penalty"] or ml not in ic["market_penalty"]:
        raise ValueError(f"unexpected levels: {gl}/{ml}")
    r["governance"]["level"], r["market"]["level"] = gl, ml
    r["confidence"] = str(r.get("confidence", "low")).lower()
    r["as_of"] = date.today().isoformat()
    return r


def industry_score(r, ic):
    """Governance counts far more than market. Low-confidence screens count half."""
    pen = ic["governance_penalty"][r["governance"]["level"]] + ic["market_penalty"][r["market"]["level"]]
    if r.get("confidence") == "low":
        pen *= 0.5
    return max(0, min(100, round(ic.get("base", 80) - pen)))


def screen_industries(labels, ic):
    """Returns {label: screen}. Reuses cached screens younger than refresh_days."""
    cache, out = _load(), {}
    cutoff = (date.today() - timedelta(days=ic.get("refresh_days", 7))).isoformat()
    canon_of = {l: canon(l, ic.get("labels")) for l in set(labels) if l}
    todo = []
    for c in sorted(set(canon_of.values())):
        hit = cache.get(c)
        if hit and hit["screened"] >= cutoff:
            out[c] = hit["result"]
        else:
            todo.append(c)
    for c in todo[: ic.get("max_screens_per_run", 8)]:
        try:
            r = _screen(c, ic)
            cache[c] = {"screened": date.today().isoformat(), "result": r}
            out[c] = r
        except Exception as e:
            note(f"Industry screen failed for '{c}': {e}")
            if c in cache:                                   # a stale screen beats none
                out[c] = cache[c]["result"]
                note(f"Industry '{c}': using older screen from {cache[c]['screened']}")
    for c in todo[ic.get("max_screens_per_run", 8):]:
        note(f"Industry '{c}': not screened this run (cap reached)")
    json.dump(cache, open(CACHE, "w"), indent=1)
    return {l: out[c] for l, c in canon_of.items() if c in out}
