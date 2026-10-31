#!/usr/bin/env bash
# Publishes the committed site/public (as of HEAD) to the gh-pages branch, which is what GitHub Pages serves: a copy of site/public plus
# the .nojekyll marker that stops Pages from running Jekyll. A plain push, never a force push, so the branch keeps its history.
#
# Two workflows run this: the nightly capture (after it commits its data) and the publish after a green merge to main. If both publish at
# the same moment one push is refused because the branch moved; the copy is rebuilt from the branch's new tip and pushed again, which is
# harmless because it is a copy of one commit.
#
# Run it from the root of a clone whose `origin` has a gh-pages branch, with a git identity set. RUNNER_TEMP is where the copy is made
# (GitHub sets it; a new folder is used when it is not set).
set -euo pipefail

src="$(git rev-parse --short HEAD)"
dest="${RUNNER_TEMP:-$(mktemp -d)}/pages"
attempt=0

while :; do
  attempt=$((attempt + 1))
  git fetch --quiet origin gh-pages
  git worktree remove --force "$dest" 2>/dev/null || rm -rf "$dest"
  git worktree prune
  git worktree add --quiet -B gh-pages "$dest" origin/gh-pages
  find "$dest" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  git archive HEAD site/public | tar -x --strip-components=2 -C "$dest"
  touch "$dest/.nojekyll"
  # a publish replaces the whole site, so refuse to go on if the copy is not a site
  if ! { test -s "$dest/index.html" && test -s "$dest/js/main.js" && test -s "$dest/data/meta.json"; }; then
    echo "the copy of site/public is incomplete; not publishing"
    exit 1
  fi
  git -C "$dest" add -A
  if git -C "$dest" diff --cached --quiet; then
    echo "the published site is already current"
    exit 0
  fi
  git -C "$dest" commit --quiet -m "Publish the site (from $src)"
  # the push starts the Pages build by itself; requesting one as well only makes GitHub cancel the first
  if git -C "$dest" push origin HEAD:gh-pages; then
    echo "published the site from $src"
    exit 0
  fi
  if [ "$attempt" -ge 4 ]; then
    echo "the push was refused $attempt times; giving up"
    exit 1
  fi
  echo "the push was refused (gh-pages moved on); starting again from its new tip (attempt $attempt of 4)"
  sleep $((attempt * ${PUBLISH_RETRY_PAUSE:-3}))
done
