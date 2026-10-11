"""Sign the native code inside the Python runtime archive and the wheelhouse.

Apple's notarisation looks inside .tar.gz archives and wheels, and rejects every
Mach-O binary there without a Developer ID signature, a secure timestamp and the
hardened runtime. The python-build-standalone runtime and PyPI wheels ship with
none or only an ad-hoc one, so they are signed here before build_dmg.sh packs them.

Usage:
    sign_payload.py --identity "Developer ID Application: ..." runtime <python-runtime.tar.gz>
    sign_payload.py --identity "Developer ID Application: ..." wheels <wheelhouse dir>
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ENTITLEMENTS = Path(__file__).with_name("python.entitlements")

# Thin and fat Mach-O, both byte orders
MACHO_MAGICS = {
    bytes.fromhex(m) for m in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca")
}


def is_macho(path: Path) -> bool:
    # cafebabe is also a Java class file
    if path.is_symlink() or not path.is_file() or path.suffix == ".class":
        return False
    with path.open("rb") as f:
        return f.read(4) in MACHO_MAGICS


def codesign(identity: str, paths: list[Path], entitlements: bool = False) -> None:
    if not paths:
        return
    cmd = ["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", identity]
    if entitlements:
        cmd += ["--entitlements", str(ENTITLEMENTS)]
    # In batches: one call per file is slow, as each one fetches a timestamp
    for i in range(0, len(paths), 50):
        subprocess.run(cmd + [str(p) for p in paths[i : i + 50]], check=True)


def sign_tree(identity: str, root: Path) -> int:
    binaries = sorted(p for p in root.rglob("*") if is_macho(p))
    # Executables run the user's code and load pip-installed extensions, which are
    # not signed by us: they get entitlements to allow that (python.entitlements)
    executables = [p for p in binaries if p.stat().st_mode & 0o111 and p.parent.name == "bin"]
    libraries = [p for p in binaries if p not in executables]
    codesign(identity, libraries)
    codesign(identity, executables, entitlements=True)
    return len(binaries)


def sign_runtime(identity: str, archive: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="leaf-sign-runtime-") as tmp:
        root = Path(tmp)
        with tarfile.open(archive) as tf:
            tf.extractall(root, filter="tar")
        count = sign_tree(identity, root)
        with tarfile.open(archive, "w:gz") as tf:
            for top in sorted(root.iterdir()):
                tf.add(top, arcname=top.name)
    print(f"Signed {count} binaries in {archive.name}")


def record_hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"sha256={digest}"


def sign_wheel(identity: str, wheel: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="leaf-sign-wheel-") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(wheel) as zf:
            infos = zf.infolist()
            zf.extractall(root)
        binaries = [p for p in root.rglob("*") if is_macho(p)]
        if not binaries:
            return 0
        codesign(identity, binaries)

        # Signing changes the files, so the wheel's RECORD gets their new hashes and sizes
        changed = {p.relative_to(root).as_posix() for p in binaries}
        record_name = next(i.filename for i in infos if i.filename.endswith(".dist-info/RECORD"))
        rows = list(csv.reader(io.StringIO((root / record_name).read_text())))
        for row in rows:
            if row and row[0] in changed:
                data = (root / row[0]).read_bytes()
                row[1] = record_hash(data)
                row[2] = str(len(data))
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerows(rows)
        (root / record_name).write_text(out.getvalue())

        # Same entries, order and attributes as before, only new contents
        rebuilt = wheel.with_suffix(".signed")
        with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as zf:
            for info in infos:
                if info.is_dir():
                    zf.writestr(info, b"")
                else:
                    zf.writestr(info, (root / info.filename).read_bytes(), zipfile.ZIP_DEFLATED)
        rebuilt.replace(wheel)
        return len(binaries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--identity", required=True)
    parser.add_argument("kind", choices=["runtime", "wheels"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    if args.kind == "runtime":
        sign_runtime(args.identity, args.path)
    else:
        for wheel in sorted(args.path.glob("*.whl")):
            count = sign_wheel(args.identity, wheel)
            if count:
                print(f"Signed {count} binaries in {wheel.name}")


if __name__ == "__main__":
    sys.exit(main())
