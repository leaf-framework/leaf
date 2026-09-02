"""
Verify that every active adapter in the marketplace can be installed via pip.
Runs in isolation (separate venv) so it does not pollute the test environment.
Marked with 'marketplace' so the regular test suite can exclude it.
"""

import subprocess
import venv
from pathlib import Path

import pytest
import yaml

MARKETPLACE_PATH = Path(__file__).parent.parent / "leaf" / "data" / "marketplace.yaml"


def load_adapters():
    with open(MARKETPLACE_PATH) as f:
        return yaml.safe_load(f)


@pytest.mark.marketplace
@pytest.mark.timeout(300)
@pytest.mark.parametrize("adapter", load_adapters(), ids=lambda a: a["adapter_id"])
def test_adapter_installable(adapter, tmp_path):
    repo_url = adapter.get("repo_url")
    if not repo_url:
        pytest.skip("No repo_url defined")

    # Create an isolated venv so installs don't pollute the test environment
    venv_dir = tmp_path / "venv"
    venv.create(str(venv_dir), with_pip=True)
    pip = venv_dir / "bin" / "pip"

    result = subprocess.run(
        [str(pip), "install", f"git+{repo_url}"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"pip install failed for {adapter['adapter_id']}:\n{result.stderr}"
