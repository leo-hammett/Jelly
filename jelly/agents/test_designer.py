import json
import re
from dataclasses import dataclass, field
from typing import Any

from jelly.agents.base import BaseAgent
from jelly.config import Config
from jelly.mcp import MCPServer, MCPTestPlan, MCPTestStep, install_server

TEST_DESIGNER_SYSTEM_PROMPT = """\
You are a Test Designer. You write comprehensive tests from a requirements spec. \
You have NOT seen any implementation code — you test against the SPECIFICATION, not an implementation.

Generate tests in three tiers:

1. Basic Functionality Tests
   - Happy path for each requirement
   - 3-5 tests per function/method

2. Edge Case Tests
   - Empty inputs, single elements, null/None, zero, negative numbers
   - Boundary values, duplicates, very long strings, special characters
   - 5-10 tests per function/method

3. Large-Scale Tests
   - Programmatically generated large inputs (10,000+ elements)
   - Use predictable inputs where expected output is calculable
   - 1-3 tests per function/method

Output each test file in a separate fenced code block with a \
`# tests/test_<module>.<ext>` comment on the first line. \
Organize tests into logical groups (classes, modules, or describe blocks) \
as appropriate for the language and testing framework.

Rules:
- Every test has a descriptive name
- Every assertion includes a message
- Tests are independent — no shared state
- Use appropriate mechanisms for testing exceptions and float comparisons
- NEVER hardcode implementation-specific behavior — test the SPEC\
"""


@dataclass
class TestDesignResult:
    """Everything the test designer produces in one shot."""

    unit_test_files: dict[str, str] = field(default_factory=dict)
    mcp_test_plan: MCPTestPlan = field(default_factory=MCPTestPlan)
    installed_servers: list[MCPServer] = field(default_factory=list)


class TestDesigner:
    """Generates tests from requirements ONLY. Never sees generated code."""

    def __init__(self, config: Config) -> None:
        """Initialize with config. Creates internal BaseAgent with test designer prompt."""
        self.config = config
        self.agent = BaseAgent(TEST_DESIGNER_SYSTEM_PROMPT, config)

    def generate_tests(
        self, requirements: str, function_signatures: list[str]
    ) -> dict[str, str]:
        """Generate test files from requirements and function signatures.

        Runs ONCE per task, not per iteration. Requirements don't change
        between iterations.

        Generates three tiers of tests:
        1. Basic tests — happy path, core behavior (3-5 per function)
        2. Edge case tests — empty inputs, boundaries, null/None, etc. (5-10 per function)
        3. Large-scale tests — big inputs with predictable outputs (1-3 per function)

        Args:
            requirements: The full requirements document text.
            function_signatures: List of signature/declaration strings
                representing the API surface to test.

        Returns:
            Dict mapping {filename: test_file_content}.
        """
        sigs_block = "\n".join(function_signatures)
        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            f"## Function Signatures to Test\n\n```\n{sigs_block}\n```\n\n"
            "Generate comprehensive tests for these functions based on the "
            "requirements above. Output each test file in a separate fenced code block "
            "with a `# tests/test_<module>.<ext>` comment on the first line."
        )

        response = self.agent.call(prompt, self.config.test_designer_max_tokens)
        test_files = self._parse_test_response(response)

        if not test_files:
            test_files = self._fallback_from_requirements(requirements)

        return test_files

    _FENCE_RE = re.compile(r"```(\w*[^\n]*)\n(.*?)```", re.DOTALL)
    _TEST_FILENAME_COMMENT_RE = re.compile(r"^#\s*((?:tests/)?\S+\.\w+)")
    _TEST_FENCE_FILENAME_RE = re.compile(r"[\w]*:?\s*((?:tests/)?\S+\.\w+)")

    def _parse_test_response(self, response: str) -> dict[str, str]:
        """Parse fenced code blocks into {filename: content} for test files.

        Checks for filenames in two places:
        1. The first 3 lines of content (e.g. ``# tests/test_parser.py``)
        2. The fence opening line (e.g. ``python:tests/test_parser.py``)
        """
        test_files: dict[str, str] = {}

        for fence_meta, block in self._FENCE_RE.findall(response):
            lines = block.strip().splitlines()
            filename = None

            for line in lines[:3]:
                match = self._TEST_FILENAME_COMMENT_RE.match(line.strip())
                if match:
                    filename = match.group(1)
                    break

            if filename is None:
                fence_match = self._TEST_FENCE_FILENAME_RE.search(fence_meta)
                if fence_match:
                    filename = fence_match.group(1)

            if filename is None:
                filename = f"tests/test_generated_{len(test_files)}.py"

            if not filename.startswith("tests/"):
                filename = f"tests/{filename}"

            content_lines = [
                l for l in lines
                if not re.match(r"^#\s*(?:tests/)?\S+\.\w+\s*$", l.strip())
            ]
            test_files[filename] = "\n".join(content_lines).strip() + "\n"

        return test_files

    @staticmethod
    def _fallback_from_requirements(requirements: str) -> dict[str, str]:
        """Extract any example test code from the requirements as a fallback."""
        blocks = BaseAgent.extract_code_blocks(requirements)
        test_blocks = [b for b in blocks if "test" in b.lower() and "assert" in b.lower()]
        if test_blocks:
            content = "\n\n".join(test_blocks)
            return {"tests/test_fallback.py": content + "\n"}
        return {}

    # ------------------------------------------------------------------
    # New multi-phase design pipeline
    # ------------------------------------------------------------------

    def design_tests(
        self, requirements: str, function_signatures: list[str]
    ) -> TestDesignResult:
        """Full pipeline: analyze reqs, pick tools, install them, generate tests.

        Returns a TestDesignResult containing unit test files, an MCP test
        plan, and the list of servers that were installed.
        """
        analysis = self._analyze_requirements(requirements)
        servers = self._select_tools(analysis)
        installed = self._install_tools(servers)
        unit_tests, mcp_plan = self._generate_test_plan(
            requirements, function_signatures, installed
        )
        return TestDesignResult(
            unit_test_files=unit_tests,
            mcp_test_plan=mcp_plan,
            installed_servers=installed,
        )

    def adapt_tests(
        self,
        code_files: dict[str, str],
        test_files: dict[str, str],
    ) -> dict[str, str]:
        """Rewrite test imports and references to match the actual generated code.

        The test designer generates tests from the spec before code exists,
        so imports and function/class names may not match. This method asks
        the LLM to fix those references while preserving all test logic.

        Args:
            code_files: {filename: code_content} as produced by the Programmer.
            test_files: {filename: test_content} as produced by generate_tests.

        Returns:
            Updated {filename: test_content} with corrected imports.
        """
        code_summary = "\n\n".join(
            f"### {fname}\n```\n{content}\n```"
            for fname, content in code_files.items()
        )
        tests_section = "\n\n".join(
            f"### {fname}\n```\n{content}\n```"
            for fname, content in test_files.items()
        )

        agent = BaseAgent(
            "You adapt test files so their imports and references match the "
            "actual source code. You NEVER change test logic, assertions, or "
            "test structure — only fix imports and name references.",
            self.config,
        )
        prompt = (
            "## Project layout\n\n"
            "Source files live flat inside `src/` (added to sys.path by "
            "conftest.py). To import a function from `src/parser.py`, tests "
            "use:\n"
            "```python\n"
            "from parser import parse_csv\n"
            "```\n"
            "NOT `from csv_dashboard import parse_csv` or "
            "`from src.parser import parse_csv`.\n\n"
            "## Actual Source Code\n\n"
            f"{code_summary}\n\n"
            "## Test Files to Adapt\n\n"
            f"{tests_section}\n\n"
            "The test files above were written from a spec before the code "
            "existed. Now the real code is available. Rewrite ONLY the parts "
            "of each test file that need to change so the tests correctly "
            "import from and call the actual source modules:\n\n"
            "1. Fix all `import` / `from ... import` statements to use the "
            "real module names (filename without .py extension). For example "
            "if a source file is `stats.py`, use `from stats import ...`.\n"
            "2. Fix any function, class, or constant names that differ.\n"
            "3. Do NOT alter test logic, expected values, or assertions.\n"
            "4. Do NOT remove or add tests.\n\n"
            "Output every adapted test file in a separate fenced code block "
            "with a `# tests/<filename>` comment on the very first line."
        )

        response = agent.call(prompt, self.config.test_designer_max_tokens)
        adapted = self._parse_test_response(response)

        if not adapted:
            return test_files

        for fname, content in test_files.items():
            if fname not in adapted:
                adapted[fname] = content

        return adapted

    def _analyze_requirements(self, requirements: str) -> dict:
        """Ask the LLM what kind of product this is and what users care about.

        Returns a dict with keys like 'product_type', 'user_concerns', and
        'testing_needs' (list of short descriptions).
        """
        agent = BaseAgent(
            "You analyze software requirements and identify what matters to "
            "end-users. Respond ONLY with JSON inside a code block.",
            self.config,
        )
        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            "Analyze these requirements. What kind of product is this? "
            "What would a real user care about when using it? "
            "What kinds of testing are needed beyond unit tests?\n\n"
            "Respond with JSON in a code block:\n"
            "```json\n"
            "{\n"
            '  "product_type": "web_app | library | cli | api_server | other",\n'
            '  "user_concerns": ["list of things a user cares about"],\n'
            '  "testing_needs": [\n'
            '    {"category": "unit | browser | accessibility | api | performance", '
            '"description": "what to test"}\n'
            "  ]\n"
            "}\n"
            "```"
        )
        response = agent.call(prompt, 4096)
        result = self._parse_json_response(response)
        if result is None:
            return {
                "product_type": "other",
                "user_concerns": [],
                "testing_needs": [{"category": "unit", "description": "unit tests"}],
            }
        return result

    def _select_tools(self, analysis: dict) -> list[MCPServer]:
        """Ask the LLM which MCP servers to install based on the analysis.

        The LLM gets a short cheat-sheet of well-known MCP servers in the
        prompt so it can pick from those first, falling back to suggesting
        others when needed.
        """
        testing_needs = analysis.get("testing_needs", [])
        needs_beyond_unit = [
            n for n in testing_needs if n.get("category") != "unit"
        ]
        if not needs_beyond_unit:
            return []

        agent = BaseAgent(
            "You pick MCP servers for testing. "
            "Respond ONLY with a JSON array inside a code block.",
            self.config,
        )
        prompt = (
            f"## Testing needs\n\n{json.dumps(needs_beyond_unit, indent=2)}\n\n"
            "## Well-known MCP servers (prefer these)\n\n"
            "1. **playwright** - Browser automation, E2E testing, UI verification\n"
            '   command: "npx", args: ["@playwright/mcp@latest"]\n'
            "   install_cmd: null (npx downloads on the fly)\n\n"
            "2. **filesystem** - Read/write/search files, verify output files\n"
            '   command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/jelly_test"]\n'
            "   install_cmd: null\n\n"
            "You may also suggest other MCP servers you know about.\n"
            "If none of the testing needs require an MCP server, return [].\n\n"
            "Respond with a JSON array in a code block:\n"
            "```json\n"
            "[\n"
            "  {\n"
            '    "name": "server_name",\n'
            '    "command": "npx",\n'
            '    "args": ["package@version"],\n'
            '    "install_cmd": "npm install -g package" or null\n'
            "  }\n"
            "]\n"
            "```"
        )
        response = agent.call(prompt, 4096)
        raw = self._parse_json_response(response)
        if not isinstance(raw, list):
            return []

        servers = []
        for entry in raw:
            if not isinstance(entry, dict) or "name" not in entry:
                continue
            servers.append(MCPServer(
                name=entry["name"],
                command=entry.get("command", "npx"),
                args=entry.get("args", []),
                install_cmd=entry.get("install_cmd"),
            ))
        return servers

    def _install_tools(self, servers: list[MCPServer]) -> list[MCPServer]:
        """Install each MCP server. Returns only the ones that succeeded."""
        installed = []
        for server in servers:
            if install_server(server):
                installed.append(server)
        return installed

    def _generate_test_plan(
        self,
        requirements: str,
        function_signatures: list[str],
        servers: list[MCPServer],
    ) -> tuple[dict[str, str], MCPTestPlan]:
        """Generate unit tests (pytest) and an MCP test plan.

        Returns (unit_test_files, mcp_test_plan).
        """
        unit_tests = self.generate_tests(requirements, function_signatures)

        if not servers:
            return unit_tests, MCPTestPlan()

        server_names = ", ".join(s.name for s in servers)
        agent = BaseAgent(
            "You create MCP test plans. "
            "Respond ONLY with a JSON array inside a code block.",
            self.config,
        )
        prompt = (
            f"## Requirements\n\n{requirements}\n\n"
            f"## Available MCP servers: {server_names}\n\n"
            "Create test steps that verify the things a real user would care "
            "about. Each step calls one tool on one MCP server and describes "
            "the expected outcome. Keep it to 5-10 steps max.\n\n"
            "Respond with a JSON array in a code block:\n"
            "```json\n"
            "[\n"
            "  {\n"
            '    "description": "what this step checks",\n'
            '    "server": "server_name",\n'
            '    "tool": "tool_name",\n'
            '    "arguments": {},\n'
            '    "expected": "what the result should contain"\n'
            "  }\n"
            "]\n"
            "```"
        )
        response = agent.call(prompt, self.config.test_designer_max_tokens)
        raw = self._parse_json_response(response)

        steps: list[MCPTestStep] = []
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                steps.append(MCPTestStep(
                    description=entry.get("description", ""),
                    server=entry.get("server", ""),
                    tool=entry.get("tool", ""),
                    arguments=entry.get("arguments", {}),
                    expected=entry.get("expected", ""),
                ))

        plan = MCPTestPlan(servers=servers, steps=steps)
        return unit_tests, plan

    @staticmethod
    def _parse_json_response(response: str) -> Any:
        """Try to pull a JSON object or array out of an LLM response.

        Handles truncated JSON arrays by trimming to the last complete element.
        """
        candidates = list(BaseAgent.extract_code_blocks(response)) + [response.strip()]
        for text in candidates:
            text = text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            # Truncated array: find last "},", slice there, close the array
            if text.startswith("["):
                last_obj_end = text.rfind("},")
                if last_obj_end != -1:
                    try:
                        return json.loads(text[: last_obj_end + 1] + "]")
                    except json.JSONDecodeError:
                        pass
        return None
