"""Compatibility entry point for building the full Windows package."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.release.portable_release import APP_VERSION, build_windows


def main():
    build_windows(APP_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
