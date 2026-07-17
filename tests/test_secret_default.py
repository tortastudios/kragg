from pathlib import Path

from kragg.gates.secret_default import check_secret_defaults
from kragg.models import Violation
from kragg.policy import KraggPolicy

SUFFIXES = KraggPolicy().secret_name_suffixes


def _scan(
    tmp_path: Path,
    code: str,
    suffixes: tuple[str, ...] = SUFFIXES,
) -> tuple[Violation, ...]:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "m.py").write_text(code)
    return check_secret_defaults(tmp_path, ("src",), suffixes)


def test_flags_env_read_with_empty_default(tmp_path: Path) -> None:
    code = 'import os\nvalue = os.environ.get("HMAC_SECRET", "")\n'

    violations = _scan(tmp_path, code)

    assert len(violations) == 1
    assert violations[0].code == "secret-default"
    assert "silently defaults to empty" in violations[0].message


def test_flags_getenv_from_import_with_hardcoded_default(tmp_path: Path) -> None:
    code = 'from os import getenv\nvalue = getenv("API_TOKEN", "dev")\n'

    violations = _scan(tmp_path, code)

    assert len(violations) == 1
    assert "hardcoded fallback" in violations[0].message


def test_flags_getenv_keyword_default(tmp_path: Path) -> None:
    code = 'import os\nvalue = os.getenv("SIGNING_KEY_SECRET", default="")\n'

    assert len(_scan(tmp_path, code)) == 1


def test_env_read_without_default_is_honest(tmp_path: Path) -> None:
    code = 'import os\nvalue = os.environ.get("API_TOKEN")\n'

    assert _scan(tmp_path, code) == ()


def test_none_default_is_honest(tmp_path: Path) -> None:
    code = 'import os\nvalue = os.getenv("API_TOKEN", None)\n'

    assert _scan(tmp_path, code) == ()


def test_non_secret_env_name_with_default_passes(tmp_path: Path) -> None:
    # the scaffolded MCP server's bind config must stay legal
    code = 'import os\nhost = os.environ.get("HOST", "127.0.0.1")\n'

    assert _scan(tmp_path, code) == ()


def test_flags_settings_class_field_defaulting_to_empty(tmp_path: Path) -> None:
    code = 'class Settings:\n    signing_secret: str = ""\n'

    violations = _scan(tmp_path, code)

    assert len(violations) == 1
    assert violations[0].line == 2


def test_flags_hardcoded_module_constant(tmp_path: Path) -> None:
    violations = _scan(tmp_path, 'API_KEY = "dev-key"\n')

    assert len(violations) == 1
    assert "hardcoded fallback" in violations[0].message


def test_none_typed_field_is_honest(tmp_path: Path) -> None:
    assert _scan(tmp_path, "class S:\n    api_token: str | None = None\n") == ()


def test_flags_parameter_defaulting_to_empty(tmp_path: Path) -> None:
    code = 'def connect(url: str, *, api_key: str = "") -> None: ...\n'

    violations = _scan(tmp_path, code)

    assert len(violations) == 1
    assert "api_key" in violations[0].message


def test_sort_key_style_names_are_out_of_scope(tmp_path: Path) -> None:
    # bare `_key` is deliberately not a default suffix
    assert _scan(tmp_path, 'sort_key = ""\n') == ()


def test_other_dict_receivers_are_out_of_scope(tmp_path: Path) -> None:
    assert _scan(tmp_path, 'value = config.get("api_token", "")\n') == ()


def test_inline_suppress_silences_a_reviewed_site(tmp_path: Path) -> None:
    code = 'import os\nv = os.environ.get("API_TOKEN", "")  # kragg: ignore\n'

    assert _scan(tmp_path, code) == ()


def test_custom_suffixes_are_honored(tmp_path: Path) -> None:
    violations = _scan(tmp_path, 'db_kennwort = ""\n', suffixes=("_kennwort",))

    assert len(violations) == 1


def test_fix_hint_demands_loud_failure(tmp_path: Path) -> None:
    violations = _scan(tmp_path, 'API_TOKEN = ""\n')

    assert violations
    assert "fails loudly" in violations[0].fix_hint
