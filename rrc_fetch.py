#!/usr/bin/env python3
"""Download one file from an RRC public share page (https://mft.rrc.texas.gov/link/<guid>).

The share is a PrimeFaces form: open the page to get a session, then POST the form with the
file-name link as the submit parameter. The file streams to <outdir>/<filename>; outdir must be new or empty.

  python3 rrc_fetch.py <guid> <filename> <outdir>

GUIDs come from the RRC data sets page. P-5 Organization: 04652169-eed6-4396-9019-2e270e790f6c
(orf850.txt.gz). Drilling Permit Master and Trailer: beeeab0c-7d07-4111-af88-783c93677b2c
(daf802.txt.gz). Both refresh monthly, so fetch into a fresh folder each time.
"""
import html
import http.cookiejar
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://mft.rrc.texas.gov"
UA = {"User-Agent": "Mozilla/5.0"}


def attrs(tag):
    return {k: html.unescape(v) for k, v in re.findall(r'([\w:.-]+)="([^"]*)"', tag)}


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    guid, filename, outdir = sys.argv[1:]
    if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", guid) or os.sep in filename:
        sys.exit("bad guid or filename")
    os.makedirs(outdir, exist_ok=True)
    if os.listdir(outdir):
        sys.exit("%s is not empty; fetch into a fresh folder" % outdir)

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    page_url = "%s/link/%s" % (BASE, guid)
    page = opener.open(urllib.request.Request(page_url, headers=UA), timeout=60).read().decode("utf-8", "replace")

    form = re.search(r'<form id="fileList"[^>]*>.*?</form>', page, re.S)
    link = re.search(r'<a id="(fileTable:\d+:[^"]+)"[^>]*>%s</a>' % re.escape(filename), page)
    if not form or not link:
        sys.exit("%s not found on the share page" % filename)
    fields = {}
    for tag in re.findall(r"<input\b[^>]*>", form.group(0)):
        a = attrs(tag)
        if a.get("type") == "hidden" and "name" in a:
            fields[a["name"]] = a.get("value", "")
    fields[link.group(1)] = link.group(1)
    action = urllib.parse.urljoin(page_url, attrs(re.search(r"<form\b[^>]*>", form.group(0)).group(0))["action"])

    headers = dict(UA, **{"Content-Type": "application/x-www-form-urlencoded", "Referer": page_url})
    resp = opener.open(urllib.request.Request(action, data=urllib.parse.urlencode(fields).encode(), headers=headers),
                       timeout=120)
    ctype = resp.headers.get("Content-Type", "")
    if ctype.startswith("text/html"):
        sys.exit("got an HTML page instead of the file: " + " ".join(resp.read(400).decode("utf-8", "replace").split())[:300])
    expected = int(resp.headers.get("Content-Length") or 0)
    path = os.path.join(outdir, filename)
    done = 0
    with open(path, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
    note = "" if not expected or expected == done else "  SIZE MISMATCH, expected %d" % expected
    print("%s: %d bytes (%s)%s" % (path, done, ctype, note))


if __name__ == "__main__":
    main()
