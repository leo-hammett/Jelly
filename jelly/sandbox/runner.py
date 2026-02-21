import re
import subprocess
import sys
import tempfile
from pathlib import Path

from jelly.run_logging import RunLogger

CONFTEST_CONTENT = """\
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
"""


def run_tests(
    code_files: dict[str, str],
    test_files: dict[str, str],
    timeout: int,
    logger: RunLogger | None = None,
    keep_sandbox_on_failure: bool = False,
) -> dict:
    """Execute pytest in an isolated subprocess.

    1. Creates a temp directory with src/, tests/, and conftest.py
       (conftest adds src/ to sys.path).
    2. Writes code_files into src/ and test_files into tests/.
    3. Runs: python -m pytest tests/ -v --tb=short -q
    4. Parses stdout/stderr into structured results.
    5. Cleans up the temp directory.

    Args:
        code_files: Mapping of {filename: code_content} for source files.
        test_files: Mapping of {filename: test_content} for test files.
        timeout: Maximum seconds before killing the subprocess.

    Returns:
        Dict with keys:
            all_passed: bool
            total_tests: int
            passed: int
            failed: int
            failure_details: list[dict] each with
                test_name, error_type, error_message, traceback
    """
    _log(
        logger,
        "INFO",
        "run.start",
        code_files=len(code_files),
        test_files=len(test_files),
        timeout_seconds=timeout,
    )
    tmp_dir = tempfile.mkdtemp(prefix="jelly_")
    tmp_path = Path(tmp_dir)
    result_payload: dict | None = None

    try:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        src_dir.mkdir()
        tests_dir.mkdir()

        (tmp_path / "conftest.py").write_text(CONFTEST_CONTENT)
        (src_dir / "__init__.py").write_text("")
        (tests_dir / "__init__.py").write_text("")

        for idx, (filename, content) in enumerate(code_files.items()):
            rel_path = _safe_relative_path(filename, "src", f"generated_src_{idx}.py")
            dest = src_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        for idx, (filename, content) in enumerate(test_files.items()):
            rel_path = _safe_relative_path(filename, "tests", f"test_generated_{idx}.py")
            dest = tests_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            _ensure_package_dirs(dest.parent, tests_dir)
            dest.write_text(content)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp_dir,
            )
            stdout = result.stdout
            stderr = result.stderr
            _log(
                logger,
                "INFO",
                "run.pytest_completed",
                returncode=result.returncode,
                stdout_length=len(stdout),
                stderr_length=len(stderr),
                tmp_dir=tmp_dir,
            )
        except subprocess.TimeoutExpired:
            result_payload = {
                "all_passed": False,
                "total_tests": 0,
                "passed": 0,
                "failed": 1,
                "failure_details": [
                    {
                        "test_name": "(entire suite)",
                        "error_type": "TimeoutError",
                        "error_message": f"Exceeded {timeout}s — likely O(n²) or infinite loop",
                        "traceback": "",
                    }
                ],
            }
            _log(
                logger,
                "ERROR",
                "run.timeout",
                timeout_seconds=timeout,
                tmp_dir=tmp_dir,
            )
            return result_payload

        result_payload = _parse_pytest_output(stdout, stderr)
        if result.returncode != 0:
            if result_payload["failed"] == 0:
                result_payload["failed"] = 1
                result_payload["total_tests"] = max(
                    result_payload["total_tests"],
                    result_payload["passed"] + result_payload["failed"],
                )
                result_payload["failure_details"].append({
                    "test_name": "(pytest execution)",
                    "error_type": "ExecutionError",
                    "error_message": (
                        f"pytest exited with code {result.returncode}"
                    ),
                    "traceback": (stdout + "\n" + stderr).strip()[-1000:],
                })
            result_payload["all_passed"] = False

        _log(
            logger,
            "INFO",
            "run.complete",
            all_passed=result_payload["all_passed"],
            total_tests=result_payload["total_tests"],
            failed=result_payload["failed"],
            tmp_dir=tmp_dir,
        )
        return result_payload

    finally:
        import shutil

        should_keep = (
            keep_sandbox_on_failure
            and result_payload is not None
            and not result_payload.get("all_passed", False)
        )
        if should_keep:
            _log(
                logger,
                "WARNING",
                "run.keep_sandbox_on_failure",
                tmp_dir=tmp_dir,
            )
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _safe_relative_path(filename: str, root_prefix: str, fallback: str) -> Path:
    raw = filename.replace("\\", "/")
    parts = [p for p in Path(raw).parts if p not in ("", ".", "..", "/", "\\")]
    if parts and parts[0] == root_prefix:
        parts = parts[1:]
    if not parts:
        parts = [fallback]
    return Path(*parts)


def _log(
    logger: RunLogger | None,
    level: str,
    operation: str,
    **fields,
) -> None:
    if logger:
        logger.event(level, "sandbox_runner", operation, **fields)


def _ensure_package_dirs(path: Path, root: Path) -> None:
    current = path
    while True:
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
        if current == root:
            break
        current = current.parent


def _parse_pytest_output(stdout: str, stderr: str) -> dict:
    """Parse pytest -v --tb=short -q output into a structured dict."""
    failure_details: list[dict] = []
    passed = _summary_count(stdout, "passed")
    failed = _summary_count(stdout, "failed")
    errors = _summary_count(stdout, "error")

    failed += errors

    failure_blocks = re.split(r"(?=^FAILED |^ERROR )", stdout, flags=re.MULTILINE)
    for block in failure_blocks:
        match = re.match(r"(?:FAILED|ERROR) (.*?) - (.*)", block.strip())
        if match:
            test_name = match.group(1).strip()
            error_msg = match.group(2).strip()
            error_type = error_msg.split(":")[0] if ":" in error_msg else "Error"
            failure_details.append(
                {
                    "test_name": test_name,
                    "error_type": error_type,
                    "error_message": error_msg,
                    "traceback": "",
                }
            )

    if not failure_details and failed > 0:
        tb_sections = re.findall(
            r"_{5,} (.*?) _{5,}\n(.*?)(?=_{5,}|\Z)", stdout, re.DOTALL
        )
        for test_name, tb_text in tb_sections:
            err_match = re.search(r"([\w.]+(?:Error|Exception))[:\s]*(.*)", tb_text)
            error_type = err_match.group(1) if err_match else "Error"
            error_message = err_match.group(2).strip() if err_match else tb_text.strip()[-200:]
            failure_details.append(
                {
                    "test_name": test_name.strip(),
                    "error_type": error_type,
                    "error_message": error_message,
                    "traceback": tb_text.strip()[-500:],
                }
            )

    if not failure_details and failed > 0:
        combined = stdout + "\n" + stderr
        failure_details.append(
            {
                "test_name": "(unparsed)",
                "error_type": "Error",
                "error_message": combined.strip()[-500:],
                "traceback": combined.strip()[-1000:],
            }
        )

    total = passed + failed

    return {
        "all_passed": failed == 0 and total > 0,
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "failure_details": failure_details,
    }


def _summary_count(output: str, token: str) -> int:
    match = re.search(rf"(\d+)\s+{token}s?\b", output)
    return int(match.group(1)) if match else 0
