from jelly.sandbox.runner import run_tests


def test_run_tests_preserves_nested_paths_for_same_basename() -> None:
    code_files = {
        "src/math_a.py": "def value_a() -> int:\n    return 1\n",
        "src/math_b.py": "def value_b() -> int:\n    return 2\n",
    }
    test_files = {
        "tests/a/test_dupe.py": (
            "from math_a import value_a\n\n"
            "def test_value_a() -> None:\n"
            "    assert value_a() == 1\n"
        ),
        "tests/b/test_dupe.py": (
            "from math_b import value_b\n\n"
            "def test_value_b() -> None:\n"
            "    assert value_b() == 2\n"
        ),
    }

    results = run_tests(code_files, test_files, timeout=10)

    assert results["all_passed"] is True
    assert results["total_tests"] == 2
    assert results["failed"] == 0


def test_run_tests_marks_non_zero_exit_as_failure() -> None:
    code_files = {
        "src/broken.py": "def broken(:\n    return 1\n",
    }
    test_files = {
        "tests/test_broken.py": (
            "import broken\n\n"
            "def test_placeholder() -> None:\n"
            "    assert True\n"
        ),
    }

    results = run_tests(code_files, test_files, timeout=10)

    assert results["all_passed"] is False
    assert results["failed"] >= 1
    assert results["failure_details"]
