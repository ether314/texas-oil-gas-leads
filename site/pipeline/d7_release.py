#!/usr/bin/env python3
"""D7 helper: publish a day's filings as the files of one GitHub release, and retire the releases of days that have aged out.

Each report day gets one release, tag `daily-YYYY-MM-DD`, marked pre-release so it never becomes the repository's "latest".
Its files are the staged W-1 letters, plats and directional surveys (d7_packs.stage_pack) that the day's report links to:

  https://github.com/<owner>/<repo>/releases/download/daily-2026-10-30/0919696_W1.pdf

and, since 2026-11-01, a readable JPEG of page one of each (the same name plus .jpg: 0919696_W1.pdf.jpg), which the Texas images view
shows inline. A preview is optional: publish() uploads the documents first, then the previews, and a preview that cannot be uploaded
costs nothing but itself.

Why a release and not the repository: the W-1 pack alone is about 31 MB a day and the survey pack 28 MB. Committed (to main and
again to gh-pages) that outgrows GitHub's repository size guidance within weeks; release files do not touch the git history or
the Pages site. The files are served as downloads, so the site links to them; the previews, which are pictures, are what it shows inline.

This needs the gh CLI and a token that can write releases (GH_TOKEN, which Actions provides with `contents: write`). The
report only links to a file after publish() has confirmed, by listing the release, that every file is there; a failed upload
means no links, never dead ones. Standard library only; gh does the talking.
"""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime

TAG = re.compile(r"daily-(\d{4}-\d\d-\d\d)")
BATCH = 40  # files per `gh release upload`
ASSET_LIMIT = 1000  # GitHub's limit of files on one release: the optional files (previews) are cut back to what the documents leave room for
ATTEMPTS = 3
DEADLINE = None  # time.time() after which no gh call is started, and the one running is cut off (set by the capture, with a margin for writing the report)


class ReleaseError(RuntimeError):
    pass


def tag_for(day):
    return "daily-" + day.isoformat()


def base_url(repo, tag):
    return "https://github.com/%s/releases/download/%s/" % (repo, tag)


def page_url(repo, tag):
    return "https://github.com/%s/releases/tag/%s" % (repo, tag)


def ready():
    """None when gh and a token are available, else a reason publishing cannot happen."""
    if shutil.which("gh") is None:
        return "the gh CLI is not installed"
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        return "no GH_TOKEN"
    return None


def repo_name():
    """owner/repo from GITHUB_REPOSITORY (set in Actions), else from the origin remote; None when neither says."""
    r = os.environ.get("GITHUB_REPOSITORY", "")
    if re.fullmatch(r"[\w.-]+/[\w.-]+", r):
        return r
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def _gh(args, timeout=300, retry=True):
    """Run gh, retrying a failure a couple of times (uploads of many files do hit the occasional reset). Returns stdout."""
    err = ""
    for k in range(ATTEMPTS if retry else 1):
        left = None if DEADLINE is None else DEADLINE - time.time()
        if left is not None and left < 20:
            raise ReleaseError("gh %s: the capture ran out of time" % " ".join(args[:2]))
        try:
            r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout if left is None else min(timeout, left))
        except (OSError, subprocess.SubprocessError) as e:
            err = str(e)
        else:
            if r.returncode == 0:
                return r.stdout
            err = (r.stderr or r.stdout).strip()[-300:]
        if k + 1 < ATTEMPTS and retry:
            time.sleep(3 * (k + 1))
    raise ReleaseError("gh %s failed: %s" % (" ".join(args[:2]), err))


def assets_of(repo, tag):
    out = _gh(["release", "view", tag, "--repo", repo, "--json", "assets"])
    return {a["name"] for a in json.loads(out).get("assets", [])}


def publish(repo, day, folder, names, log=print, optional=(), confirmed=None):
    """Create the day's release if it is not there and upload `names` (files of `folder`). Returns the tag once every name is
    confirmed to be a file of the release; raises ReleaseError otherwise.
    `optional` names (the previews) are uploaded after those, within what ASSET_LIMIT leaves; their failing, to upload or to show in
    the listing, never fails the call. The same listing that confirms `names` says which optional ones are there, and they are
    appended to the list `confirmed` when one is given."""
    tag = tag_for(day)
    names = sorted(set(names))
    optional = sorted(set(optional) - set(names))
    if not names:
        raise ReleaseError("no files to publish")
    if len(names) + len(optional) > ASSET_LIMIT:
        log("release %s: %d documents leave room for %d of %d optional files (limit %d on a release)" % (tag, len(names), max(0, ASSET_LIMIT - len(names)), len(optional), ASSET_LIMIT))
        optional = optional[:max(0, ASSET_LIMIT - len(names))]
    try:
        _gh(["release", "view", tag, "--repo", repo, "--json", "tagName"], retry=False)
    except ReleaseError:
        _gh(["release", "create", tag, "--repo", repo, "--prerelease", "--latest=false", "--title", "RRC filings, report of %s" % day.isoformat(),
             "--notes", "The Railroad Commission's W-1 permit letters, permit plats and directional surveys that the daily report of %s links to. "
             "Scans of public records, unmodified (each also has a readable JPEG of its page one, named like the file plus .jpg); they can carry names, phone numbers and addresses of individuals. Files are removed when "
             "the day leaves the report's 92-day archive. Made by site/pipeline/d7_release.py." % day.isoformat()])
        log("release %s created" % tag)
    for i in range(0, len(names), BATCH):
        _gh(["release", "upload", tag, "--repo", repo, "--clobber", *[os.path.join(folder, n) for n in names[i:i + BATCH]]], timeout=900)
    for i in range(0, len(optional), BATCH):
        try:
            _gh(["release", "upload", tag, "--repo", repo, "--clobber", *[os.path.join(folder, n) for n in optional[i:i + BATCH]]], timeout=900)
        except ReleaseError as e:  # a preview is a bonus: the documents are already on the release
            log("release %s: a batch of previews was not uploaded (%s)" % (tag, e))
            break
    have = assets_of(repo, tag)
    missing = [n for n in names if n not in have]
    if missing:
        raise ReleaseError("%d of %d files are not on release %s after the upload (%s ...)" % (len(missing), len(names), tag, ", ".join(missing[:3])))
    there = [n for n in optional if n in have]
    if confirmed is not None:
        confirmed.extend(there)
    log("release %s: %d files confirmed%s" % (tag, len(names), ", and %d of %d previews" % (len(there), len(optional)) if optional else ""))
    return tag


def prune(repo, oldest_kept, log=print):
    """Delete the releases (and their tags) of days older than `oldest_kept`: the days that have left the archive, whose pages no
    longer link to them. Only tags that are exactly daily-YYYY-MM-DD are ever touched. Returns the tags deleted."""
    out = _gh(["release", "list", "--repo", repo, "--limit", "400", "--json", "tagName"])
    gone = []
    for row in json.loads(out):
        m = TAG.fullmatch(row.get("tagName") or "")
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < oldest_kept:
            _gh(["release", "delete", row["tagName"], "--repo", repo, "--yes", "--cleanup-tag"])
            gone.append(row["tagName"])
    if gone:
        log("release: removed %d aged-out releases (%s ... %s)" % (len(gone), gone[0], gone[-1]))
    return gone


if __name__ == "__main__":
    import sys
    why = ready()
    print("ready" if not why else "not ready: " + why, "| repo:", repo_name())
    if len(sys.argv) == 2:
        print(sorted(assets_of(repo_name(), sys.argv[1])))
