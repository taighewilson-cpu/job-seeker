"""Second pass on the top matches: live web research on the employer + application notes."""
import json, re
from common import get_client

RESEARCH_SYSTEM = """You are doing due diligence on an employer for a Sydney real estate credit/finance
professional deciding whether to apply. Use web search for the employer (4 searches max). Report ONLY what
you actually find; if you find nothing reliable, say "not found". Never guess or invent facts.
Look for: what the firm does, size (headcount, AUM/funds under management, funding or ownership),
stability and track record, recent news (growth, layoffs, leadership exits, controversies), staff/culture
signals (public review sentiment, turnover), whether the team/platform is a strong place to build a
career and exit from, and any market evidence of pay for this role.
After searching, respond with ONLY this JSON object:
{"employer_summary": "2 sentences: what they do and how big/stable",
 "recent_news": "1-2 sentences or 'not found'",
 "culture_signals": "1-2 sentences or 'not found'",
 "comp_evidence": "market pay evidence found, or ''",
 "company_adjustment": int between -25 and 15 (change to his company-quality score given what you found
   about stability, culture, people, reputation among peers; 0 if no new info),
 "exit_adjustment": int between -25 and 15 (change to his exit score; 0 if no new info),
 "dd_flag": bool, "dd_reason": "what he should still check, or ''"}"""


def _json(text):
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def search_json(model, system, user_text, max_searches=4, max_tokens=1500):
    """Run a web-search-enabled call and parse the JSON object it returns."""
    client = get_client()
    user = {"role": "user", "content": user_text}
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}]
    messages = [user]
    for _ in range(3):                                   # server-side search may pause long turns
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                      tools=tools, messages=messages)
        if resp.stop_reason != "pause_turn":
            break
        messages = [user, {"role": "assistant", "content": resp.content}]
    return _json("".join(b.text for b in resp.content if b.type == "text"))


def research(job, profile, model, max_searches=4):
    d = search_json(model, RESEARCH_SYSTEM,
                    f"Employer: {job['company']}\nRole: {job['title']}\nLocation: {job['location']}\n"
                    f"Ad summary: {job['scores'].get('summary', '')}", max_searches)
    for k in ("company_adjustment", "exit_adjustment"):
        d[k] = max(-25, min(15, int(d.get(k) or 0)))
    d["dd_flag"] = bool(d.get("dd_flag"))
    return d


APP_SYSTEM = """You help a candidate apply for a job. Use ONLY facts in his profile; never invent
experience, numbers or skills. Respond with ONLY this JSON object:
{"lead_with": ["3 resume points most relevant to this role, each one short line"],
 "address_gaps": ["how to honestly address each missing qualification/concern, short lines"],
 "pitch": "one-sentence pitch for the top of the cover note"}"""


def application_notes(job, profile, model):
    s = job["scores"]
    msg = get_client().messages.create(
        model=model, max_tokens=700,
        system=APP_SYSTEM + "\n\n<candidate_profile>\n" + profile + "\n</candidate_profile>",
        messages=[{"role": "user", "content":
                   f"Role: {job['title']} at {job['company']}\nSummary: {s.get('summary', '')}\n"
                   f"Missing: {s.get('qualifications_missing')}\nAd text:\n{job['description'][:2500]}"}])
    return _json(msg.content[0].text)
