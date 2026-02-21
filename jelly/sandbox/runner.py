import re
import subprocess
import tempfile
from pathlib import Path

CONFTEST_CONTENT = """\
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
"""


def run_tests(
    code_files: dict[str, str],
    test_files: dict[str, str],
    timeout: int,
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
    tmp_dir = tempfile.mkdtemp(prefix="jelly_")
    tmp_path = Path(tmp_dir)

    try:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        src_dir.mkdir()
        tests_dir.mkdir()

        (tmp_path / "conftest.py").write_text(CONFTEST_CONTENT)
        (src_dir / "__init__.py").write_text("")
        (tests_dir / "__init__.py").write_text("")

        for filename, content in code_files.items():
            dest = src_dir / Path(filename).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        for filename, content in test_files.items():
            dest = tests_dir / Path(filename).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp_dir,
            )
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired:
            return {
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

        return _parse_pytest_output(stdout, stderr)

    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def _parse_pytest_output(stdout: str, stderr: str) -> dict:
    """Parse pytest -v --tb=short -q output into a structured dict."""
    failure_details: list[dict] = []
    passed = 0
    failed = 0
    errors = 0

    summary_match = re.search(
        r"(\d+) passed(?:.*?(\d+) failed)?(?:.*?(\d+) error)?", stdout
    )
    if summary_match:
        passed = int(summary_match.group(1))
        failed = int(summary_match.group(2) or 0)
        errors = int(summary_match.group(3) or 0)
    else:
        failed_only = re.search(r"(\d+) failed", stdout)
        error_only = re.search(r"(\d+) error", stdout)
        if failed_only:
            failed = int(failed_only.group(1))
        if error_only:
            errors = int(error_only.group(1))

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
