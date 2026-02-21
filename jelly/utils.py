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


def extract_signatures(requirements: str) -> list[str]:
    """Extract function signatures from ```python blocks in requirements.

    Looks for lines starting with 'def ' inside code fences.

    Args:
        requirements: The full requirements markdown text.

    Returns:
        List of signature strings, e.g.
        ['def has_close_elements(numbers: list[float], threshold: float) -> bool:']
    """
    signatures: list[str] = []
    in_fence = False
    for line in requirements.splitlines():
        stripped = line.strip()
        if stripped.startswith("```python"):
            in_fence = True
            continue
        if stripped.startswith("```") and in_fence:
            in_fence = False
            continue
        if in_fence and stripped.startswith("def "):
            signatures.append(stripped)
    return signatures
