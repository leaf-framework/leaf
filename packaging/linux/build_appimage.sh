#!/usr/bin/env bash
# Build a LEAF AppImage for Linux.
#
# Usage (run from repo root):
#   packaging/linux/build_appimage.sh [leaf-framework-version-spec]
#
# Needs Python 3.12+ with Tk available (Debian/Ubuntu: apt install python3-tk)
# and PyInstaller (pip installed automatically below).
#
# Built on whatever glibc the host/container provides -- for broad distro
# compatibility this should run on the OLDEST glibc you want to support
# (e.g. Debian bullseye, glibc 2.31), not the newest available image.
#
# When a version is pinned, this also bundles an offline wheelhouse (see
# packaging/runtime/build_wheelhouse.py) so first run needs no internet
# access. Set SKIP_WHEELHOUSE=1 to skip that.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION_SPEC="${1:-}"
ARCH="$(uname -m)" # x86_64 or aarch64
DIST_DIR="dist"
APPDIR="$DIST_DIR/AppDir"

case "$ARCH" in
    x86_64) RUNTIME_TARGET="linux-x86_64" ;;
    aarch64) RUNTIME_TARGET="linux-aarch64" ;;
    *)
        echo "Unsupported architecture: $ARCH" >&2
        exit 1
        ;;
esac

echo "==> Building launcher with PyInstaller"
if [ -x ".venv/bin/pyinstaller" ]; then
    PYINSTALLER_CMD=(".venv/bin/pyinstaller")
else
    python3 -m pip install "pyinstaller~=6.19"
    PYINSTALLER_CMD=(python3 -m PyInstaller)
fi
"${PYINSTALLER_CMD[@]}" packaging/launcher/leaf_launcher.spec \
    --distpath "$DIST_DIR" \
    --workpath build/launcher \
    --noconfirm

echo "==> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
cp -R "$DIST_DIR/LEAF" "$APPDIR/LEAF"
cp packaging/linux/LEAF.desktop "$APPDIR/"
cp packaging/linux/icon.png "$APPDIR/"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/LEAF/LEAF" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "==> Fetching portable Python runtime for $RUNTIME_TARGET"
python3 packaging/runtime/fetch_python.py "$RUNTIME_TARGET" --out "$APPDIR/LEAF"

if [ -n "$VERSION_SPEC" ]; then
    echo "==> Pinning $VERSION_SPEC"
    echo "$VERSION_SPEC" > "$APPDIR/LEAF/leaf-framework.version"

    if [ -z "${SKIP_WHEELHOUSE:-}" ]; then
        echo "==> Building offline wheelhouse"
        WHEELHOUSE_TMP="build/wheelhouse-staging"
        rm -rf "$WHEELHOUSE_TMP"
        python3 packaging/runtime/build_wheelhouse.py \
            --runtime-archive "$APPDIR/LEAF/python-runtime-$RUNTIME_TARGET.tar.gz" \
            --requirement "$VERSION_SPEC" \
            --out "$WHEELHOUSE_TMP"
        # A single tar.gz, not loose .whl files -- bootstrap.py expects this
        # format on every platform (see its find_wheelhouse() docstring for
        # why: a macOS-specific codesign/App-Translocation bug, but the
        # launcher code is shared, so the packaging format stays uniform).
        tar czf "$APPDIR/LEAF/wheelhouse.tar.gz" -C "$WHEELHOUSE_TMP" .
        rm -rf "$WHEELHOUSE_TMP"
    else
        echo "==> SKIP_WHEELHOUSE set; launcher will need internet on first run"
    fi
else
    echo "==> No version pinned; launcher will install the latest leaf-framework from PyPI"
fi

echo "==> Fetching appimagetool"
APPIMAGETOOL="build/appimagetool-$ARCH.AppImage"
if [ ! -x "$APPIMAGETOOL" ]; then
    mkdir -p build
    curl -fsSL -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "==> Building AppImage"
APPIMAGE_PATH="$DIST_DIR/LEAF-linux-$ARCH.AppImage"
rm -f "$APPIMAGE_PATH"
# --appimage-extract-and-run: appimagetool is itself an AppImage, which
# normally needs FUSE to run -- this makes it self-extract instead, which
# works in containers/CI runners that don't have /dev/fuse.
"$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE_PATH"

echo "==> Done: $APPIMAGE_PATH"
