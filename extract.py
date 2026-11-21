"""Turns messy HTML (alert emails, careers pages) into job dicts using Claude."""
import json, re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import requests
from common import get_client, make_job, note


class _Parse(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.text, self._href, self._label, self._skip = [], [], None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            self._href, self._label = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href:
            label = " ".join(self._label).strip()
            if self._href.startswith("http") and label:
                self.links.append((label[:120], self._href))
            self._href = None

    def handle_data(self, d):
        if self._skip:
            return
        d = d.strip()
        if d:
            self.text.append(d)
            if self._href is not None:
                self._label.append(d)


PROMPT = """Extract the job listings from this {kind}. Return ONLY a JSON array (no prose).
Each item: {"title": str, "company": str, "location": str,
 "link_index": int (index of the link in LINKS that opens that job, else null),
 "salary": str ("" if none shown),
 "posted_days_ago": int|null (from text like 'Posted 2d ago', 'Listed today' = 0, 'New' = 0),
 "snippet": str (any description text shown for that job, else "")}
Only real job listings. Ignore footers, unsubscribe links, ads and job-search tips."""


def extract_jobs(html_text, source, model, kind="email", default_company="",
                 fallback_posted=None, fallback_basis="email alert date (ad may be older)"):
    p = _Parse()
    p.feed(html_text)
    links = p.links[:80]
    text = " ".join(p.text)[:12000]
    if len(text) < 200:
        return []
    link_block = "\n".join(f"{i}: {label}" for i, (label, _) in enumerate(links))
    msg = get_client().messages.create(
        model=model, max_tokens=4000,
        messages=[{"role": "user", "content":
                   PROMPT.replace("{kind}", kind) + f"\n\nTEXT:\n{text}\n\nLINKS:\n{link_block}"}])
    raw = msg.content[0].text
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    jobs = []
    for it in json.loads(m.group(0)):
        idx = it.get("link_index")
        url = links[idx][1] if isinstance(idx, int) and 0 <= idx < len(links) else None
        if not (it.get("title") and url):
            continue
        days = it.get("posted_days_ago")
        if isinstance(days, int):
            posted, basis = datetime.now(timezone.utc) - timedelta(days=days), "posted"
        else:
            posted, basis = fallback_posted, fallback_basis
        jobs.append(make_job(source, it["title"], it.get("company") or default_company,
                             it.get("location"), url, it.get("snippet"),
                             posted=posted, posted_basis=basis, salary=it.get("salary", "")))
    return jobs


def from_url(url, source, company, model):
    try:
        r = requests.get(url, headers={"User-Agent": "job-agent/1.0"}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        note(f"Careers page {company}: fetch failed ({e})")
        return []
    jobs = extract_jobs(r.text, source, model, kind="careers page", default_company=company,
                        fallback_posted=None, fallback_basis="posting date unknown")
    if not jobs:
        note(f"Careers page {company}: no jobs read (page may be JavaScript-rendered)")
    return jobs
