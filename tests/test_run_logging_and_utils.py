import json

from jelly.run_logging import RunLogger
from jelly.utils import write_files


def test_run_logger_writes_jsonl(tmp_path) -> None:
    logger = RunLogger.create(tmp_path / "logs", level="DEBUG", project="jelly")
    logger.event("INFO", "unit_test", "event_name", value=123)

    lines = logger.log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["component"] == "unit_test"
    assert payload["operation"] == "event_name"
    assert payload["value"] == 123
    assert payload["project"] == "jelly"


def test_write_files_strips_duplicate_root_prefix(tmp_path) -> None:
    out_dir = tmp_path / "tests"
    write_files(str(out_dir), {"tests/test_sample.py": "def test_ok():\n    assert True\n"})

    assert (out_dir / "test_sample.py").exists()
    assert not (out_dir / "tests" / "test_sample.py").exists()


def test_write_files_clean_removes_stale_files(tmp_path) -> None:
    out_dir = tmp_path / "src"
    write_files(str(out_dir), {"old.py": "x = 1\n"})
    assert (out_dir / "old.py").exists()

    write_files(str(out_dir), {"new.py": "x = 2\n"}, clean=True)
    assert not (out_dir / "old.py").exists()
    assert (out_dir / "new.py").exists()
