#!/usr/bin/env python3
"""Build-time helper: pre-download every wheel a pinned leaf-framework
release needs, using the SAME portable runtime that ships with the
launcher, so wheel platform/ABI tags are guaranteed to match.

Produces a directory of .whl files that packaging/launcher/bootstrap.py
installs from with `pip install --no-index --find-links`, letting LEAF's
first run work on a computer with no internet access at all.

Usage:
    python packaging/runtime/build_wheelhouse.py \
        --runtime-archive dist/LEAF/python-runtime-darwin-arm64.tar.gz \
        --requirement "leaf-framework==0.6.0" \
        --out dist/LEAF/wheelhouse
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

# The packaging pipeline's own tag (which triggers this) fires from the
# same `publish` job that just uploaded this exact version to PyPI --
# sometimes before PyPI has finished indexing it, so the very next `pip
# download` genuinely can't find a version that exists moments later.
# Observed repeatedly in practice: retrying after PyPI catches up (usually
# under a minute) always succeeds with no other change.
PYPI_PROPAGATION_RETRIES = 6
PYPI_PROPAGATION_DELAY_SECONDS = 15


def extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        raise ValueError(f"Unsupported runtime archive format: {archive}")


def find_runtime_python(runtime_dir: Path) -> Path:
    matches = [*runtime_dir.rglob("python3"), *runtime_dir.rglob("python.exe")]
    if not matches:
        raise FileNotFoundError(f"Could not locate a python executable inside extracted runtime at {runtime_dir}")
    matches.sort(key=lambda p: len(p.parts))
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--runtime-archive", required=True, type=Path, help="python-runtime-*.tar.gz/.zip from fetch_python.py"
    )
    parser.add_argument("--requirement", required=True, help='Pip requirement spec, e.g. "leaf-framework==0.6.0"')
    parser.add_argument("--out", required=True, type=Path, help="Output wheelhouse directory")
    args = parser.parse_args()

    # ignore_cleanup_errors: on Windows, a DLL the pip subprocess below just
    # loaded (e.g. libcrypto for HTTPS) can stay locked for a moment after
    # the process exits (commonly antivirus briefly scanning it), making
    # rmtree's delete fail with "Access is denied" even though the
    # subprocess already completed. Not worth failing the whole build over
    # a leftover temp dir that the OS cleans up on its own eventually.
    with tempfile.TemporaryDirectory(prefix="leaf-wheelhouse-runtime-", ignore_cleanup_errors=True) as tmp:
        runtime_dir = Path(tmp)
        extract_archive(args.runtime_archive, runtime_dir)
        runtime_python = find_runtime_python(runtime_dir)

        args.out.mkdir(parents=True, exist_ok=True)
        cmd = [str(runtime_python), "-m", "pip", "download", args.requirement, "-d", str(args.out)]
        for attempt in range(1, PYPI_PROPAGATION_RETRIES + 1):
            result = subprocess.run(cmd, check=False)
            if result.returncode == 0:
                break
            if attempt == PYPI_PROPAGATION_RETRIES:
                result.check_returncode()
            print(
                f"pip download failed (attempt {attempt}/{PYPI_PROPAGATION_RETRIES}), "
                f"retrying in {PYPI_PROPAGATION_DELAY_SECONDS}s in case PyPI hasn't "
                "finished indexing this version yet...",
                file=sys.stderr,
            )
            time.sleep(PYPI_PROPAGATION_DELAY_SECONDS)

        # Some dependencies don't publish a prebuilt wheel for every target
        # (e.g. httptools has no win_arm64 wheel on PyPI, only an sdist) --
        # `pip download` above fell back to downloading the sdist itself.
        # Rather than fail outright, try building a wheel from each sdist
        # right here with the SAME runtime python, so tags match what the
        # end user's machine needs. This still compiles at package-build
        # time only, on whatever compiler is on PATH (e.g. an activated VS
        # dev shell on a Windows runner) -- end users never need one.
        sdists = [p for p in args.out.iterdir() if p.suffix != ".whl"]
        for sdist in sdists:
            print(f"No prebuilt wheel for {sdist.name}, trying to build one locally...", file=sys.stderr)
            build_cmd = [str(runtime_python), "-m", "pip", "wheel", str(sdist), "-w", str(args.out), "--no-deps"]
            result = subprocess.run(build_cmd, check=False)
            if result.returncode == 0:
                sdist.unlink()

    non_wheels = [p.name for p in args.out.iterdir() if p.suffix != ".whl"]
    if non_wheels:
        shutil.rmtree(args.out)
        sys.exit(
            "Wheelhouse contains non-wheel files (sdists), which need a compiler on the "
            f"end user's machine and would defeat offline installs: {non_wheels}"
        )

    wheel_count = len(list(args.out.glob("*.whl")))
    print(f"Wrote {wheel_count} wheels to {args.out}")


if __name__ == "__main__":
    main()
