"""Run the active backend's non-mutating foundation checks from any directory."""

import argparse
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ruff lint", ("ruff", "check", "app", "tests", "scripts", "migrations")),
    ("Ruff formatting", ("ruff", "format", "--check", "app", "tests", "scripts", "migrations")),
    ("Pyright", ("pyright", "--project", "pyproject.toml")),
    ("Pytest", ("pytest", "-q")),
)


def main() -> int:
    """Use this interpreter's tools, stopping at the first failed subprocess."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", action="store_true", help="Include real PostgreSQL tests")
    parser.add_argument(
        "--redis-integration", action="store_true", help="Include real Redis worker tests"
    )
    options = parser.parse_args()
    for label, arguments in CHECKS:
        if options.integration and label == "Pytest":
            arguments = (*arguments, "--integration")
        if options.redis_integration and label == "Pytest":
            arguments = (*arguments, "--redis-integration")
        print(f"Running {label}...", flush=True)
        result = subprocess.run([sys.executable, "-m", *arguments], cwd=BACKEND_DIR, check=False)
        if result.returncode != 0:
            print(f"{label} failed (exit {result.returncode}).", file=sys.stderr, flush=True)
            return result.returncode
    print("All backend checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
