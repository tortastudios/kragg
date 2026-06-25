from pathlib import Path

from kragg.gates.nullable_default import check_nullable_defaults
from kragg.models import Violation


def _scan(tmp_path: Path, code: str) -> tuple[Violation, ...]:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "m.py").write_text(code)
    return check_nullable_defaults(tmp_path, ("src",))


def test_flags_the_incident_idiom(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        'x = chatgpt.get("impressions", 0) + aio.get("impressions", 0)\n',
    )
    assert len(violations) == 1
    assert violations[0].code == "nullable-default"


def test_accumulator_is_not_flagged(tmp_path: Path) -> None:
    # one operand is a literal — the canonical correct `.get(k, 0)` use
    assert _scan(tmp_path, "freq = {}\nn = freq.get('a', 0) + 1\n") == ()


def test_none_default_is_not_flagged(tmp_path: Path) -> None:
    assert _scan(tmp_path, "x = a.get('p', None) + b.get('q', None)\n") == ()


def test_all_caps_constant_map_is_not_flagged(tmp_path: Path) -> None:
    assert _scan(tmp_path, 'x = WEIGHTS["a"] * SCORE.get("k", 0)\n') == ()


def test_subtraction_both_get_is_flagged(tmp_path: Path) -> None:
    violations = _scan(tmp_path, 'd = new.get("c", 0) - old.get("c", 0)\n')
    assert len(violations) == 1


def test_comparison_is_out_of_scope_by_design(tmp_path: Path) -> None:
    # arithmetic-only keeps precision high; comparison is a documented residual
    assert _scan(tmp_path, 'flag = a.get("x", 0) > b.get("y", 0)\n') == ()


def test_string_formatting_is_not_flagged(tmp_path: Path) -> None:
    assert _scan(tmp_path, "msg = f\"{a.get('x', 0)}-{b.get('y', 0)}\"\n") == ()


def test_inline_suppress_silences_a_reviewed_site(tmp_path: Path) -> None:
    code = 'x = a.get("i", 0) + b.get("i", 0)  # kragg: ignore\n'
    assert _scan(tmp_path, code) == ()


def test_fix_hint_does_not_recommend_or(tmp_path: Path) -> None:
    violations = _scan(tmp_path, 'x = a.get("i", 0) + b.get("i", 0)\n')
    assert violations
    assert "never `or`" in violations[0].fix_hint
