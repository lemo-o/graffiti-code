#!/bin/bash
set -e
GH_REPO="lemo-o/graffiti"
DIR=/opt/graffiti/repo

rm -rf "$DIR"
python3 /opt/graffiti/git_graffiti.py --text "BEN HALL" --repo "$DIR" --commits-per-cell 20
gh repo delete "$GH_REPO" --yes || true
gh repo create "$GH_REPO" --public --source "$DIR" --push
