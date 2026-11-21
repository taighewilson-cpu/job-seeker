import hashlib, html, re
from datetime import datetime, timezone

_client = None
NOTES = []          # run-health messages, shown at the bottom of the email


def get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def note(msg):
    print(msg)
    NOTES.append(msg)


def clean(text, limit=3500):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


_SUFFIX = re.compile(r"\b(pty|ltd|limited|group|australia|aus|holdings|inc|llc|the)\b")
_ANON = {"", "confidential", "privateadvertiser", "anonymous", "unknown"}


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", _SUFFIX.sub(" ", (s or "").lower()))


def parse_date(v):
    if not v:
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def age_days(posted):
    if not posted:
        return None
    return max(0, (datetime.now(timezone.utc) - posted).days)


def make_job(source, title, company, location, url, desc, posted=None,
             posted_basis="posted", salary=""):
    """The id is company+title so the same job from different boards merges into one."""
    key = norm(company) + "|" + norm(title)
    if norm(company) in _ANON:
        key += "|" + (url or "")
    return {"id": hashlib.sha1(key.encode()).hexdigest()[:16], "source": source,
            "sources": [source], "title": (title or "").strip(), "company": (company or "").strip(),
            "location": location or "", "url": url, "description": clean(desc),
            "posted": posted, "posted_basis": posted_basis, "salary": salary or ""}
