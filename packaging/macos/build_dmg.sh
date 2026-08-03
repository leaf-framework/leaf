#!/usr/bin/env bash
# Build LEAF.app for macOS and package it into a distributable .dmg.
#
# Usage (run from repo root):
#   packaging/macos/build_dmg.sh [leaf-framework-version-spec]
#
# Example:
#   packaging/macos/build_dmg.sh "leaf-framework==0.6.0"
#
# If no version spec is given, the launcher pip-installs the latest
# leaf-framework release from PyPI on first run instead of a pinned version.
#
# When a version is pinned, this also bundles an offline wheelhouse (see
# packaging/runtime/build_wheelhouse.py) so first run needs no internet
# access. Set SKIP_WHEELHOUSE=1 to skip that (faster local iteration; the
# resulting build still works, just needs a network connection on first run).
#
# Optional: set CODESIGN_IDENTITY to a "Developer ID Application: ..." identity
# to sign LEAF.app before packaging. Unsigned builds work fine locally but will
# trigger Gatekeeper warnings for other users.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION_SPEC="${1:-}"
ARCH="$(uname -m)" # arm64 or x86_64
DIST_DIR="dist"
APP_PATH="$DIST_DIR/LEAF.app"
CONTENTS_MACOS="$APP_PATH/Contents/MacOS"

echo "==> Building launcher with PyInstaller"
if [ -x ".venv/bin/pyinstaller" ]; then
    PYINSTALLER_CMD=(".venv/bin/pyinstaller")
else
    # Bare `pyinstaller` relies on its console-script shim being on PATH,
    # which pip doesn't guarantee (e.g. a --user install on a CI runner's
    # system Python lands outside PATH). Module invocation sidesteps that.
    PYINSTALLER_CMD=(python3 -m PyInstaller)
fi
"${PYINSTALLER_CMD[@]}" packaging/launcher/leaf_launcher.spec \
    --distpath "$DIST_DIR" \
    --workpath build/launcher \
    --noconfirm

echo "==> Fetching portable Python runtime for darwin-$ARCH"
python3 packaging/runtime/fetch_python.py "darwin-$ARCH" --out "$CONTENTS_MACOS"

if [ -n "$VERSION_SPEC" ]; then
    echo "==> Pinning $VERSION_SPEC"
    echo "$VERSION_SPEC" > "$CONTENTS_MACOS/leaf-framework.version"

    if [ -z "${SKIP_WHEELHOUSE:-}" ]; then
        echo "==> Building offline wheelhouse"
        WHEELHOUSE_TMP="build/wheelhouse-staging"
        rm -rf "$WHEELHOUSE_TMP"
        python3 packaging/runtime/build_wheelhouse.py \
            --runtime-archive "$CONTENTS_MACOS/python-runtime-darwin-$ARCH.tar.gz" \
            --requirement "$VERSION_SPEC" \
            --out "$WHEELHOUSE_TMP"
        # Packaged as a single tar.gz, not loose .whl files, for two reasons:
        # codesign refuses to sign the bundle at all once zip-structured
        # files (which .whl files are) are present without --deep, and even
        # with --deep, pip reading dozens of --deep-signed wheels off a
        # translocated/quarantined mount (what a real download gets on
        # first launch) can loop forever instead of the normal ~10-20s.
        # bootstrap.py extracts this to a normal writable, non-quarantined
        # directory before pip ever touches the wheels.
        tar czf "$CONTENTS_MACOS/wheelhouse.tar.gz" -C "$WHEELHOUSE_TMP" .
        rm -rf "$WHEELHOUSE_TMP"
    else
        echo "==> SKIP_WHEELHOUSE set; launcher will need internet on first run"
    fi
else
    echo "==> No version pinned; launcher will install the latest leaf-framework from PyPI"
fi

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    echo "==> Codesigning with identity: $CODESIGN_IDENTITY"
    codesign --deep --force --options runtime --sign "$CODESIGN_IDENTITY" "$APP_PATH"
else
    # PyInstaller ad-hoc-signs the bundle during the build above, but the
    # runtime/wheelhouse/version files staged into Contents/MacOS just now
    # were added afterward, invalidating that seal. Gatekeeper then refuses
    # to launch the app when opened via Finder/`open` (a direct Terminal
    # exec of the binary bypasses Gatekeeper, so this only shows up for
    # real users double-clicking it). Re-sign ad-hoc to reseal the bundle
    # in its final state.
    #
    # --deep is required here, not optional: without it, codesign refuses
    # to sign at all once wheelhouse/*.whl files are present ("code object
    # is not signed at all" -- codesign treats zip-structured files as
    # needing their own nested signature, which only --deep can satisfy).
    # See the wheelhouse tar.gz packaging above for why loose .whl files
    # don't end up in the final bundle at all -- avoids a separate, real
    # bug where pip reading many --deep-signed wheels off a translocated,
    # quarantined mount (what a real downloaded copy gets on first launch)
    # would loop forever instead of the normal ~10-20s.
    echo "==> Re-signing ad-hoc to reseal after staging runtime/wheelhouse files"
    codesign --deep --force --sign - "$APP_PATH"
fi

echo "==> Packaging .dmg"
DMG_STAGING="$DIST_DIR/dmg-staging"
rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"
cp -R "$APP_PATH" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

DMG_PATH="$DIST_DIR/LEAF-macos-$ARCH.dmg"
rm -f "$DMG_PATH"
hdiutil create -volname "LEAF" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_PATH"
rm -rf "$DMG_STAGING"

echo "==> Done: $DMG_PATH"
