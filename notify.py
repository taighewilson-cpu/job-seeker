import html, os, smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

e = html.escape
JOB = {"impact": "Impact", "learning": "Learning", "team": "Team", "hours": "Hours", "pay": "Pay"}
CO = {"character_culture": "Character/culture", "people": "People", "stability": "Stability",
      "reputation": "Reputation"}


def _k(v):
    return "?" if v is None else f"${v / 1000:,.0f}k"


def _range(lo, hi):
    if lo is None and hi is None:
        return "n/a"
    if lo is None or hi is None or lo == hi:
        return _k(lo if lo is not None else hi)
    return f"{_k(lo)} - {_k(hi)}"


def _bd(d, labels):
    return " &middot; ".join(f"{labels[k]} {v}" for k, v in (d or {}).items()
                             if v is not None and k in labels) or "no evidence in ad"


def _age_badge(j):
    a, basis = j.get("age_days"), j.get("posted_basis", "")
    note = "" if basis == "posted" else f" [{basis}]"
    if a is None:
        return "#777", "Posting date unknown"
    when = "today" if a == 0 else f"{a} day{'s' if a != 1 else ''} ago"
    if a <= 2:
        return "#0a7", f"Posted {when}: apply now{note}"
    if a <= 7:
        return "#2a6fdb", f"Posted {when}{note}"
    if a <= 14:
        return "#c77700", f"Posted {when}: likelihood reduced{note}"
    return "#c0392b", f"Posted {when}: likelihood reduced a lot{note}"


def _job_html(j):
    s, r = j["scores"], j["scores"].get("remuneration", {})
    wl = s.get("work_life_detail", {})
    colour, badge = _age_badge(j)
    met = e(", ".join(s.get("qualifications_met", [])) or "none listed")
    miss = e(", ".join(s.get("qualifications_missing", [])) or "none")
    watch = ' <span style="background:#eef;padding:1px 6px;border-radius:4px;font-size:11px">target employer</span>' if j.get("on_watchlist") else ""
    thin = " (thin ad: unverified)" if s.get("job_evidence") == "thin" else ""
    adv = f"<br>Advertised: {e(j['salary'])}" if j.get("salary") else ""
    pay = (f'<div style="background:#f3f8f3;padding:8px;border-radius:6px;margin:8px 0">'
           f'<b>Total remuneration (est.): {_range(r.get("total_low"), r.get("total_high"))}</b> '
           f'incl. super &amp; expected bonus &middot; base {_range(r.get("base_low"), r.get("base_high"))}<br>'
           f'<span style="font-size:12px;color:#555">{e(str(r.get("basis", "estimated")))}, '
           f'{e(str(r.get("confidence", "low")))} confidence. {e(str(r.get("bonus_note", "")))} '
           f'{e(str(r.get("note", "")))}{adv}</span></div>')
    bal = (f'<p style="margin:6px 0"><b>Work-life:</b> ~{e(str(wl.get("expected_hours_per_week", "?")))} hrs/week '
           f'({e(str(wl.get("basis", "")))}). {e(str(wl.get("summary", "")))}</p>')
    dd = ""
    if s.get("dd_flag"):
        dd = ('<p style="margin:8px 0;padding:8px;background:#fff4e5;border-left:4px solid #e67e00">'
              f'<b>Further DD:</b> {e(s.get("dd_reason") or "High exit risk")}</p>')
    res = ""
    if j.get("research"):
        x = j["research"]
        res = ('<div style="background:#f5f5fa;padding:8px;border-radius:6px;margin:8px 0;font-size:13px">'
               f'<b>Employer research:</b> {e(x.get("employer_summary", ""))}<br>'
               f'<b>News:</b> {e(x.get("recent_news", ""))}<br>'
               f'<b>Culture signals:</b> {e(x.get("culture_signals", ""))}'
               + (f'<br><b>Pay evidence:</b> {e(x["comp_evidence"])}' if x.get("comp_evidence") else "")
               + "</div>")
    app = ""
    if j.get("application"):
        a = j["application"]
        li = lambda xs: "".join(f"<li>{e(str(i))}</li>" for i in xs or [])
        app = ('<div style="font-size:13px;margin:8px 0"><b>Application notes</b>'
               f'<br><i>{e(a.get("pitch", ""))}</i><br>Lead with:<ul style="margin:2px 0">{li(a.get("lead_with"))}</ul>'
               f'Address gaps:<ul style="margin:2px 0">{li(a.get("address_gaps"))}</ul></div>')
    scr, ind_red = j.get("industry_screen"), ""
    if scr:
        pen = f" (overall score cut {j['industry_penalty']} extra)" if j.get("industry_penalty") else ""
        ind = (f"<b>Industry ({e(j['industry_label'])}):</b> governance {e(scr['governance']['level'])}, "
               f"market {e(scr['market']['level'])}{pen}. {e(scr['summary'])}")
        if scr["governance"]["level"] in ("serious", "severe"):
            ind_red = ('<p style="margin:8px 0;padding:8px;background:#fdecea;border-left:4px solid #c0392b">'
                       f'<b>Industry red flag (governance, {e(scr["governance"]["level"])}):</b> '
                       f'{e(scr["governance"]["findings"])}</p>')
    else:
        ind = f"<b>Industry:</b> {e(s['industry_note'])} (not researched)"
    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin:14px 0;font-family:sans-serif;max-width:720px">
      <div style="font-size:12px;color:#888">{e(', '.join(j['sources']))}</div>
      <h3 style="margin:4px 0"><a href="{e(j['url'] or '#')}">{e(j['title'])}</a>
        <span style="float:right;color:#0a7">{j['overall']}</span></h3>
      <div>{e(j['company'])} &middot; {e(j['location'])}{watch}</div>
      <div style="color:{colour};font-weight:600;margin:4px 0">{e(badge)}</div>
      <div style="font-size:13px;color:#555;margin:6px 0">
        <b>Job {s['job_quality']}</b>{thin} &middot; <b>Company {s['company_quality']}</b>
        &middot; <b>Industry {s['industry_quality']}</b> &middot; <b>Likelihood {s['attainability']}</b>
        (quals {s['attainability_raw']} x freshness {j['freshness']}) &middot; <b>Exit {s['exit']}</b></div>
      <p style="margin:6px 0">{e(s['summary'])}</p>
      {pay}{bal}
      <p style="margin:6px 0"><b>Job:</b> {_bd(s.get('job_breakdown'), JOB)}<br>{e(s['job_note'])}</p>
      <p style="margin:6px 0"><b>Company:</b> {_bd(s.get('company_breakdown'), CO)}<br>{e(s['company_note'])}</p>
      <p style="margin:6px 0">{ind}</p>
      <p style="margin:6px 0"><b>Likelihood detail:</b> experience level: {e(s['years_fit'])}.
         Matches: {met}. Missing: {miss}.</p>
      <p style="margin:6px 0"><b>Exit:</b> {e(s['exit_note'])}</p>
      {ind_red}{dd}{res}{app}
    </div>"""


def build_html(jobs, stats=None, notes=None):
    stats, notes = stats or {}, notes or []
    rej = stats.get("rejected") or []
    head = (f'<p style="font-family:sans-serif;color:#555">{stats.get("fetched", 0)} listings fetched, '
            f'{stats.get("scored", 0)} new scored, {len(rej)} rejected as a bad job/company, '
            f'{len(jobs)} cleared your threshold.</p>')
    inds = stats.get("industries") or {}
    ind_html = ""
    if inds:
        rows = []
        for lab, r in sorted(inds.items()):
            gl, ml = r["governance"]["level"], r["market"]["level"]
            col = "#c0392b" if gl in ("serious", "severe") else ("#c77700" if gl == "isolated" else "#0a7")
            rows.append(f'<div style="margin:4px 0"><b>{e(lab)}</b>: governance '
                        f'<b style="color:{col}">{e(gl)}</b>, market {e(ml)}. {e(r["summary"])} '
                        f'<span style="color:#888">(as of {e(r.get("as_of", "?"))}, {e(r.get("confidence", "?"))} confidence)</span></div>')
        ind_html = ('<div style="font-family:sans-serif;font-size:13px;background:#f7f7f7;padding:10px;'
                    'border-radius:6px;max-width:720px"><b>Industry screen</b>' + "".join(rows) + "</div>")
    body = ind_html + "".join(_job_html(j) for j in jobs) or "<p>No new jobs cleared your score threshold today.</p>"
    rejected = ""
    if rej:
        rejected = ('<div style="font-family:sans-serif;font-size:12px;color:#777"><b>Rejected (check the gates '
                    'are right):</b><br>' + "<br>".join(
                        f"{e(r['title'])} at {e(r['company'])}: {e(r['reason'])}. {e(r['note'])}"
                        for r in rej[:10]) + "</div>")
    foot = ""
    if notes:
        foot = ('<hr><p style="font-family:sans-serif;font-size:12px;color:#888"><b>Run notes</b><br>'
                + "<br>".join(e(n) for n in notes) + "</p>")
    return head + body + rejected + foot


def send_email(jobs, stats=None, notes=None):
    user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job matches {date.today():%d %b}: {len(jobs)} new"
    msg["From"], msg["To"] = user, os.environ.get("EMAIL_TO", user)
    msg.attach(MIMEText(build_html(jobs, stats, notes), "html"))
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"), 465) as s:
        s.login(user, pw)
        s.send_message(msg)
