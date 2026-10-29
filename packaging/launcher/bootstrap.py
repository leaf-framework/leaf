"""LEAF desktop bootstrap launcher.

This is the code that gets frozen into the clickable LEAF.exe / LEAF.app.
It deliberately does almost nothing itself: it makes sure a real, pip-capable
Python environment exists for LEAF to run under, then hands off execution to
LEAF's normal `leaf` console-script entry point.

Why not just freeze the whole app (leaf + nicegui) with PyInstaller?
Because LEAF's in-app adapter installer (leaf/ui/utils.py) runs
`sys.executable -m pip install git+<repo>` to install/uninstall adapters.
Inside a PyInstaller-frozen executable, `sys.executable` is the frozen
binary itself, not a real interpreter, so `-m pip` does not work. By only
freezing this tiny bootstrapper and running the actual LEAF app under a
genuine (portable) Python interpreter, `sys.executable` stays a real
python and adapter installation keeps working exactly like it does when a
technical user runs `pip install leaf-framework` + `leaf` by hand.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

APP_NAME = "LEAF"

# Shipped next to the launcher executable by the build scripts. Contents are
# a single pip requirement spec, e.g. "leaf-framework==1.4.0". Falls back to
# unpinned "leaf-framework" (latest from PyPI) if the file is missing.
VERSION_PIN_FILE = "leaf-framework.version"

# Marks a completed bootstrap so subsequent launches skip straight to
# starting LEAF. Re-bootstraps automatically if the pinned version changes.
BOOTSTRAP_MARKER = ".leaf-bootstrap-complete"

# If a build shipped a wheelhouse (see packaging/runtime/build_wheelhouse.py)
# next to the launcher, install from it with --no-index instead of hitting
# PyPI, so first run works with zero network access. Packaged as a single
# tar.gz, not loose .whl files -- see find_wheelhouse() for why.
WHEELHOUSE_ARCHIVE_NAME = "wheelhouse.tar.gz"


def app_data_dir() -> Path:
    """Per-user, per-OS directory where LEAF's runtime and venv live."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def bundle_dir() -> Path:
    """Directory containing files shipped alongside the frozen launcher."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def venv_python_path(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"


def venv_entrypoint(venv_dir: Path, name: str) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def _detect_machine() -> str:
    """Architecture of *this running process*, not the host's raw hardware.

    platform.machine() on Windows was found to report the underlying
    hardware's native architecture unconditionally (e.g. ARM64 on a
    Windows-on-ARM machine), even when the calling process itself is a
    genuine AMD64 binary running under x64 emulation -- confirmed directly
    on real hardware: a verified AMD64 LEAF.exe still saw platform.machine()
    return "ARM64", causing bootstrap to look for a windows-arm64 runtime
    archive that was never bundled. PROCESSOR_ARCHITECTURE (an environment
    variable, not a hardware query) correctly reflects the calling
    process's own architecture instead, respecting emulation.
    """
    if platform.system() == "Windows":
        arch = os.environ.get("PROCESSOR_ARCHITECTURE", "")
        if arch:
            return arch.lower()
    return platform.machine().lower()


def find_portable_python_archive() -> Path:
    system = platform.system().lower()
    machine = _detect_machine()
    candidates = sorted(bundle_dir().glob(f"python-runtime-{system}-{machine}.*"))
    if not candidates:
        raise FileNotFoundError(
            f"No bundled Python runtime found for {system}/{machine} next to the launcher "
            f"(expected a file like python-runtime-{system}-{machine}.tar.gz)."
        )
    return candidates[0]


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
    exe_name = "python.exe" if platform.system() == "Windows" else "python3"
    matches = list(runtime_dir.rglob(exe_name))
    if not matches:
        raise FileNotFoundError(f"Could not locate {exe_name} inside extracted runtime at {runtime_dir}")
    matches.sort(key=lambda p: len(p.parts))
    return matches[0]


def find_wheelhouse(data_dir: Path) -> Path | None:
    """Extract the bundled offline wheelhouse (if any) to a writable,
    non-quarantined location and return that directory.

    Shipped as a single tar.gz and extracted here rather than read in place
    from the app bundle: a real downloaded copy is quarantined and (short
    of an interactive Finder drag) gets App Translocated to a randomized
    read-only mount on first launch. Reading dozens of individually
    code-signed wheel files directly off that mount was observed to loop
    forever (5+ minutes, never completing) instead of the normal ~10-20s --
    see packaging/README.md. Extracting once to a normal directory
    sidesteps that entirely, and also avoids codesign refusing to sign the
    bundle at all over the zip-structured .whl files if they were loose.

    Always re-extracted (not just "if empty"): this only runs once per
    bootstrap_environment() re-install, so the cost is negligible, and a
    stale wheelhouse left over from a previous app version installing an
    older pinned release would otherwise be silently reused forever --
    pip then fails to satisfy the current pin against old wheels with no
    obvious symptom beyond a broken launch.
    """
    archive = bundle_dir() / WHEELHOUSE_ARCHIVE_NAME
    if not archive.is_file():
        return None
    wheelhouse = data_dir / "wheelhouse"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    extract_archive(archive, wheelhouse)
    return wheelhouse if any(wheelhouse.glob("*.whl")) else None


def apply_tcl_tk_env(runtime_dir: Path) -> None:
    """Point tkinter at the runtime's own bundled Tcl/Tk library.

    python-build-standalone's Tcl/Tk hardcodes the library path from its own
    build environment (e.g. /tools/deps/lib/tcl8.6), which doesn't exist on
    the end user's machine -- tkinter fails with "Can't find a usable
    init.tcl" unless TCL_LIBRARY/TK_LIBRARY point at the extracted runtime's
    own copy instead.
    """
    if not runtime_dir.is_dir():
        return
    tcl_init = next(runtime_dir.rglob("init.tcl"), None)
    if tcl_init is not None:
        os.environ["TCL_LIBRARY"] = str(tcl_init.parent)
    tk_init = next(runtime_dir.rglob("tk.tcl"), None)
    if tk_init is not None:
        os.environ["TK_LIBRARY"] = str(tk_init.parent)


def read_pinned_requirement() -> str:
    spec_file = bundle_dir() / VERSION_PIN_FILE
    if spec_file.exists():
        pinned = spec_file.read_text().strip()
        if pinned:
            return pinned
    return "leaf-framework"


def show_progress_window(message: str):
    # Best-effort UI only -- a genuinely headless environment (no display
    # server at all, e.g. a bare Linux container/server) makes tk.Tk() raise
    # TclError, not ImportError. Must never let that abort the actual
    # bootstrap (venv creation, pip install) that follows this call.
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title(APP_NAME)
        root.geometry("360x120")
        root.resizable(False, False)
        tk.Label(root, text=message, font=("Helvetica", 12), wraplength=320, justify="center").pack(
            expand=True, padx=20, pady=20
        )
        # update_idletasks(), not update() -- see run_pumping_ui() below for
        # why: update() processes the entire event queue, not just redraws,
        # which is a known source of reentrant/hanging behavior.
        root.update_idletasks()
        return root
    except Exception:
        print(message)
        return None


def show_error(message: str) -> None:
    """Show an error dialog, in a *subprocess* if at all possible.

    By the time this is called, show_progress_window() has very likely
    already created and destroyed a tk.Tk() root in this same process (the
    normal case: bootstrap_environment() fails partway through, e.g. a
    version-mismatched wheelhouse making pip unable to satisfy the pin).
    tkinter only supports one Tk() root per process -- see the identical
    concern in leaf/ui/desktop_launcher.py's is_desktop_environment() --
    and creating a second one here was observed to leave the window
    blank and the process pegged at ~100% CPU forever instead of showing
    the dialog. Running it in a fresh interpreter sidesteps that; the
    extracted runtime is normally already present by the time errors here
    are possible.
    """
    script = (
        "import tkinter as tk\n"
        "from tkinter import messagebox\n"
        "r = tk.Tk()\n"
        "r.withdraw()\n"
        "messagebox.showerror(__import__('sys').argv[1], __import__('sys').argv[2])\n"
        "r.destroy()\n"
    )
    try:
        runtime_python = find_runtime_python(app_data_dir() / "runtime")
        subprocess.run([str(runtime_python), "-c", script, APP_NAME, message], timeout=60)
        return
    except Exception:
        pass

    # Last resort: no extracted runtime to run the dialog in a subprocess
    # (e.g. bootstrap failed before ever extracting one). Only reachable
    # before show_progress_window() could have created a root, so a single
    # in-process root here is safe.
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def run_pumping_ui(cmd: list[str], progress) -> None:
    """subprocess.run, but keeps the Tk progress window responsive.

    A blocking subprocess lasting 30-90s (venv creation, pip install) leaves
    an un-pumped window that macOS and Windows both flag as "Not Responding".
    update_idletasks() only flushes Tk redraws and never drains the Win32
    message queue, and update() was seen to spin reentrantly on macOS, so
    run Tk's own mainloop and poll the child from an after() callback.
    """
    popen_kwargs = {}
    if platform.system() == "Windows":
        # The launcher is a windowed exe, so each console-subsystem child
        # (python.exe -m venv / pip) would otherwise pop its own console.
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        if progress is not None:
            try:
                _wait_in_mainloop(proc, progress)
            except Exception:
                pass
        proc.wait()
    except BaseException:
        proc.kill()
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def _wait_in_mainloop(proc: subprocess.Popen, progress) -> None:
    def check() -> None:
        if proc.poll() is None:
            progress.after(100, check)
        else:
            progress.quit()

    # Closing the window mid-install must not end mainloop with pip still running.
    progress.protocol("WM_DELETE_WINDOW", lambda: None)
    progress.after(100, check)
    progress.mainloop()


def bootstrap_environment(data_dir: Path) -> Path:
    venv_dir = data_dir / "venv"
    marker = venv_dir / BOOTSTRAP_MARKER
    pinned = read_pinned_requirement()

    if marker.exists() and marker.read_text().strip() == pinned:
        return venv_dir

    progress = show_progress_window("Setting up LEAF for the first time.\nThis can take a minute...")
    try:
        runtime_dir = data_dir / "runtime"
        if not runtime_dir.exists():
            archive = find_portable_python_archive()
            extract_archive(archive, runtime_dir)

        runtime_python = find_runtime_python(runtime_dir)

        if venv_dir.exists():
            shutil.rmtree(venv_dir)
        run_pumping_ui([str(runtime_python), "-m", "venv", str(venv_dir)], progress)

        venv_python = venv_python_path(venv_dir)
        wheelhouse = find_wheelhouse(data_dir)
        if wheelhouse is not None:
            # Offline install: everything needed is already on disk, so skip
            # the network-dependent pip self-upgrade too.
            run_pumping_ui(
                [str(venv_python), "-m", "pip", "install", "--no-index", "--find-links", str(wheelhouse), pinned],
                progress,
            )
        else:
            run_pumping_ui([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], progress)
            run_pumping_ui([str(venv_python), "-m", "pip", "install", pinned], progress)

        marker.write_text(pinned)
    finally:
        if progress is not None:
            progress.destroy()

    return venv_dir


def main() -> None:
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        venv_dir = bootstrap_environment(data_dir)
    except Exception as exc:
        show_error(f"LEAF could not set up its Python environment:\n{exc}")
        sys.exit(1)

    leaf_entry = venv_entrypoint(venv_dir, "leaf")
    if not leaf_entry.exists():
        show_error(f"LEAF installation appears broken (missing {leaf_entry}).")
        sys.exit(1)

    apply_tcl_tk_env(data_dir / "runtime")

    # LEAF writes several things (logs/, cache/, its default sqlite db) to
    # relative paths under the current working directory. A double-clicked
    # GUI app has no shell-chosen cwd -- Finder/LaunchServices starts it in
    # "/", which is read-only on modern macOS and crashes LEAF at import
    # time. Give it a real, writable directory to run in instead.
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(run_dir)

    argv = [str(leaf_entry), *sys.argv[1:]]
    try:
        if platform.system() == "Windows":
            # os.execv on Windows does not replace the process in a way that
            # plays well with the GUI subsystem, so just spawn and wait.
            sys.exit(subprocess.call(argv))
        else:
            os.execv(str(leaf_entry), argv)
    except OSError as exc:
        show_error(f"LEAF could not start ({leaf_entry}):\n{exc}")
        sys.exit(1)


if __name__ == "__main__":
    # A double-clicked GUI app has no visible stdout/stderr, so an uncaught
    # exception here would otherwise look like a silent crash with zero
    # feedback. Log it and show a dialog instead.
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback

        crash_log = app_data_dir() / "bootstrap-crash.log"
        try:
            crash_log.parent.mkdir(parents=True, exist_ok=True)
            crash_log.write_text(traceback.format_exc())
        except OSError:
            pass
        show_error(f"LEAF failed to start unexpectedly.\nDetails written to:\n{crash_log}")
        raise
