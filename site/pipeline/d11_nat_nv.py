#!/usr/bin/env python3
"""D11: Nevada's oil and gas drilling permits (Division of Minerals), for the National report of the Oil tracker.

Nevada approves a handful of permits to drill a year (none in 2024 or 2025, two in 2026 by October), and the Division publishes no table of them. What it does publish, free and with no
login, is the Permits page (https://www.minerals.nv.gov/programs/oil-gas/Permits/): a list of the signed permit PDFs for the current calendar year and the five before it, each linked under
the text "Oil <permit number> <approval date> <company> <well name>" (for example "Oil 0988 04-29-2026 ..."), the date as MM-DD-YYYY with or without leading zeros. That date is the day the
Division approved the permit, so the count is `measure="permits"`, basis "approval date". This reads the page and counts those links by month.

What it reads, and does not:
  - only the permit number (to count a permit once) and the date of each link; the company and the well name run together in the same text, so no operator is read, and no county is given;
    the page has no well type, so every permit is a new-well permit (`new`) and no other band is claimed (null, never zero); the fluid is not recorded (null);
  - the permit PDFs are never opened (they hold signatures, contacts and landowners' names);
  - the page keeps six years, so the months before them are kept from the committed file: a month that has dropped off the page is not forgotten and never becomes a zero;
  - permits are numbered in order, so a number missing between the first and last on the page is a permit the page does not list: the note says how many there are, and they are not counted;
  - the Division's "Oil Well Locations" layer (an ArcGIS service, no dates) is asked for permit numbers only, to see whether any permit is numbered above the newest on the page. If so, the
    note says how many: they are approved but have no date here, so they are not counted. A layer that cannot be read costs the note a sentence, never the file.
A month with no permit is a real zero. The page is updated by hand, so the last 30 days before the read are not shown (`lag_days`). The page is untrusted data: parsed as text, never run; a link on
it that is a permit PDF but whose text cannot be read, a date that is not a date, a year that disagrees with its heading, or a page that lost its layout fails the run (nothing is written).

  python3 -I site/pipeline/d11_nat_nv.py [--check]
"""
import html
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d11_nat_common as C  # noqa: E402

STATE = "NV"
PAGE = "https://www.minerals.nv.gov/programs/oil-gas/Permits/"
LAYER = ("https://services.arcgis.com/CXYUMoYknZtf5Qr3/arcgis/rest/services/OGHistoricData/FeatureServer/1/query"
         "?where=1%3D1&outFields=Permit&returnGeometry=false&f=json")
LAG_DAYS = 30
YEARS_SHOWN = 5  # the page lists the current year and this many before it
BLOCK = re.compile(r"<h2[^>]*>(.*?)</h2>|<li[^>]*>\s*<a\b[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", re.S | re.I)
PERMIT_LINKS = re.compile(r"href=\"[^\"]*/ogpermits/[^\"]*\"", re.I)
TEXT = re.compile(r"^\s*([A-Za-z]+)\s+0*(\d{1,5})\s+(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)")


def plain(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_page(page, today):
    """[(permit number, approval date)] of the oil and gas permits on the Permits page, in page order. Every link into the permits folder must be read: a link whose text does not give a kind, a
    number and a date, a date that is not a day, a day in the future or one outside its year's heading raises, so a changed page can never quietly lose permits."""
    if "Permits and Permit Notices" not in page:
        raise RuntimeError("the Permits page has changed: its heading is gone")
    year, found, seen = None, [], 0
    for m in BLOCK.finditer(page):
        if m.group(1) is not None:
            t = plain(m.group(1))
            if re.fullmatch(r"\d{4}", t):
                year = int(t)
            continue
        href, text = m.group(2), plain(m.group(3))
        if "/ogpermits/" not in href.lower():
            continue
        seen += 1
        t = TEXT.match(text)
        if year is None or not t:
            raise RuntimeError("a permit link on the Permits page cannot be read (%d chars of text)" % len(text))
        kind, number, mo, dy, yr = t.group(1).lower(), int(t.group(2)), int(t.group(3)), int(t.group(4)), int(t.group(5))
        try:
            d = date(yr, mo, dy)
        except ValueError:
            raise RuntimeError("a permit date on the Permits page is not a day: %s-%s-%s" % (mo, dy, yr))
        if d > today or yr != year or not 2000 <= yr <= today.year:
            raise RuntimeError("permit %04d is dated %s under the heading %s" % (number, d.isoformat(), year))
        if kind in ("oil", "gas"):  # another kind of permit (geothermal, say) is not an oil or gas well
            found.append((number, d))
    if seen != len(PERMIT_LINKS.findall(page)):
        raise RuntimeError("the Permits page links %d permit PDFs but %d were read from its lists: its layout may have changed" % (len(PERMIT_LINKS.findall(page)), seen))
    if not seen and "previous five years" not in page:
        raise RuntimeError("the Permits page lists no permit and no longer says which years it shows: its layout may have changed")
    out = {}
    for number, d in found:
        out.setdefault(number, d)  # a permit twice on the page counts once
    return sorted(out.items())


def layer_numbers(raw):
    """The permit numbers (whole numbers; a letter code such as GSR is not one) of the well layer's reply, or None when it is not the layer's reply or was cut at its transfer limit."""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
        feats = d["features"]
        if d.get("exceededTransferLimit") or not isinstance(feats, list) or len(feats) < 100:
            return None
        return sorted({int(f["attributes"]["Permit"].strip()) for f in feats if re.fullmatch(r"\d{1,5}", (f["attributes"].get("Permit") or "").strip())})
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def previous(path=None):
    """{month: new permits} of the committed nat/NV.json, or {} when there is none or it is not usable."""
    path = path or os.path.join(C.OUT, STATE + ".json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        if d["state"] != STATE:
            return {}
        return dict(zip(d["months"], d["bands"]["new"]))
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def build(get=C.polite_get, old=None, today=None):
    today = today or date.today()
    page = get(PAGE, max_bytes=2_000_000).decode("utf-8", "replace")
    permits = parse_page(page, today)
    try:
        nums = layer_numbers(get(LAYER, max_bytes=3_000_000))
    except C.Refused:
        raise
    except (RuntimeError, ValueError, OSError):
        nums = None  # the cross-check is a bonus: the page alone gives the counts
    old = previous() if old is None else old
    window = max("%04d-01" % (today.year - YEARS_SHOWN), C.FIRST_MONTH)  # the first month the page can show
    carry = {ym: n for ym, n in old.items() if ym < window} if old and C.add_months(window, -1) in old else {}
    first = min(carry) if carry else window
    if permits and min(d for _n, d in permits) < date(int(first[:4]), int(first[5:]), 1):  # a permit older than the page says it shows: keep it
        first = max("%04d-01" % min(d for _n, d in permits).year, C.FIRST_MONTH)
    t = C.Tally(STATE, bands=("new",), fluid=False)
    for ym, n in carry.items():
        if n:
            t.add(date(int(ym[:4]), int(ym[5:]), 15), "new", n=n)
    for _number, d in permits:
        t.add(d, "new")
    if not carry and not permits:
        raise RuntimeError("no permit on the Permits page and none committed")
    listed = {n for n, _d in permits}
    newest = max(listed, default=0)
    above = [n for n in (nums or []) if n > newest]
    holes = [n for n in range(min(listed), newest) if n not in listed] if listed else []  # numbers are issued in order: one between the first and last on the page is a permit the page does not list
    note = ("Permits to drill an oil or gas well, by the approval date in each permit's title on the Division of Minerals' Permits page, which lists the current year and the five before it "
            "(older months are kept from the earlier file). Nevada approves only a few a year, so a month with none is a real zero. The page names no well type, county or operator apart "
            "from the title's free text, so only new-well permits are counted and no county or operator is shown. The page is updated by hand: the last 30 days are not shown.")
    if holes:
        note += " %d permit number%s between the first and last on the page %s not listed there and %s not counted." % (len(holes), "" if len(holes) == 1 else "s", "is" if len(holes) == 1 else "are", "is" if len(holes) == 1 else "are")
    if above:
        note += " The Division's well layer holds %d permit number%s above the newest on the page; they have no date here and are not counted." % (len(above), "" if len(above) == 1 else "s")
    doc = t.document(agency="Nevada Division of Minerals", source_name="Permits and Permit Notices (Oil and Gas page)", source_url=PAGE, basis="approval date", cadence="irregular", measure="permits", lag_days=LAG_DAYS,
                     asof=today, first=first, note=note)
    if sum(doc["bands"]["new"][-24:]) == 0:
        doc["zeroOk"] = True  # a real zero: the page was read in full and Nevada approves none in some years
    return doc


if __name__ == "__main__":
    sys.exit(C.run_producer(STATE, build))
