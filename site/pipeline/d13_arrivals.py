"""D13 arrivals: the wells that appeared in FracFocus's download since the last one, and which of them a state agency's daily report had already carried.

`d13_newwells.py` rebuilds the whole map from the registry's disclosure list on every run. This module answers the question a daily run adds: what is new since the last download?
It compares today's wells (the first ten digits of an API number are the key, as everywhere in D13) with the list of wells kept from the previous download, and counts the ones that were not
there. That list is one API number a line in a gzip file the workflow keeps in GitHub's Actions cache; it is never committed and never under `site/public` (the site's data files carry no API
number). A run with no list (the first, or after the cache expired) keeps today's as the baseline and reports no arrivals: it says so instead of calling every well new.

A new well is also checked against the state agencies' daily reports, so it is not reported twice. Only Texas's day files (`data/daily/`) carry wells: each approved permit row and each
directional survey row has the well's API number (without the state's `42`), so a Texas arrival whose API number is in the archive's permits or surveys is counted as already reported.
Oklahoma's and New Mexico's day files hold counts by county and operator, not wells, so nothing can be matched for them: their arrivals say `null` (not checked), never a zero.

What is published is counts only: `data/newwells/arrivals.json`, by arrival day and state: wells found, how many of them a state report already carried (or null), and how many
wells that were in the last download are gone from this one (an operator's correction or a deletion); and how many wells, from which day, the Texas match covered (`against`: the archive's
day files from before the nightly captures were rebuilt from the monthly master without API numbers, so the match starts on the first night captured live and grows by about 85 wells a night;
a well is usually fractured months after its permit, so a match is rare at first). No API number, well name or lease.
"""
import gzip
import json
import os
import re
from datetime import date

SEEN_MIN = 100000  # a list shorter than this is not a previous download of the registry (it holds about 239,000 wells): treated as no baseline
KEEP_DAYS = 60  # days of arrivals the file keeps
MATCHABLE = ("TX",)  # the states whose daily reports carry wells (the others carry counts only)
API_PREFIX = {"TX": "42"}  # the state's API code: a day file's 8-digit API is the county and the well's own number
NAME = "arrivals.json"


# ------------------------------------------------------------------------------------------------ the list kept from the last download

def load_seen(path, min_rows=SEEN_MIN):
    """The set of API numbers kept from the previous download, or None when there is none (missing, unreadable, or too short to be one)."""
    if not path or not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="ascii") as f:
            seen = {line.strip() for line in f if re.fullmatch(r"\d{10}", line.strip())}
    except (OSError, EOFError, ValueError):
        return None
    return seen if len(seen) >= min_rows else None


def write_seen(path, apis):
    """Writes the list (sorted, one a line, no timestamp: the same wells give the same bytes)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=9) as z:
            z.write(("\n".join(sorted(apis)) + "\n").encode("ascii"))
    os.replace(tmp, path)


# ------------------------------------------------------------------------------------------------ what the state agencies' daily reports carried

def read_texas(daily_dir):
    """(the API numbers (ten digits) of the wells Texas's daily reports carry, the first day that carried any): every approved-permit row and every directional-survey row of every day file in
    the archive. A day rebuilt from the monthly master has permit rows without an API number, so only the nights captured live (from 2026-10-30) count: the match covers those days."""
    out, first_day = set(), None
    if not daily_dir or not os.path.isdir(daily_dir):
        return out, first_day
    for name in sorted(os.listdir(daily_dir)):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d\.json", name):
            continue
        try:
            with open(os.path.join(daily_dir, name), encoding="utf-8") as f:
                rep = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rep, dict):
            continue
        before = len(out)
        for rows, at in (((rep.get("permits") or {}).get("rows"), 7), ((rep.get("surveys") or {}).get("rows"), 0)):
            for r in rows if isinstance(rows, list) else []:
                api = r[at] if isinstance(r, list) and len(r) > at else None
                if isinstance(api, str) and re.fullmatch(r"\d{8}", api):
                    out.add(API_PREFIX["TX"] + api)
        if len(out) > before and first_day is None:
            first_day = name[:10]
    return out, first_day


def reported_texas(daily_dir):
    return read_texas(daily_dir)[0]


# ------------------------------------------------------------------------------------------------ the comparison

def find(first, seen, reported, day):
    """The day's arrivals: `first` maps API number -> a well's record whose second item is its state; `seen` is the last download's set, `reported` the Texas set.
    Returns an entry {day, found, removed, states: [[id, found, already reported or None]]}, or None when there is nothing to compare with."""
    if seen is None:
        return None
    found, carried = {}, {}
    for api, rec in first.items():
        if api in seen:
            continue
        st = rec[1]
        found[st] = found.get(st, 0) + 1
        if st in MATCHABLE and api in reported:
            carried[st] = carried.get(st, 0) + 1
    removed = sum(1 for api in seen if api not in first)
    states = sorted(([st, n, (carried.get(st, 0) if st in MATCHABLE else None)] for st, n in found.items()), key=lambda r: (-r[1], r[0]))
    return {"day": day, "found": sum(found.values()), "removed": removed, "states": states}


def _add(a, b):
    """Two entries of one day (a second run the same day finds only what the first did not): the counts add; a state not checked stays not checked."""
    by = {s[0]: list(s) for s in a["states"]}
    for st, n, rep in b["states"]:
        if st in by:
            by[st][1] += n
            by[st][2] = None if rep is None or by[st][2] is None else by[st][2] + rep
        else:
            by[st] = [st, n, rep]
    states = sorted(by.values(), key=lambda r: (-r[1], r[0]))
    return {"day": a["day"], "found": a["found"] + b["found"], "removed": a["removed"] + b["removed"], "states": states}


def update(old, entry, day, against=None):
    """The new document from the committed one (None when the file does not exist yet), today's entry (None when there was no baseline) and today's date.
    A day with arrivals gets an entry (added to the day's earlier one); a comparison with nothing found only moves `checked`.
    `against` says what the state match covered on this run: {"TX": {"wells": n, "from": first day with API numbers or None}} (kept as it was when not given)."""
    doc = {"v": 1, "checked": old.get("checked") if old else None, "since": old.get("since") if old else None, "against": (against if against is not None else (old or {}).get("against") or {}),
           "days": list(old.get("days", [])) if old else []}
    if entry is None:
        return doc
    doc["checked"] = day
    doc["since"] = doc["since"] or day
    if entry["found"] or entry["removed"]:
        same = [d for d in doc["days"] if d["day"] == entry["day"]]
        merged = _add(same[0], entry) if same else entry
        doc["days"] = sorted([d for d in doc["days"] if d["day"] != entry["day"]] + [merged], key=lambda d: d["day"], reverse=True)[:KEEP_DAYS]
    return doc


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------ validation

def validate(doc, today=None, states=None):
    """Problems with an arrivals document (counts only, newest day first, a state's reported count only for a state whose daily report carries wells)."""
    import privacy_check
    p = []
    today = today or date.today()
    if not isinstance(doc, dict) or doc.get("v") != 1:
        return ["arrivals: not a v1 document"]
    for k in ("checked", "since"):
        v = doc.get(k)
        if v is not None and not (isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", v) and v <= today.isoformat()):
            p.append("arrivals: %s must be a date not in the future, or null" % k)
    ag = doc.get("against")
    if not isinstance(ag, dict) or any(k not in MATCHABLE or not isinstance(v, dict) or not (isinstance(v.get("wells"), int) and not isinstance(v.get("wells"), bool) and v["wells"] >= 0)
                                       or not (v.get("from") is None or (isinstance(v.get("from"), str) and re.fullmatch(r"\d{4}-\d\d-\d\d", v["from"]) and v["from"] <= today.isoformat())) for k, v in ag.items()):
        p.append("arrivals: against must say, for a state whose daily report carries wells, how many wells it was matched against and from which day: %r" % (ag,))
    days = doc.get("days")
    if not (isinstance(days, list) and len(days) <= KEEP_DAYS):
        return p + ["arrivals: days must be a list of at most %d" % KEEP_DAYS]
    seen = []
    for d in days:
        if not (isinstance(d, dict) and isinstance(d.get("day"), str) and re.fullmatch(r"\d{4}-\d\d-\d\d", d["day"]) and d["day"] <= today.isoformat()):
            p.append("arrivals: a day needs a date")
            continue
        seen.append(d["day"])
        ints = all(isinstance(d.get(k), int) and not isinstance(d.get(k), bool) and 0 <= d[k] < 100000 for k in ("found", "removed"))
        rows = d.get("states")
        if not (ints and isinstance(rows, list)):
            p.append("arrivals %s: found, removed and states must be counts and a list" % d["day"])
            continue
        total = 0
        for r in rows:
            ok = isinstance(r, list) and len(r) == 3 and isinstance(r[0], str) and isinstance(r[1], int) and not isinstance(r[1], bool) and r[1] > 0
            if not ok or (states is not None and r[0] not in states):
                p.append("arrivals %s: a state row is [id, found, reported or null]: %r" % (d["day"], r))
                continue
            total += r[1]
            if r[0] in MATCHABLE:
                if not (isinstance(r[2], int) and not isinstance(r[2], bool) and 0 <= r[2] <= r[1]):
                    p.append("arrivals %s %s: reported must be a count not above found" % (d["day"], r[0]))
            elif r[2] is not None:
                p.append("arrivals %s %s: that state's daily report carries no wells, so reported must be null, never a count" % (d["day"], r[0]))
        if total != d["found"]:
            p.append("arrivals %s: the states add to %d, not found %d" % (d["day"], total, d["found"]))
    if seen != sorted(seen, reverse=True) or len(set(seen)) != len(seen):
        p.append("arrivals: days must be unique, newest first")
    for what in privacy_check.scan(json.dumps(doc, ensure_ascii=False), digits=True):
        p.append("arrivals hold " + what)
    return p
