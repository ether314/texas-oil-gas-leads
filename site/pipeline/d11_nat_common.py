#!/usr/bin/env python3
"""D11: what every state's producer shares, for the national report of the Oil tracker.

Each state agency publishes its permits in its own way. A producer (d11_nat_<st>.py) reads one agency's files and hands every permit it finds to a
`Tally`; the tally writes ONE small file, site/public/data/nat/<ST>.json, in the shape below, and d11_nat_build.py merges those files (and the
four jurisdictions built earlier: Texas, Oklahoma, New Mexico, the federal offshore) into site/public/data/national.json, which the National view reads.

The shape of nat/<ST>.json (v1):
  state, name, agency            who publishes it
  measure                        'permits' (counted by the day the agency approved or issued the permit) or 'spuds' (wells counted by their spud date,
                                 for agencies that publish no approval dates by well); figures of the two measures are never added together
  basis                          the date the counts are by, in words: 'approval date', 'issue date', 'filing date', 'spud date'
  source                         {name, url}: the file or service read
  asOf                           the newest record's day; through: the last day of the newest complete month shown (a spud-counting state ends later by its lag)
  cadence                        how often the agency refreshes the source
  months                         'YYYY-MM' from 2019-01 to through, no gaps
  bands                          {band: [count per month] or null}; null means the source cannot tell that band (never zero). `new` is always present.
  fluid                          the last 12 months of `new` by the well's recorded fluid {oil, gas, both, other, unknown}, or null where the state does not record it
  counties                       [[name, count]]: the top 15 places by `new` in the last 12 months
  operators                      [[name, count]]: the top 15 operators by `new` in the last 12 months, corporations, LLCs and partnerships only (the naming rule)
  namedShare                     the share of the last 12 months' `new` permits whose operator may be named
  read                           how many records the source gave (a sanity figure)
  note                           anything a reader should know (a lag, a revision, a limit)

The bands (a permit is in exactly one):
  new      a new well drilled to produce or explore (oil, gas, wildcat, development)
  inj      a new injection, disposal, storage or other service well
  redrill  a re-entry, deepening, sidetrack or re-drill of an existing well
  rework   a recompletion, plug-back, workover, conversion or change of zone
  amend    an amendment, revision, extension or transfer of an approved permit
  other    anything else the agency files as a permit

Rules every producer follows (CLAUDE.md): public business-, place- and market-level data only (no person's name, phone, street address, API number, lease
or well name leaves a producer); a polite client (a refusal is an answer: `Refused`, never retried; downloads capped in size); files are parsed, never run;
no TLS verification is ever switched off; a failure leaves the committed file alone. Standard library only; run producers with `python3 -I`.
"""
import calendar
import collections
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d8_ok_daily as D8  # noqa: E402  (the one naming rule: a corporation, LLC or partnership, never a person's dba)
import privacy_check  # noqa: E402

OUT = os.path.join(SITE, "public", "data", "nat")
UA = "Mozilla/5.0 (research script)"  # identifies no person
FIRST_MONTH = "2019-01"
BANDS = ("new", "inj", "redrill", "rework", "amend", "other")
BAND_LABEL = {"new": "New wells", "inj": "Injection and disposal", "redrill": "Re-entries and sidetracks", "rework": "Recompletions and reworks",
              "amend": "Amendments and extensions", "other": "Other filings"}
FLUIDS = ("oil", "gas", "both", "other", "unknown")
MEASURES = ("permits", "spuds")
log = D8.log
nameable = D8.nameable

# every jurisdiction the national report accounts for: the states with oil production in the EIA's tables, Texas, Oklahoma and New Mexico (built first),
# and the federal offshore. `built` ones come from their own earlier producers (d11_nat_build.py adapts them).
JURISDICTIONS = [
    ("TX", "Texas"), ("OK", "Oklahoma"), ("NM", "New Mexico"), ("FO", "Federal offshore"), ("BL", "Federal onshore (BLM)"),
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"), ("CA", "California"), ("CO", "Colorado"), ("FL", "Florida"),
    ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"), ("MI", "Michigan"),
    ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"), ("NY", "New York"), ("ND", "North Dakota"),
    ("OH", "Ohio"), ("OR", "Oregon"), ("PA", "Pennsylvania"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("UT", "Utah"), ("VA", "Virginia"),
    ("WV", "West Virginia"), ("WY", "Wyoming"),
]
NAME_OF = dict(JURISDICTIONS)
OVERLAP = frozenset({"BL"})  # lines that overlap the states (the BLM permits wells the states permit too): shown, never added into a total


# ------------------------------------------------------------------------------------------------ polite network

class Refused(RuntimeError):
    """The server said no (401, 403, 429) or the network policy did: an answer, never retried."""


def polite_get(url, max_bytes=60 * 1024 * 1024, timeout=120, tries=2, pause=3.0, headers=None):
    """The body of one URL as bytes. Retries only a dropped connection or a 5xx, twice at most, with a pause; a refusal raises Refused at once; a
    body past max_bytes raises (the cap protects the runner). TLS is always verified, the proxy variables are honored."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(headers or {})))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("the reply is larger than %d bytes" % max_bytes)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 407, 429):
                raise Refused("HTTP %d from the server" % e.code)
            last = e
        except urllib.error.URLError as e:
            last = e
        except (OSError, ValueError) as e:  # a dropped connection, a cut-off read, too large
            if isinstance(e, ValueError):
                raise
            last = e
        if i + 1 < tries:
            time.sleep(pause * (i + 1))
    raise RuntimeError("could not read the source: " + privacy_check.clean_error(last))


def polite_json(url, **kw):
    return json.loads(polite_get(url, **kw).decode("utf-8-sig"))


def csv_rows(data, delimiter=None, encoding="utf-8-sig"):
    """Rows of a CSV given as bytes or text, as dicts keyed by the (stripped) header, never raising on a ragged row."""
    text = data.decode(encoding, "replace") if isinstance(data, (bytes, bytearray)) else data
    if delimiter is None:
        head = text[:4096].splitlines()[0] if text else ""
        delimiter = max(",;\t|", key=head.count)
    rd = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = [h.strip() for h in next(rd)]
    except StopIteration:
        return []
    out = []
    for row in rd:
        if not any(c.strip() for c in row):
            continue
        out.append({h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(header)})
    return out


# ------------------------------------------------------------------------------------------------ dates and words

DAY_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d", "%d-%b-%Y", "%d-%b-%y", "%Y/%m/%d", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y")


def parse_day(text, today=None):
    """A date from the shapes agencies use (ISO, 4/30/2026, 20260430, 30-APR-2026, an ISO date-time, an ArcGIS millisecond stamp); None for blank, junk,
    a placeholder (1900, 9999) or a day after `today`."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        try:
            d = datetime.utcfromtimestamp(text / 1000.0).date() if abs(text) > 1e10 else None
        except (OverflowError, OSError, ValueError):
            d = None
    else:
        s = str(text).strip()
        d = None
        if not s:
            return None
        head = re.split(r"[T ](?=\d{1,2}:)", s)[0]
        for f in DAY_FORMATS:
            try:
                d = datetime.strptime(head, f).date()
                break
            except ValueError:
                continue
    if d is None or d.year < 1950 or d.year > 2100:
        return None
    if d > (today or date.today()):
        return None
    return d


def month_of(d):
    return "%04d-%02d" % (d.year, d.month)


def month_list(first, last):
    out, y, m = [], int(first[:4]), int(first[5:])
    while "%04d-%02d" % (y, m) <= last:
        out.append("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_end(ym):
    return date(int(ym[:4]), int(ym[5:]), calendar.monthrange(int(ym[:4]), int(ym[5:]))[1])


def add_months(ym, n):
    t = int(ym[:4]) * 12 + int(ym[5:]) - 1 + n
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def band_of(work="", purpose=""):
    """A permit's band from the agency's own words. `work` is its type of work or application type; `purpose` its well type or purpose. Amendments are
    recognized first (an amendment of a new-drill permit is still an amendment), then reworks, re-entries, then a service well; what is left that
    says new, drill or original is a new well; anything else is 'other'."""
    w = (" %s " % (work or "")).lower()
    p = (" %s " % (purpose or "")).lower()
    both = w + p
    if re.search(r"amend|revis|modif|extension|extend|renew|transfer|change of operator|name change|correction|supersed", w):
        return "amend"
    if re.search(r"re-?complet|rework|work-?over|plug[- ]?back|conver|stimulat|change (of|in) zone|re-?perforat|recomp", w):
        return "rework"
    if re.search(r"re-?entr|re-?enter|deepen|side-?track|re-?drill|horizontal lateral|lateral addition|re-?work", w):
        return "redrill"
    if re.search(r"inject|dispos|swd|storage|service|\beor\b|water supply|observation|monitor|brine|\bgeothermal", both):
        return "inj"
    if re.search(r"\bnew\b|drill|original|initial|spud|wildcat|exploratory|development|\bapd\b|permit to drill", w) or not w.strip():
        return "new"
    return "other"


def fluid_of(text):
    """'oil', 'gas', 'both' or 'other' from a well type or purpose in the agency's words; None when the text says nothing about the fluid."""
    t = (text or "").lower()
    if not t.strip():
        return None
    if re.search(r"inject|dispos|swd|storage|service|observation|monitor|water|brine|geothermal|stratigraph|core|test hole", t):
        return "other"
    oil, gas = bool(re.search(r"\boil\b|crude|\bo&g\b|oil[ /&-]*(and|&)?[ /&-]*gas|oil/gas", t)), bool(re.search(r"\bgas\b|\bcbm\b|coal ?bed|methane|\bo&g\b|oil[ /&-]*(and|&)?[ /&-]*gas|oil/gas", t))
    if oil and gas:
        return "both"
    return "oil" if oil else "gas" if gas else None


# ------------------------------------------------------------------------------------------------ the tally

PLACE = re.compile(r"^[A-Za-z][A-Za-z .'\-/&()0-9]{0,45}$")


class Tally:
    """Collects permits one at a time and writes the state's document. `bands` names the bands this source can tell (`new` always); the others are
    published as null, never zero. Nothing but counts is kept: a record's county and operator are folded into totals, its well and lease are never seen."""

    def __init__(self, state, bands=("new",), fluid=False):
        if state not in NAME_OF:
            raise ValueError("unknown jurisdiction " + state)
        self.state = state
        self.bands = tuple(b for b in BANDS if b in bands or b == "new")
        self.fluid = fluid
        self.m = {b: collections.Counter() for b in BANDS}  # band -> month -> count
        self.county = collections.defaultdict(collections.Counter)  # month -> county -> new permits
        self.oper = collections.defaultdict(collections.Counter)  # month -> operator -> new permits
        self.unnamed = collections.Counter()  # month -> new permits whose operator may not be named
        self.fl = collections.defaultdict(collections.Counter)  # month -> fluid -> new permits
        self.read = 0
        self.newest = None

    def add(self, day, band="new", county=None, operator=None, fluid=None):
        """One permit. `day` is a date (the day the counts are by); `operator` the agency's name for it (kept only if it may be named)."""
        if day is None or band not in BANDS:
            return
        self.read += 1
        if self.newest is None or day > self.newest:
            self.newest = day
        ym = month_of(day)
        self.m[band][ym] += 1
        if band != "new":
            return
        if county:
            c = " ".join(str(county).replace("_", " ").split())
            if PLACE.match(c) and not re.search(r"\d{3,}", c):
                self.county[ym][c.upper()] += 1
        if operator and nameable(operator):
            self.oper[ym][" ".join(operator.upper().replace(",", " ").split())] += 1
        else:
            self.unnamed[ym] += 1
        if self.fluid:
            self.fl[ym][fluid if fluid in FLUIDS else "unknown"] += 1

    def document(self, *, name=None, agency, source_name, source_url, basis, cadence, measure="permits", lag_days=0, asof=None, note="", first=FIRST_MONTH):
        asof = asof or self.newest
        if asof is None:
            raise ValueError("no permit was read: refusing to write an empty state")
        through = max((ym for ym in month_list(first, month_of(asof)) if month_end(ym).toordinal() + lag_days <= asof.toordinal()), default=None)
        if through is None:
            raise ValueError("no complete month yet")
        months = month_list(first, through)
        last12 = months[-12:]
        bands = {b: ([self.m[b].get(ym, 0) for ym in months] if b in self.bands else None) for b in BANDS}
        cnt, ops, fl = collections.Counter(), collections.Counter(), collections.Counter()
        for ym in last12:
            cnt.update(self.county.get(ym, {}))
            ops.update(self.oper.get(ym, {}))
            fl.update(self.fl.get(ym, {}))
        named = sum(ops.values())
        total12 = sum(bands["new"][-12:])
        return {
            "v": 1, "state": self.state, "name": name or NAME_OF[self.state], "agency": agency, "measure": measure, "basis": basis,
            "source": {"name": source_name, "url": source_url}, "asOf": asof.isoformat(), "through": month_end(through).isoformat(), "cadence": cadence,
            "months": months, "bands": bands,
            "fluid": ({f: fl.get(f, 0) for f in FLUIDS} if self.fluid else None),
            "counties": [[c.title(), n] for c, n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:15]],
            "operators": [[o, n] for o, n in sorted(ops.items(), key=lambda kv: (-kv[1], kv[0]))[:15]],
            "namedShare": round(named / total12, 3) if total12 else None,
            "read": self.read, "note": note,
        }


# ------------------------------------------------------------------------------------------------ validation

def _fail(problems, cond, msg):
    if not cond:
        problems.append(msg)
    return cond


def validate(doc, today=None):
    """What a state file must satisfy before it is committed. Returns a list of problems ([] when the file is good)."""
    p = []
    today = today or date.today()
    if not _fail(p, isinstance(doc, dict) and doc.get("v") == 1, "not a v1 document"):
        return p
    sid = doc.get("state")
    # TX, OK, NM and FO are adapted from their own producers' files; BL (the BLM) is a producer like the states
    _fail(p, sid in NAME_OF and sid not in ("TX", "OK", "NM", "FO"), "state %r is not one this file type carries" % (sid,))
    _fail(p, doc.get("measure") in MEASURES, "measure must be one of %s" % (MEASURES,))
    for k in ("name", "agency", "basis", "cadence", "note"):
        _fail(p, isinstance(doc.get(k), str), "%s must be text" % k)
    src = doc.get("source") or {}
    _fail(p, isinstance(src.get("name"), str) and src["name"] and re.match(r"https://[\w.\-]+/", str(src.get("url", ""))), "source needs a name and an https address")
    months = doc.get("months")
    ok = _fail(p, isinstance(months, list) and len(months) >= 24 and all(isinstance(m, str) and re.fullmatch(r"\d{4}-\d\d", m) for m in months), "months must be 24 or more YYYY-MM")
    if ok:
        _fail(p, months == month_list(months[0], months[-1]), "months have a gap or are out of order")
        _fail(p, months[0] == FIRST_MONTH or months[0] > FIRST_MONTH, "months start before %s" % FIRST_MONTH)
        through, asof = doc.get("through"), doc.get("asOf")
        okd = _fail(p, all(isinstance(x, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", x) for x in (through, asof)), "asOf and through must be dates")
        if okd:
            _fail(p, through[:7] == months[-1] and through == month_end(months[-1]).isoformat(), "through must be the last day of the last month")
            _fail(p, through <= asof <= today.isoformat(), "asOf must not be before through, nor in the future")
            _fail(p, asof >= add_months(months[-1], 0) + "-01", "asOf is older than the last month")
        bands = doc.get("bands")
        if _fail(p, isinstance(bands, dict) and set(bands) == set(BANDS), "bands must hold exactly %s" % (BANDS,)):
            _fail(p, isinstance(bands["new"], list), "the new band is required")
            for b, v in bands.items():
                if v is None:
                    continue
                _fail(p, isinstance(v, list) and len(v) == len(months) and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 100000 for x in v), "band %s must be %d non-negative whole counts" % (b, len(months)))
            if isinstance(bands.get("new"), list) and len(bands["new"]) == len(months):
                _fail(p, sum(bands["new"][-24:]) > 0 or doc.get("zeroOk") is True, "no new permit in the last 24 months: a producer that read nothing must not write a file")
                _fail(p, max(bands["new"]) <= 20 * max(1, sorted(bands["new"])[len(months) // 2]) + 50, "one month is wildly larger than the typical month (a parse error?)")
    fl = doc.get("fluid")
    if fl is not None:
        _fail(p, isinstance(fl, dict) and set(fl) == set(FLUIDS) and all(isinstance(v, int) and v >= 0 for v in fl.values()), "fluid must hold %s as counts, or be null" % (FLUIDS,))
    cs = doc.get("counties")
    if _fail(p, isinstance(cs, list) and len(cs) <= 15, "counties: at most 15 [name, count]"):
        for r in cs:
            _fail(p, isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) and PLACE.match(r[0]) and isinstance(r[1], int) and r[1] > 0, "county row %r" % (r,))
        _fail(p, [r[1] for r in cs] == sorted((r[1] for r in cs), reverse=True), "counties must be ranked")
    os_ = doc.get("operators")
    if _fail(p, isinstance(os_, list) and len(os_) <= 15, "operators: at most 15 [name, count]"):
        for r in os_:
            if _fail(p, isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) and isinstance(r[1], int) and r[1] > 0, "operator row %r" % (r,)):
                _fail(p, nameable(r[0]), "operator name the rule refuses: " + privacy_check.mask(r[0]))
        _fail(p, [r[1] for r in os_] == sorted((r[1] for r in os_), reverse=True), "operators must be ranked")
    ns = doc.get("namedShare")
    _fail(p, ns is None or (isinstance(ns, (int, float)) and 0 <= ns <= 1), "namedShare must be 0 to 1")
    _fail(p, isinstance(doc.get("read"), int) and doc["read"] > 0, "read must count the records")
    text = json.dumps(doc, ensure_ascii=False)
    for what in privacy_check.scan(re.sub(r"https://[\w./\-]+", "", text), digits=True):
        p.append("the file holds " + what)
    return p


def write_doc(doc, out_dir=OUT):
    """Validates and writes nat/<ST>.json, compactly and deterministically. A bad document is never written."""
    bad = validate(doc)
    if bad:
        raise ValueError("%s: %s" % (doc.get("state"), "; ".join(bad[:5])))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, doc["state"] + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
    return path


def check_dir(out_dir=OUT):
    """Reloads and validates every nat/<ST>.json; returns the problems as 'ST: text' lines."""
    out = []
    if not os.path.isdir(out_dir):
        return out
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".json"):
            continue
        try:
            doc = json.load(open(os.path.join(out_dir, name), encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append("%s: unreadable (%s)" % (name, e))
            continue
        out += ["%s: %s" % (name[:-5], x) for x in validate(doc)]
        if doc.get("state") != name[:-5]:
            out.append("%s: file name and state differ" % name)
    return out


def run_producer(state, build, out_dir=OUT, argv=None):
    """The one `main` every producer uses: `build()` returns the document; `--check` only reloads what is committed. Exit code 1 on any problem."""
    args = argv if argv is not None else sys.argv[1:]
    if "--check" in args:
        bad = [x for x in check_dir(out_dir) if x.startswith(state + ":")]
        for x in bad:
            log(x)
        log("check: " + ("FAILED" if bad else "clean"))
        return 1 if bad else 0
    try:
        doc = build()
        path = write_doc(doc, out_dir)
    except Refused as e:
        log("%s: the source refused this machine (%s); nothing written" % (state, e))
        return 2
    except Exception as e:  # noqa: BLE001 - any failure leaves the committed file alone
        log("%s: failed: %s; nothing written" % (state, privacy_check.clean_error(e)))
        return 1
    log("%s: wrote %s (%d months to %s, %d records)" % (state, os.path.relpath(path, SITE), len(doc["months"]), doc["through"], doc["read"]))
    return 0


if __name__ == "__main__":
    sys.exit(1 if check_dir() else 0)
