# LEAF desktop packaging

Turns `pip install leaf-framework && leaf` into a double-clickable app for
non-technical users, without breaking the in-app adapter installer.

## Why this design

LEAF's adapter installer (`leaf/ui/utils.py`, `install_adapter`/`uninstall_adapter`)
runs `sys.executable -m pip install git+<repo>` at runtime. Freezing the whole
app with PyInstaller (as a single bundled executable) breaks this: inside a
frozen build, `sys.executable` is the frozen binary itself, not a real Python
interpreter, so `-m pip` doesn't work and adapter installs silently fail.

Instead, only a tiny bootstrapper (`launcher/bootstrap.py`, stdlib + tkinter
only) gets frozen. On first run it:

1. Extracts a bundled portable CPython ("runtime") next to itself.
2. Creates a real venv from that runtime under the user's app-data directory.
3. `pip install`s a pinned `leaf-framework` release into that venv.
4. Hands off execution to the venv's own `leaf` console-script entry point.

Every subsequent launch skips straight to step 4. Because LEAF then runs
under a genuine venv Python, `sys.executable` is correct and adapter
installs work identically to a technical user's terminal-based `pip install`
— no changes needed to `leaf/ui/utils.py`.

If a build bundled an offline wheelhouse (see below), step 3 installs with
`pip install --no-index --find-links <wheelhouse>` instead of hitting PyPI,
so first run needs no internet access at all — only the adapter installer
still needs a connection, same as it would for a technical user.

This was verified end-to-end locally, including with PyPI made unreachable:
built `LEAF.app` and the `.dmg`, mounted it, launched the app fresh, and
watched it bootstrap a venv from the bundled wheelhouse with zero network
access, then start LEAF's normal startup sequence.

## Layout

```
packaging/
  launcher/
    bootstrap.py            # frozen into LEAF.exe / LEAF.app
    leaf_launcher.spec       # PyInstaller spec for the launcher only
    leaf-framework.version   # (generated at build time) pinned pip spec
    python-runtime-*.tar.gz  # (generated at build time) portable Python payloads
    wheelhouse.tar.gz         # (generated at build time) offline wheel cache
  runtime/
    fetch_python.py          # downloads python-build-standalone runtimes
    build_wheelhouse.py      # pre-downloads leaf-framework's wheels for offline installs
  windows/
    leaf.iss                 # Inno Setup installer script
  macos/
    build_dmg.sh              # builds LEAF.app and packages a .dmg
  linux/
    LEAF.desktop              # AppImage desktop entry
    icon.png                  # AppImage icon (generated from leaf/ui/images/icon.svg)
    build_appimage.sh         # builds a LEAF AppImage
```

At runtime, LEAF's venv and extracted Python runtime live in:

- Windows: `%LOCALAPPDATA%\LEAF\`
- macOS: `~/Library/Application Support/LEAF/`
- Linux: `~/.local/share/LEAF/` (or `$XDG_DATA_HOME/LEAF`)

Uninstalling the app (Windows installer / dragging LEAF.app to Trash) does
not touch this directory, so a reinstall doesn't need to re-download
anything. Users wanting a full wipe can delete it manually.

LEAF itself writes several things (`logs/`, `cache/`, its default sqlite db)
to relative paths under the process's current working directory. A
double-clicked GUI app has no shell-chosen cwd -- on macOS, Finder starts
apps with cwd `/`, which is read-only and crashes LEAF at import time before
any window can even appear (a direct Terminal exec of the same binary
doesn't hit this, since it inherits the shell's writable cwd -- easy to miss
in testing for exactly that reason). `bootstrap.py` works around this by
`chdir`ing into `<app-data-dir>/run/` before handing off to `leaf`, so
these end up somewhere sane and writable regardless of how the app was
launched.

LEAF's desktop control panel (the small tkinter window with Open
Browser/Stop buttons) also silently failed to appear: python-build-standalone's
bundled Tcl/Tk hardcodes a library path from its own build environment
(`/tools/deps/lib/tcl8.6`), which doesn't exist on the end user's machine.
`tkinter.Tk()` fails with `TclError: Can't find a usable init.tcl`, which
`leaf`'s desktop-environment check catches broadly and logs only at debug
level -- so it silently falls back to headless/browser-only mode instead of
erroring visibly. `bootstrap.py` fixes this by setting
`TCL_LIBRARY`/`TK_LIBRARY` to the runtime's own bundled Tcl/Tk directories
(found via `apply_tcl_tk_env`) before handing off to `leaf`.

`show_progress_window` (the "Setting up LEAF..." window shown during first
run) originally only handled tkinter being altogether unavailable
(`ImportError`). On a genuinely headless machine -- no display server at
all, e.g. a bare Linux server/container -- `tk.Tk()` instead raises
`TclError`, which was uncaught and aborted the whole bootstrap before venv
creation even started. Found via Linux AppImage testing, but the fix
(catch broadly, fall back to a plain `print`) applies on every platform.

**The wheelhouse is a single `wheelhouse.tar.gz`, not loose `.whl` files.**
`codesign --force --sign -` (no `--deep`) on a bundle containing loose
`.whl` files (zip-structured) fails outright: `code object is not signed at
all`. `--deep` is required for signing to succeed at all once any
zip-structured file is present, so this is still necessary -- but it is
*not* what fixes the hang described below (an earlier version of this
doc claimed it was; it didn't, and only appeared to because the hang is
intermittent). Packaged as one tar.gz, `bootstrap.py`'s `find_wheelhouse()`
extracts it to a normal writable, non-quarantined directory before pip
reads any wheel, which is good practice regardless (translocation
irrelevant to that read) but wasn't the actual root cause either.

**The real bug: `run_pumping_ui` calling `root.update()` in a tight polling
loop.** A locally built, never-quarantined `LEAF.app` looks fine either
way -- this only showed up for an actual downloaded, quarantined copy, and
only intermittently, which made it genuinely difficult to pin down (two
earlier "fixes" -- dropping `--deep`, then the wheelhouse tar.gz repackaging
-- each seemed to work in a handful of manual tests, purely from luck).
`update()` processes the *entire* Tk event queue, not just redraws, which
Tk's own documentation warns can cause reentrant/recursive callback
processing -- confirmed here with a real Python-level traceback
(`faulthandler.dump_traceback_later`) showing the *main thread* (not a
subprocess) stuck in deep, repeating recursion through
`_PyEval_EvalFrameDefault`, specifically under quarantine + App
Translocation (a real download gets both on first launch, short of an
interactive Finder drag, which can't be scripted to verify). Switching to
`update_idletasks()` -- which only flushes pending redraws, all this
actually needs -- fixed it: 8/8 consecutive runs with genuine quarantine +
translocation active, no hangs, versus frequent 5+ minute hangs
(oscillating memory, never completing) before.

Moral: with an intermittent bug, a handful of successful manual tests is
not confirmation. Get to double digits, and get an actual traceback of the
stuck thread before believing a fix.

Confirmed by reproducing with genuine quarantine + translocation
(`xattr -w com.apple.quarantine ... /Applications/LEAF.app` triggers
translocation without needing an actual browser download each time) --
loose `.whl` files reproduced the hang every time even after `--deep`
signing (the resulting bundle even worked when *not* actually re-signed
with `--deep`, since it was silently reusing an already-signed leftover
from a previous test, which is what made this misleading at first); the
tar.gz form didn't hang once, repeatedly, under the same conditions.

## Building

### macOS

```
packaging/macos/build_dmg.sh "leaf-framework==<version>"
```

Produces `dist/LEAF-macos-<arch>.dmg`. Run natively per architecture
(arm64/x86_64) — this is not cross-compiled. Set `CODESIGN_IDENTITY` to a
"Developer ID Application: ..." identity to sign the app before packaging
(unsigned builds work locally but trigger Gatekeeper warnings for others;
notarization is not yet wired up).

When you pass a version, the script also builds an offline wheelhouse (see
below) so the resulting `.dmg` needs no internet on first run. Set
`SKIP_WHEELHOUSE=1` to skip that for faster local iteration.

### Windows

Requires a Windows machine (or CI runner) with Python 3.12+ and
[Inno Setup 6](https://jrsoftware.org/isinfo.php) installed:

```
python -m pip install "pyinstaller~=6.19"
python -m PyInstaller packaging\launcher\leaf_launcher.spec --distpath dist --workpath build\launcher --noconfirm
python packaging\runtime\fetch_python.py windows-amd64 --out dist\LEAF
echo leaf-framework==<version> > dist\LEAF\leaf-framework.version

:: Optional but recommended: bundle an offline wheelhouse, same as macOS.
:: Packaged as a single tar.gz (bootstrap.py expects this exact filename on
:: every platform) -- tar.exe ships built into Windows 10 1803+/11.
python packaging\runtime\build_wheelhouse.py --runtime-archive dist\LEAF\python-runtime-windows-amd64.tar.gz --requirement "leaf-framework==<version>" --out build\wheelhouse-staging
tar czf dist\LEAF\wheelhouse.tar.gz -C build\wheelhouse-staging .

set LEAF_VERSION=<version>
ISCC packaging\windows\leaf.iss
```

### Linux

Unlike macOS/Windows, this needs no native machine or special runner --
it's a plain ELF binary, buildable in any Docker container with Tk
available (Debian/Ubuntu: `apt install python3-tk`). Build on the *oldest*
glibc you want to support, not the newest available image; `package:linux`
in CI uses `python:3.12-slim-bullseye` (glibc 2.31) for that reason.

```
packaging/linux/build_appimage.sh "leaf-framework==<version>"
```

Produces `dist/LEAF-linux-<arch>.AppImage` (arch is whatever `uname -m`
reports on the build machine -- not cross-compiled). Downloads
`appimagetool` into `build/` on first run and reuses it after that. Same
`SKIP_WHEELHOUSE=1` escape hatch as macOS for faster local iteration.

Produces `packaging\windows\Output\LEAF-Setup-amd64.exe` (arch-tagged, same
convention as macOS/Linux, so a future ARM64 Windows build won't collide
with this one). Installs per-user (no admin prompt) to
`%LOCALAPPDATA%\Programs\LEAF`.

### Offline installs (no internet on the target computer)

`packaging/runtime/build_wheelhouse.py` pre-downloads every wheel a pinned
`leaf-framework` release needs, using the *same* portable runtime that ships
with the launcher (so platform/ABI tags match exactly — no cross-platform
wheel resolution guesswork). `bootstrap.py` automatically prefers this
wheelhouse over PyPI when one is bundled (`pip install --no-index
--find-links`), so a build with a wheelhouse works with zero network access
on first run — verified locally with PyPI made deliberately unreachable.

The tool hard-fails if any dependency has no prebuilt wheel for the target
platform (an sdist would need a compiler on the end user's machine, which
defeats the purpose) — currently everything `leaf-framework` depends on
ships wheels for all five supported targets. A pinned build adds ~40MB and
about a minute of build time; both `build_dmg.sh` and the GitLab CI jobs
build one by default.

### GitLab CI

`.gitlab-ci.yml` has `package`/`release` stages that run automatically on the
tag pipeline `publish` triggers (i.e. only for actual releases from `main`,
not every commit).

`package:linux` needs no special runner -- it runs in a plain
`python:3.12-slim-bullseye` Docker image on whatever untagged shared runner
already handles `lint`/`test`/`determine_version`.

`package:macos` and `package:windows` need self-hosted runners:

- A runner tagged `macos`, with Python 3.12+ on PATH.
- A runner tagged `windows`, with Python 3.12+ and
  [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed at the path in
  `ISCC_PATH` (default `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`;
  override via a CI/CD variable if installed elsewhere). The job scripts are
  written for a PowerShell-shell runner.

`package:windows` (and the job that attaches its release asset link) only
run when the `WINDOWS_RUNNER_READY` CI/CD variable is set to `"true"`. Until
a `windows`-tagged runner actually exists, leaving that variable unset means
the job is never created in the pipeline at all -- rather than sitting
`pending` forever with no runner to claim it, which blocks `release` behind
it (GitLab shows this as "no runners ... match all of the job's tags: windows").
Set the variable in Settings → CI/CD → Variables once the runner is
registered.

All three jobs upload their installer to the project's Generic Package
Registry (`packages/generic/leaf-desktop/<version>/...`) and the `release`
job attaches them as asset links on a GitLab Release for the tag. No extra
token setup is needed — `CI_JOB_TOKEN` already has package-registry write
access for the project's own pipelines.

### Fetching portable Python runtimes manually

`packaging/runtime/fetch_python.py` downloads
[astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone)
"install_only" CPython builds. Supported targets: `windows-amd64`,
`darwin-x86_64`, `darwin-arm64`, `linux-x86_64`, `linux-aarch64`.

```
python packaging/runtime/fetch_python.py --all --out packaging/launcher
```

## Not yet done

- Code signing / notarization for macOS, code signing for Windows.
- Linux `.deb`/`.rpm` packages, or submitting the AppImage to AppImageHub.
