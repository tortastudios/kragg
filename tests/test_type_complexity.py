from pathlib import Path

from crag.gates.type_complexity import check_path


def test_type_complexity_flags_nested_shape(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def load() -> dict[str, list[dict[str, str]]]:\n    return {}\n")

    violations = check_path(source, max_depth=2, max_length=40)

    assert len(violations) == 1
    assert violations[0].context == "return type of load()"
