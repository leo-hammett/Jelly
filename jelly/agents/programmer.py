import re

from jelly.agents.base import BaseAgent
from jelly.config import Config

PROGRAMMER_SYSTEM_PROMPT = """\
You are an expert Python programmer. You generate production-quality code from requirements.

For initial generation:
1. Parse requirements carefully. Identify inputs, outputs, constraints, edge cases.
2. Choose appropriate data structures and algorithms.
3. Write clean Python with type hints, docstrings, and error handling.
4. Mentally trace through basic and edge case inputs before submitting.

For refinement (fixing test failures):
1. Read the error message and failing test carefully. Identify root cause.
2. Fix ONLY what's broken. Don't refactor working code.
3. Trace the fix against the failing test to confirm it resolves the issue.

Output each file in a separate ```python fence with a # filename.py comment at the top.

Rules:
- Type hints on all function signatures
- Docstrings on public functions
- Handle edge cases explicitly (empty inputs, None, boundaries)
- Standard library preferred; minimize dependencies
- If requirements are ambiguous, make a reasonable assumption and comment it\
"""


class Programmer:
    """Generates and refines code from requirements."""

    def __init__(self, config: Config) -> None:
        """Initialize with config. Creates internal BaseAgent with programmer prompt."""
        self.config = config
        self.agent = BaseAgent(PROGRAMMER_SYSTEM_PROMPT, config)

    def generate(self, requirements: str) -> dict[str, str]:
        """Generate code from requirements using Chain-of-Thought.

        Approach: understand -> plan -> implement -> self-review.

        Args:
            requirements: The full requirements document text.

        Returns:
            Dict mapping {filename: code_content}.
            Each file comes from a separate ```python fence with a
            '# src/filename.py' comment at the top.
        """
        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            "Implement all the functions specified above. "
            "Output each file in a separate ```python fence with a "
            "`# src/<filename>.py` comment on the very first line of each fence."
        )
        response = self.agent.call(prompt, self.config.programmer_max_tokens)
        return self._parse_code_response(response)

    def refine(
        self,
        requirements: str,
        previous_code: dict[str, str],
        error_feedback: str,
        iteration: int,
    ) -> dict[str, str]:
        """Fix code based on test failure feedback.

        Must fix ONLY what's broken — don't rewrite working code.

        Args:
            requirements: The full requirements document text.
            previous_code: The current {filename: code_content} that failed.
            error_feedback: Formatted error report from TestExecutor.
            iteration: Current fix iteration number (1-indexed).

        Returns:
            Updated {filename: code_content} with fixes applied.
        """
        code_section = "\n\n".join(
            f"### {fname}\n```python\n{content}\n```"
            for fname, content in previous_code.items()
        )

        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            f"## Current Code (iteration {iteration})\n\n{code_section}\n\n"
            f"## Test Failures\n\n{error_feedback}\n\n"
            "Fix ONLY what's broken. Don't refactor working code. "
            "Output ALL files (including unchanged ones) in separate ```python fences "
            "with `# src/<filename>.py` on the first line of each fence."
        )
        response = self.agent.call(prompt, self.config.programmer_max_tokens)
        result = self._parse_code_response(response)

        for fname, content in previous_code.items():
            if fname not in result:
                result[fname] = content

        return result

    def _parse_code_response(self, response: str) -> dict[str, str]:
        """Extract filename-to-code mapping from fenced code blocks.

        Looks for ```python blocks with a '# filename.py' comment on the
        first line. If no fences found, retries the API call once with an
        explicit reminder to use code fences.

        Args:
            response: Raw text response from Claude.

        Returns:
            Dict mapping {filename: code_content}.
        """
        result = self._extract_files_from_response(response)

        if not result:
            retry_response = self.agent.call(
                "Your previous response didn't contain any ```python code fences. "
                "Please output the code again, with each file in a separate "
                "```python fence and a `# src/<filename>.py` comment on the first line.",
                self.config.programmer_max_tokens,
            )
            result = self._extract_files_from_response(retry_response)

        return result

    @staticmethod
    def _extract_files_from_response(response: str) -> dict[str, str]:
        """Parse fenced code blocks with filename comments into a dict."""
        blocks = BaseAgent.extract_code_blocks(response)
        files: dict[str, str] = {}

        for block in blocks:
            lines = block.strip().splitlines()
            filename = None
            for line in lines[:3]:
                match = re.match(r"^#\s*(?:src/)?([\w./]+\.py)", line.strip())
                if match:
                    filename = match.group(1)
                    break

            if filename is None:
                filename = f"module_{len(files)}.py"

            content_lines = [
                l for l in lines
                if not re.match(r"^#\s*(?:src/)?[\w./]+\.py\s*$", l.strip())
            ]
            files[filename] = "\n".join(content_lines).strip() + "\n"

        return files
