import re

from jelly.agents.base import BaseAgent
from jelly.config import Config

PROGRAMMER_SYSTEM_PROMPT = """\
You are an expert programmer. You generate production-quality code from requirements.

For initial generation:
1. Parse requirements carefully. Identify inputs, outputs, constraints, edge cases.
2. Choose appropriate data structures and algorithms.
3. Write clean, idiomatic code following the language's best practices and conventions.
4. Mentally trace through basic and edge case inputs before submitting.

For refinement (fixing test failures):
1. Read the error message and failing test carefully. Identify root cause.
2. Fix ONLY what's broken. Don't refactor working code.
3. Trace the fix against the failing test to confirm it resolves the issue.

## File output format

CRITICAL: Each file must be in its own fenced code block. The VERY FIRST LINE \
inside the code fence MUST be a comment with the filename:

```python
# src/csv_parser.py
import csv
...
```

The `# src/<filename>` line is MANDATORY — without it the file cannot be saved \
correctly.

## File organization

- Group related functionality into a SMALL number of well-named files. \
Do NOT create one file per requirement — consolidate logically.
- Use descriptive filenames (e.g. `parser.py`, `stats.py`, `report.py`), \
NEVER generic names like `module_0.py` or `utils.py` for core logic.
- Source files are placed flat in a `src/` directory. Use simple top-level \
imports between them (e.g. `from parser import parse_csv`), NOT relative \
imports (`from .parser import ...`) and NOT package imports \
(`from mypackage import ...`).

## Other rules

- Use the language's type system where available
- Document public interfaces
- Handle edge cases explicitly (empty inputs, null/None, boundaries)
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
            Each file comes from a separate fenced code block with a
            '# src/filename' comment at the top.
        """
        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            "Implement all the functions specified above. Group related "
            "functionality into a small number of well-named files — do NOT "
            "create one file per requirement.\n\n"
            "Output each file in a separate fenced code block. The VERY FIRST "
            "LINE inside each code fence MUST be a `# src/<filename>` comment, "
            "for example:\n\n"
            "```python\n"
            "# src/parser.py\n"
            "import csv\n"
            "...\n"
            "```"
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
            f"### {fname}\n```\n{content}\n```"
            for fname, content in previous_code.items()
        )

        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            f"## Current Code (iteration {iteration})\n\n{code_section}\n\n"
            f"## Test Failures\n\n{error_feedback}\n\n"
            "Fix ONLY what's broken. Don't refactor working code. "
            "Output ALL files (including unchanged ones) in separate fenced code "
            "blocks. The VERY FIRST LINE inside each code fence MUST be "
            "`# src/<filename>` (e.g. `# src/parser.py`)."
        )
        response = self.agent.call(prompt, self.config.programmer_max_tokens)
        result = self._parse_code_response(response)

        for fname, content in previous_code.items():
            if fname not in result:
                result[fname] = content

        return result

    def _parse_code_response(self, response: str) -> dict[str, str]:
        """Extract filename-to-code mapping from fenced code blocks.

        Looks for fenced code blocks with a '# filename' comment on the
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
                "Your previous response didn't contain any fenced code blocks. "
                "Please output the code again, with each file in a separate "
                "fenced code block and a `# src/<filename>` comment on the first line.",
                self.config.programmer_max_tokens,
            )
            result = self._extract_files_from_response(retry_response)

        return result

    _FENCE_RE = re.compile(
        r"```(\w*[^\n]*)\n(.*?)```", re.DOTALL
    )
    _FILENAME_COMMENT_RE = re.compile(r"^#\s*(?:src/)?([\w./-]+\.\w+)")
    _FENCE_FILENAME_RE = re.compile(r"[\w]*:?\s*(?:src/)?([\w./-]+\.\w+)")

    @classmethod
    def _extract_files_from_response(cls, response: str) -> dict[str, str]:
        """Parse fenced code blocks with filename comments into a dict.

        Checks for filenames in two places:
        1. The fence opening line (e.g. ``python:src/parser.py``)
        2. The first 3 lines of content (e.g. ``# src/parser.py``)
        """
        files: dict[str, str] = {}

        for fence_meta, block in cls._FENCE_RE.findall(response):
            lines = block.strip().splitlines()
            filename = None

            for line in lines[:3]:
                match = cls._FILENAME_COMMENT_RE.match(line.strip())
                if match:
                    filename = match.group(1)
                    break

            if filename is None:
                fence_match = cls._FENCE_FILENAME_RE.search(fence_meta)
                if fence_match:
                    filename = fence_match.group(1)

            if filename is None:
                filename = f"module_{len(files)}.py"

            content_lines = [
                l for l in lines
                if not re.match(r"^#\s*(?:src/)?[\w./-]+\.\w+\s*$", l.strip())
            ]
            files[filename] = "\n".join(content_lines).strip() + "\n"

        return files
