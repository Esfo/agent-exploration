import pytest

from swarm.settings import Settings, SettingsError, PLACEHOLDER_MODEL
from swarm.instructions import parse_instruction_file, InstructionError


def write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_settings_parses(tmp_path):
    sdir = tmp_path / "settings"
    sdir.mkdir()
    write(sdir, "main.settings",
          "# comment\n\nRUNTIME_NAME=x\nOLLAMA_GPU_ENDPOINT=a\nOLLAMA_CPU_ENDPOINT=b\n"
          "DEFAULT_MODEL=m\nDATABASE_PATH=runtime/state.sqlite\nFOO=true\nN=5\nC=auto\n")
    s = Settings.load(sdir / "main.settings")
    assert s.get("RUNTIME_NAME") == "x"
    assert s.get_bool("FOO") is True
    assert s.get_int("N") == 5
    assert s.is_auto("C")
    assert s.get_int("C") is None  # auto -> None


def test_settings_missing_required(tmp_path):
    sdir = tmp_path / "settings"
    sdir.mkdir()
    write(sdir, "main.settings", "RUNTIME_NAME=x\n")
    with pytest.raises(SettingsError):
        Settings.load(sdir / "main.settings")


def test_settings_bad_line(tmp_path):
    sdir = tmp_path / "settings"
    sdir.mkdir()
    write(sdir, "main.settings", "RUNTIME_NAME=x\nthis is not valid\n")
    with pytest.raises(SettingsError) as e:
        Settings.load(sdir / "main.settings")
    assert ":2:" in str(e.value)


def test_instruction_parse(tmp_path):
    p = write(tmp_path, "coding.txt",
              f"MODEL: {PLACEHOLDER_MODEL}\nPURPOSE: test\n001. first\n002. second\n# c\n")
    inst = parse_instruction_file(p)
    assert inst.model_is_placeholder
    assert inst.purpose == "test"
    assert inst.lines == ["first", "second"]


def test_instruction_concrete_model(tmp_path):
    p = write(tmp_path, "x.txt", "MODEL: qwen2.5-coder:7b\nPURPOSE: p\n001. do it\n")
    inst = parse_instruction_file(p)
    assert not inst.model_is_placeholder
    assert inst.model == "qwen2.5-coder:7b"


def test_instruction_requires_model_first(tmp_path):
    p = write(tmp_path, "bad.txt", "PURPOSE: p\n001. x\n")
    with pytest.raises(InstructionError):
        parse_instruction_file(p)
