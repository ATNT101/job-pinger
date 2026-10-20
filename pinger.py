#!/usr/bin/env python3
"""
Job Pinger: watches bank / boutique / pension career sites, LinkedIn and
Simplify for summer 2027 finance internships and summer 2028 IB roles,
then pings your phone (ntfy) and Gmail the moment something new shows up.

Usage:
  python pinger.py            # one pass (what GitHub Actions runs)
  python pinger.py --doctor   # test every source, print a health table
  python pinger.py --dry-run  # one pass, print matches, send nothing, save nothing
  python pinger.py --test-alert  # send a fake ping to check your phone/email
"""
import html as htmllib
import json
import os
import re
import smtplib
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
HEALTH_FILE = STATE_DIR / "health.json"
META_FILE = STATE_DIR / "meta.json"
FOUND_FILE = ROOT / "FOUND.md"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
TIMEOUT = 25
from zoneinfo import ZoneInfo
TORONTO = ZoneInfo("America/Toronto")

# ───────────────────────── classification ─────────────────────────

INTERN = re.compile(r"\b(intern|interns|internship|summer|placement|co-?op|off[- ]cycle|"
                    r"insight|spring week|stagiaire|stage|vacation scheme)\b", re.I)
IB = re.compile(r"investment bank|\bIBD?\b|\bM\s?&\s?A\b|mergers|advisory|capital markets|"
                r"\bDCM\b|\bECM\b|leveraged finance|restructuring|corporate finance|"
                r"global banking|financial sponsors|corporate & investment|corporate and investment|"
                r"\bCIB\b|\bGBM\b|summer analyst|summer financial analyst", re.I)
FIN = re.compile(r"markets|sales\s?(&|and)\s?trading|trading|equity research|research analyst|"
                 r"asset management|investment|private equity|credit|fixed income|treasury|"
                 r"wealth|portfolio|valuation|transaction|deals|assurance|audit|accounting|"
                 r"risk|finance|financial|banking|fund|pension|infrastructure|"
                 r"corporate development|real estate|economics|actuarial", re.I)
EXCLUDE = re.compile(r"software|engineer|developer|data scien|machine learning|\bAI\b|cyber|"
                     r"technology(?! investment)|\bIT\b|marketing|human resources|\bHR\b|"
                     r"nurs|branch|teller|customer|graphic|design|legal|paralegal|"
                     r"data analyst|business analyst|systems analyst|product|operations|supply chain|procurement|"
                     r"compliance|anti[- ]money|\bAML\b|fraud|payroll|"
                     r"apprentice|\bphd\b|\bmba\b|vice president|director|"
                     r"full[- ]?time|experienced|graduate programme|graduate program|new analyst|"
                     r"winter|fall 20|autumn|spring 20", re.I)
HARD_EXCLUDE = re.compile(r"software|engineer|developer|data scien|machine learning|quality assurance|"
                          r"\bQA\b|cyber|devops|technician", re.I)
# off-cycle / term-time / insight events: dropped unless the title also says summer
NOT_SUMMER = re.compile(r"off[- ]?cycle|winter|fall 20|fall term|autumn|spring 20|spring week|spring insight|"
                        r"insight|discovery (day|program)|open day|january 20|september 20|long[- ]term|year[- ]long|"
                        r"\b([4-9]|1[0-2])(\.5)?\s?[-–]?\s?months?\b|\b[4-6]\s?[-–]\s?6\s?months?\b|jan(uary)?\s?[-–]\s?jun|jul(y)?\s?[-–]\s?dec", re.I)
SENIOR = re.compile(r"\b(vice president|director|managing|\bVP\b|senior|lead|head of|full[- ]?time|associate|"
                    r"actuarial|women in|women's|for women)\b", re.I)

REGIONS = {
    "canada": r"canada|toronto|montr[eé]al|vancouver|calgary|ottawa|waterloo|halifax|\bON\b|\bQC\b|\bBC\b|\bAB\b|ontario|quebec",
    "apac": r"hong kong|singapore|shanghai|beijing|shenzhen|tokyo|seoul|sydney|melbourne|mumbai|"
            r"taipei|manila|kuala lumpur|jakarta|bangkok|apac|asia|china|japan|australia|\bHK\b|\bSG\b",
    "europe": r"london|united kingdom|\bUK\b|england|scotland|edinburgh|leeds|manchester|birmingham|"
              r"dublin|ireland|paris|france|frankfurt|germany|madrid|spain|milan|italy|amsterdam|"
              r"netherlands|zurich|geneva|switzerland|stockholm|brussels|luxembourg|warsaw|emea|europe|"
              r"glasgow|knutsford|canary wharf|belfast|cardiff|bristol|northampton|poland|krak[oó]w|prague|"
              r"lisbon|portugal|vienna|austria|copenhagen|denmark|oslo|norway|helsinki|athens|budapest|bucharest",
    # regions you never want; listed so "unknown" places from these get rejected
    "other": r"mexico|brazil|s[aã]o paulo|buenos aires|argentina|chile|santiago|colombia|bogot[aá]|\bperu\b|"
             r"tel aviv|israel|dubai|abu dhabi|\bUAE\b|saudi|riyadh|qatar|doha|bahrain|kuwait|"
             r"johannesburg|south africa|cape town|lagos|nigeria|nairobi|kenya|cairo|egypt|casablanca|morocco|"
             r"latam|latin america|middle east|\bMENA\b|pune|chennai|bengaluru|bangalore|hyderabad|gurugram|gurgaon|noida|kolkata",
    "us": r"new york|nyc|\bNY\b|chicago|san francisco|boston|charlotte|houston|dallas|los angeles|"
          r"atlanta|miami|minneapolis|\bUSA?\b|united states|washington|"
          r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b",
}


def summer_year(title):
    """Return 2027 / 2028 / None (unknown) / -1 (old, reject)."""
    t = title
    # "Class of 2029" = graduating 2029 = summer 2028 internship
    m = re.search(r"class of\s*(20\d\d)", t, re.I)
    if m:
        return int(m.group(1)) - 1 if int(m.group(1)) - 1 >= 2027 else -1
    yrs = [int(y) for y in re.findall(r"\b(20[2-3]\d)\b", t)]
    yrs += [2000 + int(y) for y in re.findall(r"['’](2[6-9])\b", t)]
    if not yrs:
        return None
    good = [y for y in yrs if y in (2027, 2028)]
    if good:
        return min(good) if 2027 in good and 2028 in good else good[0]
    return -1 if max(yrs) < 2027 else None


def classify(job, cfg):
    """Return (keep, track, priority, why). track in {'IB-2028','2027','?'}."""
    title = job["title"]
    blob = f"{title} {job.get('company','')}"
    if SENIOR.search(title):
        return False, None, 0, "senior"
    yr = summer_year(title)
    if yr == -1:
        return False, None, 0, "old year"
    is_ib = bool(IB.search(blob))
    is_fin = is_ib or bool(FIN.search(title))
    looks_intern = bool(INTERN.search(title)) or yr in (2027, 2028)
    if not looks_intern or not is_fin:
        return False, None, 0, "not finance internship"
    if HARD_EXCLUDE.search(title):
        return False, None, 0, "excluded keyword"
    if EXCLUDE.search(title) and not re.search(r"investment bank|\bM\s?&\s?A\b|capital markets|global markets", title, re.I):
        return False, None, 0, "excluded keyword"
    # keep 2028 IB insight/early-ID events (they feed the internship); drop other non-summer stuff
    if NOT_SUMMER.search(title) and not re.search(r"summer", title, re.I) and not (yr == 2028 and is_ib):
        return False, None, 0, "not summer"
    if not region_ok(f"{job.get('location', '')} | {title}", cfg["regions"]):
        return False, None, 0, "region"
    big = is_big(job.get("company", "") + " " + job.get("source", ""), cfg)
    if yr == 2028 and is_ib:
        return True, "IB-2028", 5, "2028 IB"
    if yr == 2028:
        return True, "2028", 4, "2028 finance"
    if yr == 2027:
        return True, "2027", 4 if (big or is_ib) else 3, "2027 finance"
    # no year in title: only keep if it's clearly summer + finance at a real shop
    if re.search(r"summer", title, re.I) and (big or is_ib):
        return True, "?", 3, "summer, year not stated"
    return False, None, 0, "no year"


def region_ok(loc, regions):
    if not loc or not loc.strip(" |"):
        return True
    for r in regions:
        if re.search(REGIONS[r], loc, re.I):
            return True
    # unknown places (e.g. "Multiple Locations", "Remote") pass; known other regions fail
    for r, pat in REGIONS.items():
        if r not in regions and re.search(pat, loc, re.I):
            return False
    return True


def is_big(text, cfg):
    for n in cfg["big_names"]:
        if re.search(r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])", text, re.I):
            return True
    return False


# ───────────────────────── sources ─────────────────────────

def job(source, title, url, location="", company=None, jid=None, posted=""):
    title = re.sub(r"^XMLNAME[-\s]*", "", htmllib.unescape(title or "")).strip()
    return {"id": jid or url, "source": source, "company": company or source,
            "title": " ".join(title.split()), "url": url,
            "location": " ".join((location or "").split()), "posted": posted}


def fetch_workday(src, cfg):
    out = {}
    api = f"https://{src['host']}/wday/cxs/{src['tenant']}/{src['site']}/jobs"
    base = f"https://{src['host']}/en-US/{src['site']}"
    for q in cfg.get("workday_searches", ["intern"]):
        for offset in (0, 20):
            r = S.post(api, json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q},
                       headers={"Accept": "application/json", "Content-Type": "application/json"},
                       timeout=TIMEOUT)
            r.raise_for_status()
            posts = r.json().get("jobPostings", [])
            for p in posts:
                path = p.get("externalPath", "")
                jid = f"wd:{src['tenant']}:{(p.get('bulletFields') or [path])[0]}"
                out[jid] = job(src["name"], p.get("title"), base + path, p.get("locationsText", ""),
                               jid=jid, posted=p.get("postedOn", ""))
            if len(posts) < 20:
                break
            time.sleep(0.4)
    return list(out.values())


def fetch_greenhouse(src, cfg):
    r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{src['token']}/jobs", timeout=TIMEOUT)
    r.raise_for_status()
    return [job(src["name"], j["title"], j["absolute_url"], (j.get("location") or {}).get("name", ""),
                jid=f"gh:{src['token']}:{j['id']}") for j in r.json().get("jobs", [])]


def fetch_lever(src, cfg):
    r = S.get(f"https://api.lever.co/v0/postings/{src['token']}?mode=json", timeout=TIMEOUT)
    r.raise_for_status()
    return [job(src["name"], j["text"], j["hostedUrl"], (j.get("categories") or {}).get("location", ""),
                jid=f"lv:{src['token']}:{j['id']}") for j in r.json()]


def fetch_oracle_hcm(src, cfg):
    out = {}
    for kw in src.get("keywords", ["intern"]):
        url = (f"https://{src['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               f"?onlyData=true&expand=requisitionList.secondaryLocations"
               f"&finder=findReqs;siteNumber={src['site']},keyword=%22{quote(kw)}%22,"
               f"limit=50,sortBy=POSTING_DATES_DESC")
        r = S.get(url, headers={"Accept": "application/json"}, timeout=TIMEOUT)
        r.raise_for_status()
        for item in r.json().get("items", []):
            for j in item.get("requisitionList", []):
                jid = f"or:{src['host']}:{j['Id']}"
                link = f"https://{src['host']}/hcmUI/CandidateExperience/en/sites/{src['site']}/job/{j['Id']}"
                out[jid] = job(src["name"], j.get("Title"), link, j.get("PrimaryLocation", ""),
                               jid=jid, posted=j.get("PostedDate", ""))
    return list(out.values())


LINKISH = re.compile(r"intern|summer|analyst|placement|co-?op|off[- ]cycle|2027|2028|programme|program", re.I)


def fetch_html(src, cfg):
    r = S.get(src["url"], timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if 8 <= len(text) <= 200 and LINKISH.search(text):
            url = urljoin(src["url"], a["href"]).split("#")[0]
            if url.rstrip("/") == src["url"].rstrip("/"):
                continue
            out[url] = job(src["name"], text, url)
    if src.get("link_pattern"):
        for url in set(re.findall(src["link_pattern"], r.text)):
            url = urljoin(src["url"], url)
            if url not in out and url.rstrip("/") != src["url"].rstrip("/"):
                slug = url.rstrip("/").split("/")[-1]
                title = re.sub(r"[-_]+", " ", slug)
                out[url] = job(src["name"], title, url)
    return list(out.values())


def fetch_linkedin_one(query, location):
    url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
           f"?keywords={quote(query)}&location={quote(location)}&f_TPR=r604800&sortBy=DD&start=0")
    r = S.get(url, timeout=TIMEOUT)
    if r.status_code == 429:
        raise RuntimeError("LinkedIn rate-limited (429)")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for card in soup.select("li"):
        t = card.select_one(".base-search-card__title, h3")
        a = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        if not t or not a:
            continue
        c = card.select_one(".base-search-card__subtitle, h4")
        loc = card.select_one(".job-search-card__location")
        tm = card.select_one("time")
        href = a["href"].split("?")[0]
        m = re.search(r"(\d{8,})", href)
        jid = f"li:{m.group(1)}" if m else href
        company = c.get_text(" ", strip=True) if c else "LinkedIn"
        out.append(job("LinkedIn", t.get_text(" ", strip=True), href,
                       loc.get_text(" ", strip=True) if loc else location,
                       company=company, jid=jid, posted=tm.get("datetime", "") if tm else ""))
    return out


def fetch_linkedin(src, cfg, meta):
    li = cfg["linkedin"]
    combos = []
    for q in li.get("urgent_queries", []):
        for loc in li["locations"]:
            combos.append((q, loc))
    urgent = list(combos)
    for q in li.get("queries", []):
        for loc in li["locations"]:
            combos.append((q, loc))
    combos = urgent + combos  # urgent ones appear twice per cycle
    cur = meta.get("linkedin_cursor", 0) % len(combos)
    picks = [combos[(cur + i) % len(combos)] for i in range(li.get("per_pass", 6))]
    meta["linkedin_cursor"] = (cur + len(picks)) % len(combos)
    out = []
    for n, (q, loc) in enumerate(picks):
        try:
            out += fetch_linkedin_one(q, loc)
        except RuntimeError:
            if n == 0:
                raise
            break  # rate-limited mid-pass: keep what we have, retry the rest next pass
        time.sleep(3)
    return out


def fetch_simplify(src, cfg):
    r = S.get(cfg["simplify"]["url"], timeout=60)
    r.raise_for_status()
    out = []
    cutoff = time.time() - 14 * 86400
    for j in r.json():
        if not j.get("active") or not j.get("is_visible", True):
            continue
        if (j.get("date_posted") or 0) < cutoff:
            continue
        terms = " ".join(j.get("terms") or [])
        if not re.search(r"2027|2028", terms):
            continue
        title = j["title"]
        if not re.search(r"20\d\d", title):
            title = f"{title} ({terms})"
        out.append(job("Simplify", title, j["url"], "; ".join(j.get("locations") or []),
                       company=j.get("company_name"), jid=f"sim:{j['id']}"))
    return out


# ───────────────────────── alerts ─────────────────────────

def ntfy(title, message, priority=3, click=None, tags=None):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    body = {"topic": topic, "title": title[:250], "message": message[:3500],
            "priority": priority, "tags": tags or []}
    if click:
        body["click"] = click
        body["actions"] = [{"action": "view", "label": "Apply now", "url": click}]
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    try:
        requests.post(server, json=body, timeout=15)
    except Exception as e:
        print("ntfy failed:", e)


def email(subject, html_body):
    clean = lambda v: re.sub(r"[\s\u00a0\u200b]+", "", v or "")  # app passwords get pasted with (non-breaking) spaces
    user, pw = clean(os.environ.get("GMAIL_ADDRESS")), clean(os.environ.get("GMAIL_APP_PASSWORD"))
    to = clean(os.environ.get("ALERT_EMAIL_TO")) or user
    if not user or not pw:
        return
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Job Pinger <{user}>", to
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
    except Exception as e:
        print("email failed:", e)


def jobs_table(jobs):
    rows = []
    for j in jobs:
        badge = {"IB-2028": "🚨 2028 IB", "2028": "2028", "2027": "2027", "?": "year?"}[j["track"]]
        star = "⭐ " if j["big"] else ""
        rows.append(
            f"<tr><td style='padding:6px 10px'><b>{badge}</b></td>"
            f"<td style='padding:6px 10px'>{star}{htmllib.escape(j['company'])}</td>"
            f"<td style='padding:6px 10px'><a href='{htmllib.escape(j['url'])}'>{htmllib.escape(j['title'])}</a></td>"
            f"<td style='padding:6px 10px;color:#666'>{htmllib.escape(j['location'] or '')}</td>"
            f"<td style='padding:6px 10px;color:#999'>{htmllib.escape(j['source'])}</td></tr>")
    return ("<table style='border-collapse:collapse;font-family:-apple-system,Arial;font-size:14px'>"
            "<tr style='background:#f2f2f2'><th>Track</th><th>Firm</th><th>Role</th><th>Location</th><th>Found via</th></tr>"
            + "".join(rows) + "</table>")


def sort_key(j):
    return (-j["priority"], not j["big"], j["company"])


def alert_new(new):
    new.sort(key=sort_key)
    for j in new[:12]:
        prefix = "🚨 2028 IB OPEN: " if j["track"] == "IB-2028" else ("⭐ " if j["big"] else "")
        ntfy(f"{prefix}{j['company']}", f"{j['title']}\n{j['location']}\nvia {j['source']}",
             priority=j["priority"], click=j["url"],
             tags=["rotating_light"] if j["track"] == "IB-2028" else ["briefcase"])
    if len(new) > 12:
        ntfy(f"+{len(new) - 12} more new postings", "Full list is in your email.", priority=3)
    urgent = any(j["track"] == "IB-2028" for j in new)
    subj = (f"🚨 2028 IB posting live + {len(new) - 1} more" if urgent and len(new) > 1 else
            "🚨 2028 IB posting live" if urgent else
            f"{len(new)} new internship posting{'s' if len(new) > 1 else ''}: {new[0]['company']}")
    email(subj, f"<p>New since the last check ({datetime.now(TORONTO):%b %d %I:%M %p} Toronto):</p>"
                + jobs_table(new) + "<p style='color:#888'>Apply early. Most of these are rolling.</p>")


# ───────────────────────── state ─────────────────────────

def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save(path, data):
    STATE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True))


def append_found(new):
    lines = []
    if not FOUND_FILE.exists():
        lines.append("# Found postings (newest first)\n\n| When (UTC) | Track | Firm | Role | Location |\n|---|---|---|---|---|\n")
        existing = ""
    else:
        existing = FOUND_FILE.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    rows = "".join(f"| {now} | {j['track']} | {j['company']} | [{j['title'].replace('|', '/')}]({j['url']}) | {j['location'].replace('|', '/')} |\n"
                   for j in sorted(new, key=sort_key))
    if existing:
        head, sep, rest = existing.partition("|---|---|---|---|---|\n")
        FOUND_FILE.write_text(head + sep + rows + rest)
    else:
        FOUND_FILE.write_text(lines[0] + rows)


# ───────────────────────── main ─────────────────────────

def all_sources(cfg):
    for kind in ("workday", "greenhouse", "lever", "oracle_hcm", "html"):
        for src in cfg.get(kind) or []:
            yield kind, src
    if cfg.get("linkedin"):
        yield "linkedin", {"name": "LinkedIn"}
    if cfg.get("simplify"):
        yield "simplify", {"name": "Simplify"}


FETCHERS = {"workday": fetch_workday, "greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "oracle_hcm": fetch_oracle_hcm, "html": fetch_html, "simplify": fetch_simplify}


def run(doctor=False, dry=False):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    seen = load(SEEN_FILE, {})
    health = load(HEALTH_FILE, {})
    meta = load(META_FILE, {})
    bootstrap = "_bootstrapped" not in seen and not doctor and not dry
    now = time.time()
    every = cfg.get("every_min", {})
    found, report, rejected = [], [], []

    for kind, src in all_sources(cfg):
        key = f"{kind}:{src['name']}"
        h = health.setdefault(key, {"fails": 0, "last_ok": None, "last_run": 0, "alerted": False})
        if not doctor and not bootstrap and now - h.get("last_run", 0) < every.get(kind, 0) * 60 - 30:
            continue
        h["last_run"] = now
        try:
            jobs = fetch_linkedin(src, cfg, meta) if kind == "linkedin" else FETCHERS[kind](src, cfg)
            kept = 0
            for j in jobs:
                ok, track, prio, why = classify(j, cfg)
                if ok:
                    j.update(track=track, priority=prio, big=is_big(j["company"] + " " + j["source"], cfg))
                    found.append(j)
                    kept += 1
                elif doctor and why not in ("not finance internship",) and INTERN.search(j["title"]):
                    rejected.append((why, j))
            if h["fails"] >= 6 and h.get("alerted") and not dry:
                ntfy(f"✅ {src['name']} is back", "Source recovered.", priority=2)
            h.update(fails=0, last_ok=datetime.now(timezone.utc).isoformat(timespec="minutes"), alerted=False,
                     last_count=len(jobs))
            report.append((key, "OK", len(jobs), kept, ""))
        except Exception as e:
            h["fails"] = h.get("fails", 0) + 1
            h["last_error"] = str(e)[:200]
            report.append((key, "FAIL", 0, 0, str(e)[:120]))
            # only alert on sources that have worked before (so unverified ones stay quiet)
            if h["fails"] == 6 and h.get("last_ok") and not h.get("alerted") and not dry and not doctor:
                ntfy(f"⚠️ {src['name']} stopped responding", str(e)[:300], priority=2, tags=["warning"])
                h["alerted"] = True
        time.sleep(0.3)

    # dedupe within run (same posting found by several sources)
    uniq = {}
    for j in found:
        k = j["id"]
        if k not in uniq:
            uniq[k] = j
    fresh = [j for j in uniq.values() if j["id"] not in seen]
    # also dedupe by company+title so LinkedIn and the bank's own site don't double-ping
    seen_titles = {v.get("t") for v in seen.values() if isinstance(v, dict)}
    out, titles_this_run = [], set()
    for j in fresh:
        tkey = re.sub(r"\W+", "", (j["company"] + j["title"]).lower())[:120]
        if tkey in seen_titles or tkey in titles_this_run:
            seen[j["id"]] = {"d": datetime.now(timezone.utc).date().isoformat(), "t": tkey}
            continue
        titles_this_run.add(tkey)
        j["tkey"] = tkey
        out.append(j)

    if doctor or dry:
        print(f"\n{'SOURCE':45} {'STATUS':6} {'FETCHED':>8} {'MATCHED':>8}  NOTE")
        for key, st, n, k, note in report:
            print(f"{key[:45]:45} {st:6} {n:>8} {k:>8}  {note}")
        print(f"\n{len(uniq)} matching postings total, {len(out)} would be NEW:\n")
        for j in sorted(out, key=sort_key):
            print(f"  [{j['track']:7}] {'*' if j['big'] else ' '} {j['company'][:28]:28} | {j['title'][:80]} | {j['location'][:40]}")
        if doctor and rejected:
            print(f"\nRejected internship-looking titles (sample, for checking the filters):")
            shown = set()
            for why, j in rejected:
                k = (j["company"], j["title"])
                if k in shown or len(shown) >= 150:
                    continue
                shown.add(k)
                print(f"  ({why:14}) {j['company'][:28]:28} | {j['title'][:80]} | {j['location'][:40]}")
        return

    today = datetime.now(timezone.utc).date().isoformat()
    for j in out:
        seen[j["id"]] = {"d": today, "t": j["tkey"]}

    if bootstrap:
        ok_n = sum(1 for r in report if r[1] == "OK")
        bad = [r for r in report if r[1] == "FAIL"]
        out.sort(key=sort_key)
        health_html = ("<h3>Source health</h3><p>" + f"{ok_n} sources working, {len(bad)} not responding"
                       + (": " + ", ".join(htmllib.escape(r[0]) for r in bad) if bad else "") + "</p>")
        email(f"Job Pinger is live: {len(out)} matching roles already open",
              "<p>Here is everything that matches <b>right now</b>. From here on you only get pinged for new postings.</p>"
              + jobs_table(out) + health_html)
        ntfy("Job Pinger is live ✅",
             f"Watching {ok_n} sources. {len(out)} matching roles are already open; full list in your email.",
             priority=4, tags=["white_check_mark"])
        if out:
            append_found(out)
        seen["_bootstrapped"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    elif out:
        alert_new(out)
        append_found(out)

    # daily heartbeat ~8am Toronto so you know it's alive
    local = datetime.now(TORONTO)
    if not bootstrap and local.hour >= 8 and meta.get("heartbeat") != local.date().isoformat():
        meta["heartbeat"] = local.date().isoformat()
        bad = [k for k, v in health.items() if v.get("fails", 0) >= 6 and v.get("last_ok")]
        new_24h = sum(1 for v in seen.values() if isinstance(v, dict) and v.get("d") == today)
        up = sum(1 for v in health.values() if v.get("fails", 0) == 0 and v.get("last_ok"))
        ntfy("Job Pinger: still watching", f"{up} sources up"
             + (f", down: {', '.join(bad)[:200]}" if bad else "") + f". {new_24h} new today.",
             priority=1, tags=["eyes"])

    # prune entries older than 200 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=200)).date().isoformat()
    seen = {k: v for k, v in seen.items() if not isinstance(v, dict) or v.get("d", today) >= cutoff}
    save(SEEN_FILE, seen)
    save(HEALTH_FILE, health)
    save(META_FILE, meta)
    print(f"done: {len(out)} new, {sum(1 for r in report if r[1]=='OK')} ok, "
          f"{sum(1 for r in report if r[1]=='FAIL')} failed")


if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        sample = [{"track": "IB-2028", "priority": 5, "big": True, "company": "Test Bank",
                   "title": "2028 Investment Banking Summer Analyst (TEST)", "location": "Toronto, ON",
                   "url": "https://example.com", "source": "test"}]
        alert_new(sample)
        print("sent test alert")
    else:
        run(doctor="--doctor" in sys.argv, dry="--dry-run" in sys.argv)