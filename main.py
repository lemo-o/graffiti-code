#!/usr/bin/env python3
"""
git_graffiti.py — Spell out text on your GitHub contribution graph.

How the contribution graph works:
  - Each column = 1 week (Sunday → Saturday)
  - The graph shows ~52 weeks, newest on the right
  - Commits on a given date fill in that cell

Usage:
  python git_graffiti.py --text "BEN HALL" --repo ./graffiti-repo
  python git_graffiti.py --text "BEN HALL" --preview

Options:
  --text             Text to draw (A-Z, 0-9, spaces supported)
  --start            Start date (YYYY-MM-DD, a Sunday). Default: the most recent
                     Sunday minus --offset-weeks, so the text ends a few columns
                     left of the current week.
  --offset-weeks     Weeks back from the current week to the first column of text
                     (default 48, which leaves 4 blank columns on the left and 3
                     on the right for a 45-column string)
  --repo             Path to the git repo (created fresh if missing; no prompt)
  --preview          Print an ASCII preview without making any commits
  --commits-per-cell How many commits per "lit" cell (default: 1, more = darker green)
  --branch           Branch to commit on (default: main)
"""

import argparse
import os
import subprocess
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# 5×7 pixel font (col-major, top→bottom)
# Each letter is a list of 5 columns, each column is 7 bits (MSB = top row)
# ─────────────────────────────────────────────
FONT = {
    'A': [0b0111111, 0b1001000, 0b1001000, 0b1001000, 0b0111111],
    'B': [0b1111111, 0b1001001, 0b1001001, 0b1001001, 0b0110110],
    'C': [0b0111110, 0b1000001, 0b1000001, 0b1000001, 0b0100010],
    'D': [0b1111111, 0b1000001, 0b1000001, 0b1000001, 0b0111110],
    'E': [0b1111111, 0b1001001, 0b1001001, 0b1001001, 0b1000001],
    'F': [0b1111111, 0b1001000, 0b1001000, 0b1001000, 0b1000000],
    'G': [0b0111110, 0b1000001, 0b1001001, 0b1001001, 0b0101111],
    'H': [0b1111111, 0b0001000, 0b0001000, 0b0001000, 0b1111111],
    'I': [0b1000001, 0b1000001, 0b1111111, 0b1000001, 0b1000001],
    'J': [0b0000010, 0b0000001, 0b0000001, 0b0000001, 0b1111110],
    'K': [0b1111111, 0b0001000, 0b0010100, 0b0100010, 0b1000001],
    'L': [0b1111111, 0b0000001, 0b0000001, 0b0000001, 0b0000001],
    'M': [0b1111111, 0b0100000, 0b0011000, 0b0100000, 0b1111111],
    'N': [0b1111111, 0b0110000, 0b0001000, 0b0000110, 0b1111111],
    'O': [0b0111110, 0b1000001, 0b1000001, 0b1000001, 0b0111110],
    'P': [0b1111111, 0b1001000, 0b1001000, 0b1001000, 0b0110000],
    'Q': [0b0111110, 0b1000001, 0b1000101, 0b1000010, 0b0111101],
    'R': [0b1111111, 0b1001000, 0b1001100, 0b1001010, 0b0110001],
    'S': [0b0110001, 0b1001001, 0b1001001, 0b1001001, 0b1000110],
    'T': [0b1000000, 0b1000000, 0b1111111, 0b1000000, 0b1000000],
    'U': [0b1111110, 0b0000001, 0b0000001, 0b0000001, 0b1111110],
    'V': [0b1111000, 0b0000110, 0b0000001, 0b0000110, 0b1111000],
    'W': [0b1111110, 0b0000001, 0b0001110, 0b0000001, 0b1111110],
    'X': [0b1100011, 0b0010100, 0b0001000, 0b0010100, 0b1100011],
    'Y': [0b1100000, 0b0010000, 0b0001111, 0b0010000, 0b1100000],
    'Z': [0b1000011, 0b1000101, 0b1001001, 0b1010001, 0b1100001],
    '0': [0b0111110, 0b1000101, 0b1001001, 0b1010001, 0b0111110],
    '1': [0b0100001, 0b1111111, 0b0000001, 0b0000000, 0b0000000],
    '2': [0b0100011, 0b1000101, 0b1001001, 0b1001001, 0b0110001],
    '3': [0b1000010, 0b1001001, 0b1001001, 0b1001001, 0b0110110],
    '4': [0b1111000, 0b0001000, 0b0001000, 0b0001000, 0b1111111],
    '5': [0b1110001, 0b1010001, 0b1010001, 0b1010001, 0b1001110],
    '6': [0b0111110, 0b1001001, 0b1001001, 0b1001001, 0b0000110],
    '7': [0b1000000, 0b1000111, 0b1001000, 0b1010000, 0b1100000],
    '8': [0b0110110, 0b1001001, 0b1001001, 0b1001001, 0b0110110],
    '9': [0b0110000, 0b1001001, 0b1001001, 0b1001001, 0b0111110],
    ' ': [0b0000000, 0b0000000, 0b0000000],  # 3-wide space
    '!': [0b0000000, 0b1101111, 0b0000000],
    '.': [0b0000000, 0b0000011, 0b0000000],
}

ROWS = 7  # contribution graph rows (Sun–Sat)
COL_GAP = 1  # blank column between letters


def text_to_grid(text: str) -> list[list[bool]]:
    """Convert text string into a 2D grid of booleans (rows x cols)."""
    text = text.upper()
    grid_cols = []  # list of columns, each column is 7 bools

    for i, ch in enumerate(text):
        if ch not in FONT:
            ch = ' '
        cols = FONT[ch]
        for col_bits in cols:
            column = [(col_bits >> (ROWS - 1 - row)) & 1 == 1 for row in range(ROWS)]
            grid_cols.append(column)
        # Add gap column between letters (not after last)
        if i < len(text) - 1:
            grid_cols.append([False] * ROWS)

    return grid_cols  # shape: [num_cols][7 rows]


def preview(grid_cols: list, text: str):
    """Print an ASCII preview of what the contribution graph will look like."""
    print(f'\nPreview for: "{text}"')
    print(f'Width: {len(grid_cols)} weeks\n')
    day_labels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    for row in range(ROWS):
        label = day_labels[row]
        line = f'{label}  '
        for col in grid_cols:
            line += '██' if col[row] else '░░'
        print(line)
    print()


def run(cmd: list, cwd: str, env: dict = None):
    """Run a shell command, raise on failure."""
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def make_commits(grid_cols: list, start_date: datetime, repo_path: str,
                 commits_per_cell: int, branch: str):
    """Create commits in the repo at the appropriate dates."""
    repo_path = os.path.abspath(repo_path)

    # Init repo if needed
    if not os.path.exists(os.path.join(repo_path, '.git')):
        print(f'Initializing new git repo at {repo_path}')
        os.makedirs(repo_path, exist_ok=True)
        run(['git', 'init', '-b', branch], cwd=repo_path)
        run(['git', 'config', 'gc.auto', '0'], cwd=repo_path)
    else:
        print(f'Using existing repo at {repo_path}')

    graffiti_file = os.path.join(repo_path, 'graffiti.txt')

    total_commits = sum(
        commits_per_cell
        for col in grid_cols
        for row in range(ROWS)
        if col[row]
    )
    print(f'Creating {total_commits} commits across {len(grid_cols)} weeks...\n')

    commit_count = 0
    for week, col in enumerate(grid_cols):
        for day in range(ROWS):
            if not col[day]:
                continue
            commit_date = start_date + timedelta(weeks=week, days=day)
            date_str = commit_date.strftime('%Y-%m-%dT12:00:00')

            env = os.environ.copy()
            env['GIT_AUTHOR_DATE'] = date_str
            env['GIT_COMMITTER_DATE'] = date_str

            for n in range(commits_per_cell):
                with open(graffiti_file, 'w') as f:
                    f.write(f'week={week} day={day} n={n} date={date_str}\n')

                run(['git', 'add', 'graffiti.txt'], cwd=repo_path)
                run(
                    ['git', 'commit', '-m', f'graffiti {week},{day},{n}'],
                    cwd=repo_path,
                    env=env
                )
                commit_count += 1

        if (week + 1) % 5 == 0 or week == len(grid_cols) - 1:
            print(f'  Week {week+1}/{len(grid_cols)} done — {commit_count} commits so far')

    print(f'\nDone. {commit_count} commits created.')


def main():
    parser = argparse.ArgumentParser(description='Spell text on GitHub contribution graph')
    parser.add_argument('--text', required=True, help='Text to draw (A-Z, 0-9, spaces)')
    parser.add_argument('--start', default=None,
                        help='Start date YYYY-MM-DD, a Sunday (default: computed from today)')
    parser.add_argument('--offset-weeks', type=int, default=48,
                        help='Weeks back from the current week to the first text column (default 48)')
    parser.add_argument('--repo', default='./graffiti-repo',
                        help='Path to git repo (created if missing)')
    parser.add_argument('--preview', action='store_true',
                        help='Show ASCII preview only, no commits')
    parser.add_argument('--commits-per-cell', type=int, default=1,
                        help='Commits per lit cell (more = darker green, default 1)')
    parser.add_argument('--branch', default='main',
                        help='Branch name (default: main)')
    args = parser.parse_args()

    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        start_date = this_sunday - timedelta(weeks=args.offset_weeks)
    print(f'Start date: {start_date:%Y-%m-%d} ({start_date:%A})')

    grid_cols = text_to_grid(args.text)
    preview(grid_cols, args.text)

    if args.preview:
        print('(Preview only — no commits made. Remove --preview to generate commits.)')
        return

    make_commits(grid_cols, start_date, args.repo, args.commits_per_cell, args.branch)


if __name__ == '__main__':
    main()
