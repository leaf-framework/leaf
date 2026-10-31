from pathlib import Path

from leaf.ui.tabs.configuration import read_adapter_readme


def test_read_adapter_readme(tmp_path: Path) -> None:
    assert read_adapter_readme(str(tmp_path)) == ""
    _ = (tmp_path / "README.md").write_text("### Control")
    assert read_adapter_readme(str(tmp_path)) == "\n### Control"
