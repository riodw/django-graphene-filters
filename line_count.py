"""Line count summary for Python files in the project.

Usage:
    python line_count.py
"""

import os
from pathlib import Path

# Directories to skip entirely
SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".tox", "dist", "build", ".eggs"}


def count_lines(filepath: Path) -> tuple[int, int, int]:
    """Count total, code, and comment lines in a Python file.

    Returns:
        (total_lines, code_lines, comment_lines)
        where code_lines = total - blank - comments
    """
    total = 0
    blank = 0
    comments = 0
    in_docstring = False
    docstring_char = None

    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            total += 1
            stripped = line.strip()

            # Track multiline docstrings (triple-quoted strings)
            if in_docstring:
                comments += 1
                if docstring_char in stripped and stripped.count(docstring_char) % 2 == 1:
                    in_docstring = False
                continue

            # Check for docstring start
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = stripped[:3]
                comments += 1
                # Single-line docstring (opens and closes on same line)
                rest = stripped[3:]
                if quote in rest:
                    continue
                # Multiline docstring starts
                in_docstring = True
                docstring_char = quote
                continue

            if stripped == "":
                blank += 1
            elif stripped.startswith("#"):
                comments += 1

    code = total - blank - comments
    return total, code, comments


def scan_directory(root: Path) -> dict[str, tuple[int, int, int]]:
    """Walk a directory and count lines for all .py files.

    Returns:
        dict mapping relative file path to (total, code, comments)
    """
    results = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            filepath = Path(dirpath) / fname
            rel = filepath.relative_to(root)
            results[str(rel)] = count_lines(filepath)

    return results


def print_table(title: str, results: dict[str, tuple[int, int, int]]) -> None:
    """Print a formatted table of line counts."""
    total_all = sum(t for t, _, _ in results.values())
    code_all = sum(c for _, c, _ in results.values())
    comments_all = sum(cm for _, _, cm in results.values())
    blank_all = total_all - code_all - comments_all
    file_count = len(results)

    col1 = max(len(f) for f in results) if results else 10
    col1 = max(col1, len("TOTAL"))

    header = f"{'File':<{col1}}  {'Total':>7}  {'Code':>7}  {'Comments':>8}  {'Blank':>7}"
    sep = "-" * len(header)

    print()
    print(f"  {title}")
    print(f"  {file_count} Python files")
    print()
    print(f"  {header}")
    print(f"  {sep}")

    for filepath in sorted(results):
        total, code, comments = results[filepath]
        blank = total - code - comments
        print(f"  {filepath:<{col1}}  {total:>7}  {code:>7}  {comments:>8}  {blank:>7}")

    print(f"  {sep}")
    print(f"  {'TOTAL':<{col1}}  {total_all:>7}  {code_all:>7}  {comments_all:>8}  {blank_all:>7}")
    print()


def main() -> None:
    """Print line count tables for the package and the entire project."""
    project_root = Path(__file__).parent

    # Table 1: django_graphene_filters package only
    pkg_dir = project_root / "django_graphene_filters"
    if pkg_dir.is_dir():
        pkg_results = scan_directory(pkg_dir)
        print_table("django_graphene_filters/", pkg_results)

    # Table 2: entire project
    all_results = scan_directory(project_root)
    print_table("Entire project", all_results)


if __name__ == "__main__":
    main()
