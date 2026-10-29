"""
Deploy check: is every data file the dashboard reads in git?

Streamlit Cloud runs from a clone of GitHub, so a file that .gitignore excludes (*.csv, Scripts/output/*, Scripts/data/) is missing
online and the page shows "not found". This lists every file in the data folders whose name or stem appears in a Dashboard .py
file but which git does not track. Run it from Dashboard/ before pushing; it exits 1 if anything is listed.
Fix: `git add -f <file>`, and whitelist it in .gitignore with a `!` line.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIRS = ["Scripts/output", "Scripts/data", "Handover/segment_study_2026-10", "Dashboard/assets", "analysis"]
SKIP = ("backups", "history", "__pycache__", "-shm", "-wal", "csv_export", "gold_set",
        "theme_tag_queue", "cache.json", "Scripts/data/UN Comtrade")  # not read by the app, regenerated, or a fallback copy
EXTS = {".csv", ".db", ".json", ".xlsx", ".md", ".png", ".txt", ".toml", ".parquet"}


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").splitlines()


def main():
    tracked = {p.lower() for p in _git("ls-files")}
    code = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "Dashboard").glob("*.py")).lower()
    missing = []
    for d in DATA_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            rel = p.relative_to(ROOT).as_posix()
            if not p.is_file() or p.suffix.lower() not in EXTS or any(s in rel for s in SKIP):
                continue
            if rel.lower() in tracked:
                continue
            if p.name.lower() in code or p.stem.lower() in code:
                missing.append(rel)
    if missing:
        print("Read by the dashboard but NOT in git (git add -f, then whitelist in .gitignore):")
        print("\n".join("  " + m for m in missing))
        return 1
    print("OK: every data file the dashboard names is tracked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
