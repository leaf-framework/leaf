"""Sanity-check a release tag before the pipeline acts on it.

Releases are cut by a human typing `git tag vX.Y.Z`, so the version is
whatever they typed. These checks are the machine half of that: they run in
`determine_version`, before the wheel is built, the installers are packaged,
or any old installer is pruned.

Usage: check_tag.py <tag> <padded version>
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

PYPI_JSON = "https://pypi.org/pypi/leaf-framework/json"



def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def check_shape(tag: str, version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(
            f"tag {tag} does not name a MAJOR.MINOR.PATCH version (got "
            f"{version!r}). Delete the tag and re-tag, e.g. v0.11.0."
        )


def check_not_on_pypi(version: str) -> None:
    """PyPI refuses to overwrite a version, so this would fail in `publish`
    anyway -- catching it here just means finding out in seconds rather than
    after a full build. A PyPI outage is not a reason to block a release, so
    a failed lookup only warns: `poetry publish` is still the backstop."""
    try:
        with urllib.request.urlopen(PYPI_JSON, timeout=30) as response:
            releases = json.load(response).get("releases", {})
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"WARNING: could not reach PyPI to check {version}: {exc}")
        return
    if version in releases:
        fail(
            f"leaf-framework {version} is already on PyPI. Versions there are "
            f"immutable - bump to the next patch and re-tag."
        )


def all_tagged_versions(tag: str) -> list[str]:
    """Every vX.Y.Z tag in the repo except this pipeline's own."""
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        t[1:] for t in tags if t != tag and re.fullmatch(r"v\d+\.\d+\.\d+", t)
    ]


def check_step(tag: str, version: str) -> None:
    """The version has to be the next step from what's already released --
    exactly one component up, by exactly one.

    Two ways to get this wrong, and a typo lands in both: too low deletes
    things (`cleanup:old-installers` keeps exactly one version's installers
    per MAJOR.MINOR line, so tagging v0.10.5 when v0.10.20 exists would prune
    v0.10.20's downloads), and too high is permanent (a fat-fingered
    v0.10.20000 publishes to PyPI, where versions can never be reused or
    overwritten, and every later real release sorts below it).

    From highest release H, exactly three tags are accepted: H's patch + 1 on
    its own line, H.major.(H.minor + 1).0, or (H.major + 1).0.0. A patch on an
    older line is fine too, as long as it is that line's own highest + 1.

    A deliberate skip is still possible -- set the LEAF_ALLOW_VERSION_JUMP
    CI/CD variable and re-run the pipeline for the tag (Pipelines > Run
    pipeline > pick the tag). This only stops the jumps nobody meant."""
    if os.environ.get("LEAF_ALLOW_VERSION_JUMP"):
        print("LEAF_ALLOW_VERSION_JUMP set - skipping the version-step check.")
        return

    major, minor, patch = as_tuple(version)
    released = all_tagged_versions(tag)
    if not released:
        return

    line = [v for v in released if as_tuple(v)[:2] == (major, minor)]
    if line:
        # A patch release on an existing line - including an older line, which
        # is how a backport would land.
        highest = max(line, key=as_tuple)
        h_patch = as_tuple(highest)[2]
        if patch == h_patch + 1:
            return
        if patch <= h_patch:
            fail(
                f"tag {tag} goes backwards: {highest} already exists in the "
                f"{major}.{minor} line, and releasing {version} would prune "
                f"{highest}'s installers. Tag v{major}.{minor}.{h_patch + 1}."
            )
        fail(
            f"tag {tag} skips ahead of {highest} - releases move one patch at "
            f"a time, and a wrong version on PyPI can never be reused. Tag "
            f"v{major}.{minor}.{h_patch + 1}."
        )

    # A new MAJOR.MINOR line: one minor up from the highest release, or one
    # major up, starting at .0 either way.
    highest = max(released, key=as_tuple)
    h_major, h_minor, _ = as_tuple(highest)
    if (major, minor, patch) in {
        (h_major, h_minor + 1, 0),
        (h_major + 1, 0, 0),
    }:
        return
    # Same rejection either way, but say which rule was broken rather than
    # making someone infer it from the generic message below.
    if major == h_major + 1 and (minor, patch) != (0, 0):
        fail(
            f"tag {tag} opens major {major} at {minor}.{patch}. A new major "
            f"starts at v{major}.0.0."
        )
    if patch != 0:
        fail(
            f"tag {tag} opens the {major}.{minor} line at patch {patch}. A new "
            f"minor starts at v{major}.{minor}.0."
        )
    fail(
        f"tag {tag} is not the next version after {highest} (the highest "
        f"released one). Releases move by one: v{h_major}.{h_minor}."
        f"<next patch>, v{h_major}.{h_minor + 1}.0, or v{h_major + 1}.0.0. If "
        f"the jump is deliberate, set LEAF_ALLOW_VERSION_JUMP and re-run the "
        f"pipeline for this tag."
    )


def main() -> None:
    if len(sys.argv) != 3:
        fail(f"usage: {sys.argv[0]} <tag> <padded version>")
    tag, version = sys.argv[1], sys.argv[2]
    check_shape(tag, version)
    check_not_on_pypi(version)
    check_step(tag, version)
    print(f"Tag {tag} accepted as version {version}.")


if __name__ == "__main__":
    main()
