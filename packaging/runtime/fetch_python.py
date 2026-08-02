#!/usr/bin/env python3
"""Build-time helper: download a portable CPython runtime to bundle with the
LEAF launcher.

Not shipped inside the frozen launcher itself -- this runs in CI (or locally)
to produce the `python-runtime-<os>-<arch>.tar.gz` files that
packaging/launcher/bootstrap.py looks for next to LEAF.exe / LEAF.app at
first run, and which it extracts and uses to create LEAF's real venv.

Source: astral-sh/python-build-standalone "install_only" builds -- these are
a self-contained CPython (interpreter + stdlib + pip via ensurepip), no build
toolchain artifacts, which is exactly what a throwaway venv-creation runtime
needs.

Usage:
    python packaging/runtime/fetch_python.py windows-amd64 --out packaging/launcher
    python packaging/runtime/fetch_python.py --all --out packaging/launcher
"""

from __future__ import annotations

import argparse
import shutil
import urllib.request
from pathlib import Path

# Bump these together when picking up a newer CPython / PBS release.
PYTHON_VERSION = "3.12.8"
PBS_TAG = "20241219"

# our-name -> python-build-standalone target triple
TARGETS: dict[str, str] = {
    "windows-amd64": "x86_64-pc-windows-msvc",
    "darwin-x86_64": "x86_64-apple-darwin",
    "darwin-arm64": "aarch64-apple-darwin",
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
}

BASE_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}"


def asset_url(triple: str) -> str:
    return f"{BASE_URL}/cpython-{PYTHON_VERSION}+{PBS_TAG}-{triple}-install_only.tar.gz"


def fetch_one(name: str, out_dir: Path) -> Path:
    triple = TARGETS[name]
    url = asset_url(triple)
    dest = out_dir / f"python-runtime-{name.split('-', 1)[0]}-{name.split('-', 1)[1]}.tar.gz"
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as response, open(dest, "wb") as f:
        shutil.copyfileobj(response, f)
    print(f"Wrote {dest} ({dest.stat().st_size / 1_000_000:.1f} MB)")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "targets", nargs="*", choices=list(TARGETS.keys()), help="Target(s) to fetch, e.g. windows-amd64"
    )
    parser.add_argument("--all", action="store_true", help="Fetch every supported target")
    parser.add_argument("--out", type=Path, default=Path("packaging/launcher"), help="Output directory")
    args = parser.parse_args()

    if not args.all and not args.targets:
        parser.error("Specify one or more targets, or --all")

    names = list(TARGETS.keys()) if args.all else args.targets
    args.out.mkdir(parents=True, exist_ok=True)

    for name in names:
        fetch_one(name, args.out)


if __name__ == "__main__":
    main()
