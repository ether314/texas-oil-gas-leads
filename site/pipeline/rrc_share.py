#!/usr/bin/env python3
"""Read and download from the Railroad Commission's public file shares (https://mft.rrc.texas.gov/link/<guid>).

A share is a PrimeFaces (JSF) file table: the page lists the first 250 files by name, and the table can be sorted and
paged with AJAX posts. This module opens one keep-alive HTTPS connection per share session, sorts the table by Last
Modified (newest first), reads as many rows as asked for, and streams one file to disk. Python standard library only.

The host drops most new TLS handshakes (about two in three through the agent proxy, with no pattern by file), so the
connection is reused and every request reconnects and retries until it gets through. Requests go one at a time per
session; the daily script runs a few shares side by side.

  python3 -I site/pipeline/rrc_share.py list <guid> [N]              the N newest files (default 10)
  python3 -I site/pipeline/rrc_share.py get <guid> <file> <outdir>   download <file> (outdir must be new or empty)

GUIDs come from the RRC data sets page (see d7_daily.py). Downloads are untrusted data: parse them, never execute them.
"""
import html
import http.client
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime

HOST = "mft.rrc.texas.gov"
UA = "Mozilla/5.0 (research script)"
TABLE = "fileTable"
PAGE_ROWS = 250  # rows the share renders per page
RETRYABLE_STATUS = {500, 502, 503, 504}
UNITS = {"B": 1, "KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30}


class ShareError(RuntimeError):
    pass


class TooSlow(RuntimeError):
    """A download went past its time budget. Not an OSError, so the retry loop does not swallow it."""


def attrs(tag):
    return {k: html.unescape(v) for k, v in re.findall(r'([\w:.-]+)="([^"]*)"', tag)}


def parse_size(text):
    """'2.82 MB' / '1,019.48 KB' -> bytes (the share rounds to two decimals, so this is approximate)."""
    m = re.fullmatch(r"\s*([\d,]*\.?\d+)\s*(B|KB|MB|GB)\s*", text or "")
    return int(round(float(m.group(1).replace(",", "")) * UNITS[m.group(2)])) if m else None


def parse_modified(text):
    """'10/30/26 9:45:28 AM' (RRC server time, Central) -> '2026-10-30T09:45:28' or None."""
    try:
        return datetime.strptime(text.strip(), "%m/%d/%y %I:%M:%S %p").isoformat()
    except ValueError:
        return None


class Session:
    """One keep-alive HTTPS connection to the share host with a cookie jar and retry-with-reconnect."""

    def __init__(self, host=HOST, attempts=18, timeout=120, log=None):
        self.host, self.attempts, self.timeout, self.log = host, attempts, timeout, log
        self.conn = None
        self.cookies = {}
        self.retries = 0  # how many resets this session absorbed (reported by the daily script)
        self.deadline = None  # time.time() after which a streaming download gives up (TooSlow); None means no limit

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None

    def _connect(self):
        import ssl
        ctx = ssl.create_default_context()
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:  # the agent proxy: CONNECT tunnel, TLS to the share inside it
            p = urllib.parse.urlsplit(proxy)
            self.conn = http.client.HTTPSConnection(p.hostname, p.port, timeout=self.timeout, context=ctx)
            self.conn.set_tunnel(self.host, 443)
        else:
            self.conn = http.client.HTTPSConnection(self.host, 443, timeout=self.timeout, context=ctx)

    def _once(self, method, path, data, headers, sink):
        if self.conn is None:
            self._connect()
        hdr = {"User-Agent": UA, "Accept": "*/*"}
        hdr.update(headers or {})
        if self.cookies:
            hdr["Cookie"] = "; ".join("%s=%s" % kv for kv in self.cookies.items())
        self.conn.request(method, path, body=data, headers=hdr)
        r = self.conn.getresponse()
        for sc in r.headers.get_all("Set-Cookie") or []:
            k, _, v = sc.split(";", 1)[0].partition("=")
            self.cookies[k.strip()] = v.strip()
        if r.status in RETRYABLE_STATUS:
            r.read()
            raise http.client.HTTPException("HTTP %d" % r.status)
        ctype = r.headers.get("Content-Type", "")
        if sink is not None and r.status == 200 and not ctype.startswith("text/html"):
            sink.seek(0)
            sink.truncate()
            while True:
                if self.deadline is not None and time.time() > self.deadline:
                    raise TooSlow("download of %s went past its time budget" % path.split("?")[0])
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                sink.write(chunk)
            want = r.headers.get("Content-Length")
            if want and sink.tell() != int(want):
                raise http.client.IncompleteRead(b"", int(want) - sink.tell())
            return r.status, r.headers, b""
        return r.status, r.headers, r.read()

    def request(self, method, path, data=None, headers=None, sink=None):
        """(status, headers, body). Follows redirects. With `sink` (a binary file object) a non-HTML 200 body is
        streamed into it and body is b''."""
        for _hop in range(6):
            last = None
            for i in range(self.attempts):
                try:
                    status, hdrs, body = self._once(method, path, data, headers, sink)
                    break
                except (OSError, http.client.HTTPException) as e:  # includes ssl.SSLError and resets
                    last = e
                    self.retries += 1
                    self.close()
                    time.sleep(min(1.0 + 0.5 * i, 8.0))
            else:
                raise ShareError("%s %s failed after %d tries: %r" % (method, path, self.attempts, last))
            if status in (301, 302, 303, 307, 308) and hdrs.get("Location"):
                loc = urllib.parse.urlsplit(urllib.parse.urljoin("https://%s%s" % (self.host, path), hdrs["Location"]))
                path, method, data = loc.path + ("?" + loc.query if loc.query else ""), "GET", None
                continue
            return status, hdrs, body
        raise ShareError("too many redirects for " + path)


ROW = re.compile(r'<tr data-ri="(\d+)"[^>]*>(.*?)</tr>', re.S)
NAME_CELL = re.compile(r'class="NameColumn">\s*(?:<a id="([^"]+)"[^>]*>)?(.*?)(?:</a>)?\s*</td>', re.S)
DATE_CELL = re.compile(r'class="ModifiedOnColumn">(.*?)</td>', re.S)
SIZE_CELL = re.compile(r'class="SizeColumn">(.*?)</td>', re.S)


def parse_rows(text):
    """Rows of a share page or an AJAX table update: [{name, modified, size, bytes, link}], in table order."""
    out = []
    for m in ROW.finditer(text):
        body = m.group(2)
        n, d, s = NAME_CELL.search(body), DATE_CELL.search(body), SIZE_CELL.search(body)
        if not n:
            continue
        size = html.unescape(s.group(1)).strip() if s else ""
        out.append({"name": html.unescape(re.sub(r"<[^>]+>", "", n.group(2))).strip(),
                    "modified": parse_modified(html.unescape(d.group(1))) if d else None,
                    "size": size, "bytes": parse_size(size), "link": n.group(1)})
    return out


class Share:
    def __init__(self, guid, session=None):
        if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", guid):
            raise ValueError("bad share guid")
        self.guid, self.s = guid, session or Session()
        self.fields, self.action, self.total, self.links, self.page = {}, None, 0, {}, 0  # page: what the server's table shows

    def open(self):
        """Load the share page. Returns its first rows (name order) and sets .total."""
        page_path = "/link/" + self.guid
        status, _h, body = self.s.request("GET", page_path)
        page = body.decode("utf-8", "replace")
        form = re.search(r'<form id="fileList"[^>]*>.*?</form>', page, re.S)
        if status != 200 or not form:
            raise ShareError("share %s: no file table (HTTP %d)" % (self.guid, status))
        self.fields = {}
        for tag in re.findall(r"<input\b[^>]*>", form.group(0)):
            a = attrs(tag)
            if a.get("type") == "hidden" and "name" in a:
                self.fields[a["name"]] = a.get("value", "")
        self.action = urllib.parse.urljoin(page_path, attrs(re.search(r"<form\b[^>]*>", form.group(0)).group(0))["action"])
        rows = parse_rows(page)
        count = re.search(r"rowCount:(\d+)", page)
        self.total = int(count.group(1)) if count else len(rows)
        self.links = {r["name"]: r["link"] for r in rows if r["link"]}
        self.page = 0
        return rows

    def _ajax(self, extra):
        data = dict(self.fields)
        data.update({"javax.faces.partial.ajax": "true", "javax.faces.source": TABLE, "javax.faces.partial.execute": TABLE,
                     "javax.faces.partial.render": TABLE, TABLE: TABLE, TABLE + "_encodeFeature": "true", "fileList": "fileList"})
        data.update(extra)
        hdr = {"Content-Type": "application/x-www-form-urlencoded", "Faces-Request": "partial/ajax",
               "X-Requested-With": "XMLHttpRequest", "Referer": "https://%s/link/%s" % (self.s.host, self.guid)}
        status, _h, body = self.s.request("POST", self.action, urllib.parse.urlencode(data).encode(), hdr)
        text = body.decode("utf-8", "replace")
        if status != 200 or "<partial-response" not in text or "<error>" in text:
            raise ShareError("share %s: table request failed: %s" % (self.guid, " ".join(text[:200].split())))
        vs = re.search(r'<update id="[^"]*ViewState[^"]*"><!\[CDATA\[(.*?)\]\]></update>', text)
        if vs:
            self.fields["javax.faces.ViewState"] = vs.group(1)
        return text

    def newest(self, count=PAGE_ROWS):
        """The `count` most recently modified files, newest first. Needs open() first."""
        rows, first = [], 0
        while len(rows) < count and first < self.total:
            if first == 0:  # a sort request always restarts at the first page, so only this one carries the sort
                extra = {TABLE + "_sorting": "true", TABLE + "_sortKey": TABLE + ":date", TABLE + "_sortDir": "-1",
                         TABLE + "_first": "0", TABLE + "_rows": str(PAGE_ROWS)}
            else:  # later pages continue the server-side sort order
                extra = {TABLE + "_pagination": "true", TABLE + "_first": str(first), TABLE + "_rows": str(PAGE_ROWS),
                         TABLE + "_page": str(first // PAGE_ROWS)}
            got = parse_rows(self._ajax(extra))
            self.page = first // PAGE_ROWS
            if not got:
                break
            rows += got
            first += PAGE_ROWS
        rows = rows[:count]
        self.links = {r["name"]: r["link"] for r in rows if r["link"]}  # ids are positions in this sorted view
        return rows

    def _goto(self, page):
        """A file link only resolves while the server's table shows the page that holds its row."""
        if page != self.page:
            self._ajax({TABLE + "_pagination": "true", TABLE + "_first": str(page * PAGE_ROWS), TABLE + "_rows": str(PAGE_ROWS),
                        TABLE + "_page": str(page)})
            self.page = page

    def download(self, name, dest_dir):
        """Stream one file into dest_dir (created if needed). The name must be in the latest listing of this share."""
        link = self.links.get(name)
        if not link:
            raise ShareError("%s is not in the last listing of share %s" % (name, self.guid))
        if os.sep in name or name.startswith("."):
            raise ShareError("bad file name " + name)
        os.makedirs(dest_dir, exist_ok=True)
        self._goto(int(link.split(":")[1]) // PAGE_ROWS)
        data = dict(self.fields)
        data[link] = link
        hdr = {"Content-Type": "application/x-www-form-urlencoded", "Referer": "https://%s/link/%s" % (self.s.host, self.guid)}
        path = os.path.join(dest_dir, name)
        with open(path, "wb") as f:
            status, _h, body = self.s.request("POST", self.action, urllib.parse.urlencode(data).encode(), hdr, sink=f)
        if status != 200 or body:  # an HTML body means the share answered with a page instead of the file
            os.remove(path)
            raise ShareError("share %s: %s did not download (HTTP %d: %s)" % (self.guid, name, status, " ".join(body[:160].decode("utf-8", "replace").split())))
        return path


def main(argv):
    if len(argv) >= 3 and argv[1] == "list":
        sh = Share(argv[2])
        first = sh.open()
        print("%d files; first page %d rows" % (sh.total, len(first)), file=sys.stderr)
        for r in sh.newest(int(argv[3]) if len(argv) > 3 else 10):
            print("%-40s %-20s %s" % (r["name"], r["modified"], r["size"]))
    elif len(argv) == 5 and argv[1] == "get":
        _, _, guid, name, outdir = argv
        if os.path.isdir(outdir) and os.listdir(outdir):
            sys.exit("%s is not empty; download into a fresh folder" % outdir)
        sh = Share(guid)
        sh.open()
        sh.newest(PAGE_ROWS)
        if name not in sh.links:
            sh.open()  # not among the newest: the first page (name order) has it, e.g. daf420.dat
        print(sh.download(name, outdir))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
