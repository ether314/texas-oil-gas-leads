#!/usr/bin/env python3
"""D8 context: Oklahoma's monthly figures, for the monthly figures card on the Daily report.

Reads one EIA series, Oklahoma field production of crude oil (MCRFPOK1, thousand barrels a month), by the same fetch and the same
page parser the Texas market series use (d3_markets_infra.py), and writes site/public/data/series-ok.json. The two prices on the card
(WTI and Henry Hub) are not repeated: the page reads them from series-markets.json.

Not here, and why: Oklahoma oil and gas jobs (BLS State and Area Employment, series SMU40000001021100001) and Oklahoma rig counts
(Baker Hughes). The keyless BLS API allows 25 requests a day per address and the build host had used its allowance; BLS's bulk files
refuse a request without a contact in the User-Agent; Baker Hughes blocks scripts and its workbook copies are on the Internet
Archive, which the build host could not reach. See NOTES_D8.md.

  python3 -I site/pipeline/d8_ok_context.py [--as-of YYYY-MM-DD] [--out FILE] [--dl DIR]
  python3 -I site/pipeline/d8_ok_context.py --check [--out FILE]        only reload and check what is already there

The downloaded page is untrusted data: parsed, never run. Run by hand when EIA publishes (about the end of each month).
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)  # python -I drops the script folder from sys.path
import d3_markets_infra as D3  # noqa: E402

OUT = os.path.join(SITE, "public", "data", "series-ok.json")
DL = os.path.join(os.path.dirname(SITE), "dl")
SPEC = dict(name="eia_okcrude_monthly", sid="MCRFPOK1", url="https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=MCRFPOK1&f=M",
            must=("Oklahoma Field Production of Crude Oil", "Thousand Barrels"), never=("per Day",), lo=5000.0, hi=30000.0,
            label="EIA, Oklahoma field production of crude oil, thousand barrels per month")
KEYS = ["asOf", "latest", "release", "months", "okCrude", "units", "src"]
# Another state is the same series under its own code: --state NM writes series-nm.json from MCRFPNM1 (key nmCrude). The plausible range is
# wide enough for the whole history since 2019 and narrow enough to catch a per-day series or the wrong state.
STATE_SPECS = {
    "OK": dict(SPEC=SPEC, key="okCrude", out=OUT, noun="Oklahoma"),
    "NM": dict(SPEC=dict(name="eia_nmcrude_monthly", sid="MCRFPNM1", url="https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=MCRFPNM1&f=M",
                         must=("New Mexico Field Production of Crude Oil", "Thousand Barrels"), never=("per Day",), lo=10000.0, hi=120000.0,
                         label="EIA, New Mexico field production of crude oil, thousand barrels per month"),
               key="nmCrude", out=os.path.join(SITE, "public", "data", "series-nm.json"), noun="New Mexico"),
}
log = D3.log


def build(dl_root, as_of, state="OK"):
    st = STATE_SPECS[state]; spec, key = st["SPEC"], st["key"]
    path = D3.fetch(dl_root, spec["name"], "page.html", spec["url"])
    title, values, release = D3.parse_eia_monthly(path, spec)
    have = sorted(k for k, v in values.items() if v is not None and k >= D3.MARKET_START)
    if not have:
        raise SystemExit("%s: no month from %d-%02d on has a value" % (spec["sid"], *D3.MARKET_START))
    months = D3.month_range(D3.MARKET_START, have[-1])
    series = []
    for ym in months:
        v = values.get(ym)
        if v is not None and not (spec["lo"] < v < spec["hi"]):
            raise SystemExit("%s %04d-%02d value %s outside %s..%s (wrong series or units?)" % (spec["sid"], ym[0], ym[1], v, spec["lo"], spec["hi"]))
        series.append(int(v) if v is not None and v == int(v) else v)
    latest = "%04d-%02d" % have[-1]
    return {"asOf": as_of.isoformat(), "latest": latest, "release": release, "months": ["%04d-%02d" % ym for ym in months], key: series,
            "units": {key: "thousand barrels per month"},
            "src": {key: "%s (series %s, %s), EIA release %s; latest month with data %s. The newest months are estimates that EIA revises."
                    % (spec["label"], spec["sid"], spec["url"], release or "date n/a", latest)}}


def validate(doc, state="OK"):
    """The problems found in a series-ok.json (or series-nm.json) document (empty when all is well)."""
    st = STATE_SPECS[state]; spec, key = st["SPEC"], st["key"]
    keys = ["asOf", "latest", "release", "months", key, "units", "src"]
    bad = []

    def check(cond, msg):
        if not cond:
            bad.append(msg)

    check(isinstance(doc, dict) and list(doc.keys()) == keys, "keys are not %s" % keys)
    if bad:
        return bad
    months, crude = doc["months"], doc[key]
    check(months and months[0] == "2019-01" and len(months) >= 90, "months do not start at 2019-01 or are fewer than 90")
    check(len(crude) == len(months), "%s and months have different lengths" % key)
    ok_months = all(re.fullmatch(r"\d{4}-\d\d", m) for m in months) and months == sorted(set(months))
    check(ok_months, "months are not ascending year-months")
    if ok_months and len(months) >= 2:
        y, m = (int(x) for x in months[0].split("-"))
        want = []
        for _ in months:
            want.append("%04d-%02d" % (y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        check(months == want, "months have a gap")
    check(all(isinstance(v, (int, float)) and spec["lo"] < v < spec["hi"] for v in crude if v is not None), "a value is outside the plausible range")
    check(crude and crude[-1] is not None and doc["latest"] == months[-1], "the newest month has no value or does not match `latest`")
    check(isinstance(doc["asOf"], str) and re.fullmatch(r"\d{4}-\d\d-\d\d", doc["asOf"]), "asOf is not a date")
    check(doc["units"] == {key: "thousand barrels per month"} and set(doc["src"]) == {key}, "units or src are not as expected")
    return bad


def main():
    ap = argparse.ArgumentParser(description="D8 context: a state's crude oil production, monthly (see the module docstring)")
    ap.add_argument("--state", default="OK", choices=sorted(STATE_SPECS), help="which state's series (default OK)")
    ap.add_argument("--as-of", default=datetime.date.today().isoformat(), help="the build date (default today)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dl", default=DL)
    ap.add_argument("--check", action="store_true", help="only reload and check the file already in --out")
    a = ap.parse_args()
    st = STATE_SPECS[a.state]
    out = a.out or st["out"]
    if a.check:
        with open(out, encoding="utf-8") as f:
            problems = validate(json.load(f), a.state)
        for p in problems:
            log("CHECK failed: " + p)
        log("checks ok (%s)" % out if not problems else "%d problem(s)" % len(problems))
        return 1 if problems else 0
    doc = build(a.dl, datetime.date.fromisoformat(a.as_of), a.state)
    problems = validate(doc, a.state)
    if problems:
        for p in problems:
            log("CHECK failed: " + p)
        return 2
    size = D3.write_json(out, doc)
    log("wrote %s (%d bytes): %d months to %s, latest %d thousand barrels" % (os.path.basename(out), size, len(doc["months"]), doc["latest"], doc[st["key"]][-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
