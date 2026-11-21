"""Reads your SEEK / LinkedIn / Indeed / Jora alert emails from a Gmail label via IMAP."""
import email, imaplib, os
from email.utils import parsedate_to_datetime
from datetime import timezone
from common import note
from extract import extract_jobs


def _body(msg):
    html_part, text_part = None, None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            txt = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if ctype == "text/html" and html_part is None:
                html_part = txt
            elif ctype == "text/plain" and text_part is None:
                text_part = txt
    return html_part or (f"<p>{text_part}</p>" if text_part else "")


def _label(sender):
    s = (sender or "").lower()
    for name in ("seek", "linkedin", "indeed", "jora"):
        if name in s:
            return f"alert:{name}"
    return "alert:other"


def fetch_alert_jobs(cfg):
    a = cfg["sources"].get("email_alerts") or {}
    if not a.get("enabled"):
        return []
    user = os.getenv("IMAP_USER") or os.getenv("SMTP_USER")
    pw = os.getenv("IMAP_PASS") or os.getenv("SMTP_PASS")
    if not (user and pw):
        note("Alerts: no IMAP credentials, skipped")
        return []
    model, jobs = cfg["scoring"].get("extract_model", cfg["scoring"]["model"]), []
    try:
        M = imaplib.IMAP4_SSL(os.getenv("IMAP_HOST", "imap.gmail.com"))
        M.login(user, pw)
        typ, _ = M.select(f'"{a.get("folder", "job-alerts")}"')
        if typ != "OK":
            note(f"Alerts: folder '{a.get('folder')}' not found (create the Gmail label)")
            return []
        _, data = M.search(None, "UNSEEN")
        ids = data[0].split()[: a.get("max_emails", 30)]
        for num in ids:
            _, md = M.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(md[0][1])
            try:
                sent = parsedate_to_datetime(msg["Date"])
                sent = sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc)
            except Exception:
                sent = None
            try:
                jobs += extract_jobs(_body(msg), _label(msg.get("From")), model, kind="job-alert email",
                                     fallback_posted=sent)
                M.store(num, "+FLAGS", "\\Seen")          # only mark read once parsed OK
            except Exception as e:
                note(f"Alerts: could not parse one email ({e})")
        M.logout()
        note(f"Alerts: read {len(ids)} unread emails, found {len(jobs)} listings")
    except Exception as e:
        note(f"Alerts: IMAP failed ({e})")
    return jobs
