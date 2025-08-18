#!/usr/bin/env python3
import argparse
import hashlib
import os
import sys
import difflib
from pathlib import Path

def list_files(root: Path):
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        for name in filenames:
            p = dirpath / name
            rel = p.relative_to(root)
            files[str(rel).replace("\\", "/")] = p
    return files

def sha256(path: Path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def is_text_file(path: Path, sample_size=8192):
    try:
        with open(path, "rb") as f:
            sample = f.read(sample_size)
        if b"\x00" in sample:
            return False
        # try decode
        sample.decode("utf-8")
        return True
    except Exception:
        return False

def read_text(path: Path):
    # 최대한 텍스트로 보여주기 위해 errors='replace'
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines(keepends=False)

def should_ignore(rel_path: str, ignores: list[str]):
    from fnmatch import fnmatch
    return any(fnmatch(rel_path, pat) for pat in ignores)

def main():
    parser = argparse.ArgumentParser(description="Compare two directories and show diffs")
    parser.add_argument("old_dir", help="Baseline directory (before)")
    parser.add_argument("new_dir", help="Changed directory (after)")
    parser.add_argument("--ignore", action="append", default=[], help="Glob patterns to ignore (e.g., --ignore 'venv/**' --ignore '*.pyc')")
    parser.add_argument("--context", type=int, default=3, help="Diff context lines (default: 3)")
    parser.add_argument("--max-bytes", type=int, default=10_000_000, help="Max bytes to hash/read per file (default: 10MB)")
    args = parser.parse_args()

    old_root = Path(args.old_dir).resolve()
    new_root = Path(args.new_dir).resolve()

    if not old_root.exists() or not new_root.exists():
        print("Both paths must exist.", file=sys.stderr)
        sys.exit(1)

    old_files = list_files(old_root)
    new_files = list_files(new_root)

    # apply ignore
    if args.ignore:
        old_files = {k: v for k, v in old_files.items() if not should_ignore(k, args.ignore)}
        new_files = {k: v for k, v in new_files.items() if not should_ignore(k, args.ignore)}

    old_set = set(old_files.keys())
    new_set = set(new_files.keys())

    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    common = sorted(old_set & new_set)

    print("=== Summary ===")
    print(f"Added   : {len(added)}")
    print(f"Removed : {len(removed)}")
    print(f"Common  : {len(common)}")
    print()

    if added:
        print("=== Added files ===")
        for rel in added:
            print(f"+ {rel}")
        print()

    if removed:
        print("=== Removed files ===")
        for rel in removed:
            print(f"- {rel}")
        print()

    print("=== Modified files (with diffs for text) ===")
    for rel in common:
        old_p = old_files[rel]
        new_p = new_files[rel]

        # Quick hash to detect changes (fall back on size if huge)
        try:
            old_h = sha256(old_p) if old_p.stat().st_size <= args.max_bytes else f"SIZE:{old_p.stat().st_size}"
            new_h = sha256(new_p) if new_p.stat().st_size <= args.max_bytes else f"SIZE:{new_p.stat().st_size}"
        except Exception as e:
            print(f"[skip] {rel} (hash error: {e})")
            continue

        if old_h == new_h:
            continue  # identical

        # changed
        if is_text_file(old_p) and is_text_file(new_p):
            old_lines = read_text(old_p)
            new_lines = read_text(new_p)
            diff = difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=str(old_p),
                tofile=str(new_p),
                n=args.context,
                lineterm=""
            )
            print(f"* {rel} (text changed)")
            for line in diff:
                print(line)
            print()
        else:
            # binary or undecodable
            print(f"* {rel} (binary or non-text changed)  old={old_h}  new={new_h}")

if __name__ == "__main__":
    main()