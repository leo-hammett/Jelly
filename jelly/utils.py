import re
from pathlib import Path


def read_file(path: str) -> str:
    """Read and return the contents of a file.

    Args:
        path: Path to the file to read.

    Returns:
        The file's text content.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    return Path(path).read_text()


def write_files(directory: str, files: dict[str, str]) -> None:
    """Write a dict of files to a directory, creating parent dirs as needed.

    Args:
        directory: Base directory to write into.
        files: Mapping of {filename: content} to write.
    """
    base = Path(directory)
    for filename, content in files.items():
        dest = base / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)


_DECLARATION_RE = re.compile(
    r"^\s*(?:"
    r"(?:export\s+)?(?:async\s+)?function\s+\w+|"  # JS/TS
    r"(?:async\s+)?def\s+\w+|"                      # Python
    r"(?:pub\s+)?(?:async\s+)?fn\s+\w+|"            # Rust
    r"func\s+\w+|"                                   # Go
    r"(?:public|private|protected|static)\s+.*\w+\s*\(" # Java/C#/C++
    r")"
)


def extract_signatures(requirements: str) -> list[str]:
    """Extract function/method declarations from code blocks in requirements.

    Looks for lines inside fenced code blocks that match common
    function or method declaration patterns across languages.

    Args:
        requirements: The full requirements markdown text.

    Returns:
        List of declaration strings found in code fences.
    """
    signatures: list[str] = []
    in_fence = False
    for line in requirements.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and _DECLARATION_RE.match(stripped):
            signatures.append(stripped)
    return signatures
