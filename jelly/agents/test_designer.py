import re

from jelly.agents.base import BaseAgent
from jelly.config import Config

TEST_DESIGNER_SYSTEM_PROMPT = """\
You are a Test Designer. You write comprehensive pytest tests from a requirements spec. \
You have NOT seen any implementation code — you test against the SPECIFICATION, not an implementation.

Generate tests in three tiers:

1. Basic Functionality Tests
   - Happy path for each requirement
   - 3-5 tests per function

2. Edge Case Tests
   - Empty inputs, single elements, None, zero, negative numbers
   - Boundary values, duplicates, very long strings, special characters
   - 5-10 tests per function

3. Large-Scale Tests
   - Programmatically generated large inputs (10,000+ elements)
   - Use predictable inputs where expected output is calculable
   - 1-3 tests per function

Output format:
```python
# tests/test_<module>.py
import pytest

class TestBasicFunctionality:
    def test_<name>(self):
        \"\"\"What this tests.\"\"\"
        assert result == expected, f"Expected {expected}, got {result}"

class TestEdgeCases:
    ...

class TestLargeScale:
    ...
```

Rules:
- Every test has a descriptive name and docstring
- Every assert has a message
- Tests are independent — no shared state
- Use pytest.raises for expected exceptions
- Use pytest.approx for floats
- NEVER hardcode implementation-specific behavior — test the SPEC\
"""


class TestDesigner:
    """Generates tests from requirements ONLY. Never sees generated code."""

    def __init__(self, config: Config) -> None:
        """Initialize with config. Creates internal BaseAgent with test designer prompt."""
        self.config = config
        self.agent = BaseAgent(TEST_DESIGNER_SYSTEM_PROMPT, config)

    def generate_tests(
        self, requirements: str, function_signatures: list[str]
    ) -> dict[str, str]:
        """Generate pytest test files from requirements and function signatures.

        Runs ONCE per task, not per iteration. Requirements don't change
        between iterations.

        Generates three tiers of tests:
        1. Basic tests — happy path, core behavior (3-5 per function)
        2. Edge case tests — empty inputs, boundaries, None, etc. (5-10 per function)
        3. Large-scale tests — big inputs with predictable outputs (1-3 per function)

        Args:
            requirements: The full requirements document text.
            function_signatures: List of signature strings (e.g.
                ['def has_close_elements(numbers: list[float], threshold: float) -> bool:'])
                These are NOT implementations — just the API surface.

        Returns:
            Dict mapping {filename: test_file_content}.
        """
        sigs_block = "\n".join(function_signatures)
        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            f"## Function Signatures to Test\n\n```python\n{sigs_block}\n```\n\n"
            "Generate comprehensive pytest tests for these functions based on the "
            "requirements above. Output each test file in a separate ```python fence "
            "with a `# tests/test_<module>.py` comment on the first line."
        )

        response = self.agent.call(prompt, self.config.test_designer_max_tokens)
        test_files = self._parse_test_response(response)

        if not test_files:
            test_files = self._fallback_from_requirements(requirements)

        return test_files

    def _parse_test_response(self, response: str) -> dict[str, str]:
        """Parse fenced code blocks into {filename: content} for test files."""
        blocks = BaseAgent.extract_code_blocks(response)
        test_files: dict[str, str] = {}

        for block in blocks:
            lines = block.strip().splitlines()
            filename = None
            for line in lines[:3]:
                match = re.match(r"^#\s*(tests/\S+\.py)", line.strip())
                if match:
                    filename = match.group(1)
                    break

            if filename is None:
                filename = f"tests/test_generated_{len(test_files)}.py"

            content_lines = [l for l in lines if not re.match(r"^#\s*tests/\S+\.py", l.strip())]
            test_files[filename] = "\n".join(content_lines).strip() + "\n"

        return test_files

    @staticmethod
    def _fallback_from_requirements(requirements: str) -> dict[str, str]:
        """Extract any example test code from the requirements as a fallback."""
        blocks = BaseAgent.extract_code_blocks(requirements)
        test_blocks = [b for b in blocks if "def test_" in b or "assert " in b]
        if test_blocks:
            content = "\n\n".join(test_blocks)
            return {"tests/test_fallback.py": f"import pytest\n\n{content}\n"}
        return {}
