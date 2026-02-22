"""
Text processing utilities: tokenization, normalization, search, and highlighting.
"""

import unicodedata
import re
from typing import Optional


# ---------------------------------------------------------------------------
# FR-1: Tokenize with Quoted Strings
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """
    Tokenize string respecting quoted substrings.

    Splits on whitespace; preserves quoted substrings as single tokens (quotes
    stripped). Escaped quotes inside a quoted region become literal quote
    characters. Adjacent quoted/unquoted segments without whitespace become
    separate tokens. Unmatched quotes are treated as literal characters.
    """
    tokens: list[str] = []
    current: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch.isspace():
            # Flush accumulated token
            if current:
                tokens.append("".join(current))
                current = []
            i += 1

        elif ch in ('"', "'"):
            # Scan ahead for a matching (unescaped) closing quote
            quote_char = ch
            j = i + 1
            found_close = False
            while j < n:
                if text[j] == "\\" and j + 1 < n and text[j + 1] == quote_char:
                    j += 2  # skip escaped quote
                elif text[j] == quote_char:
                    found_close = True
                    break
                else:
                    j += 1

            if found_close:
                # Emit any in-progress token before the quoted section
                if current:
                    tokens.append("".join(current))
                    current = []
                # Collect quoted content, honouring escape sequences
                k = i + 1
                quoted: list[str] = []
                while k < j:
                    if text[k] == "\\" and k + 1 < j and text[k + 1] == quote_char:
                        quoted.append(quote_char)
                        k += 2
                    else:
                        quoted.append(text[k])
                        k += 1
                tokens.append("".join(quoted))
                i = j + 1  # skip past closing quote
            else:
                # Unmatched quote — treat as a literal character
                current.append(ch)
                i += 1

        else:
            current.append(ch)
            i += 1

    if current:
        tokens.append("".join(current))

    return tokens


# ---------------------------------------------------------------------------
# FR-2: Normalize Text
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """
    Normalize text for accent- and case-insensitive comparison.

    Steps:
    1. Unicode NFC normalization.
    2. Case-fold (handles ß → ss, etc.).
    3. Strip combining characters (Unicode category Mn).
    4. Collapse runs of whitespace (including Unicode whitespace) to a
       single ASCII space.
    5. Strip leading/trailing whitespace.

    Raises TypeError for non-string input.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__!r}")
    if not text:
        return ""

    # Step 1: NFC
    result = unicodedata.normalize("NFC", text)
    # Step 2: case-fold
    result = result.casefold()
    # Step 3: strip combining characters via NFD decomposition
    result = unicodedata.normalize("NFD", result)
    result = "".join(ch for ch in result if unicodedata.category(ch) != "Mn")
    # Step 4 & 5: collapse whitespace and strip
    result = re.sub(r"\s+", " ", result, flags=re.UNICODE).strip()
    return result


# ---------------------------------------------------------------------------
# Internal: position-aware normalization map
# ---------------------------------------------------------------------------

def _normalize_char(ch: str) -> str:
    """
    Return the normalized form of a single character (may be empty or
    multi-character, e.g. ß → 'ss').
    """
    nfc = unicodedata.normalize("NFC", ch)
    casefolded = nfc.casefold()
    nfd = unicodedata.normalize("NFD", casefolded)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _build_norm_map(text: str):
    """
    Build a normalized form of *text* and a parallel array that maps each
    position in the normalized string back to an index in the original string.

    Returns
    -------
    norm_text : str
        The normalized string (whitespace collapsed, stripped).
    orig_positions : list[int]
        ``orig_positions[i]`` is the index in *text* that contributed the
        character ``norm_text[i]``.
    """
    # Phase 1: expand each original character to its normalized sub-chars,
    # keeping track of the originating index.
    expanded: list[tuple[int, str]] = []  # (orig_idx, norm_char)
    for orig_idx, ch in enumerate(text):
        norm_chars = _normalize_char(ch)
        for c in norm_chars:
            expanded.append((orig_idx, c))

    # Phase 2: collapse whitespace runs (isspace() covers Unicode whitespace)
    collapsed: list[tuple[int, str]] = []
    in_ws = False
    for orig_idx, c in expanded:
        if c.isspace():
            if not in_ws:
                collapsed.append((orig_idx, " "))
                in_ws = True
            # else skip additional whitespace characters
        else:
            collapsed.append((orig_idx, c))
            in_ws = False

    # Phase 3: strip leading/trailing spaces
    lo = 0
    hi = len(collapsed)
    while lo < hi and collapsed[lo][1] == " ":
        lo += 1
    while hi > lo and collapsed[hi - 1][1] == " ":
        hi -= 1
    collapsed = collapsed[lo:hi]

    norm_text = "".join(c for _, c in collapsed)
    orig_positions = [idx for idx, _ in collapsed]
    return norm_text, orig_positions


# ---------------------------------------------------------------------------
# FR-3: Find All Matches with Context
# ---------------------------------------------------------------------------

def find_matches(
    text: str,
    query: str,
    context_chars: int = 20,
) -> list[dict]:
    """
    Find all occurrences of *query* within *text* using normalized matching.

    Positions in the returned dicts refer to the **original** text.
    Overlapping matches are all returned.

    Parameters
    ----------
    text : str
        The text to search in.
    query : str
        The search query.  Empty query returns ``[]``.
    context_chars : int
        Number of characters of surrounding context to include.
        Must be ≥ 0; raises ValueError otherwise.

    Returns
    -------
    list[dict] with keys: ``start``, ``end``, ``match``, ``context``.
    """
    if context_chars < 0:
        raise ValueError("context_chars must be non-negative")
    if not query:
        return []

    norm_query = normalize(query)
    if not norm_query:
        return []

    norm_text, orig_positions = _build_norm_map(text)
    q_len = len(norm_query)
    n_len = len(norm_text)

    results: list[dict] = []

    # Search for all (possibly overlapping) occurrences in the normalized text
    start_search = 0
    while start_search <= n_len - q_len:
        idx = norm_text.find(norm_query, start_search)
        if idx == -1:
            break

        norm_start = idx
        norm_end = idx + q_len  # exclusive

        # Map back to original text positions
        orig_start = orig_positions[norm_start]
        # orig_end is the index *after* the last original character involved
        orig_end = orig_positions[norm_end - 1] + 1

        ctx_start = max(0, orig_start - context_chars)
        # orig_end is already exclusive, so add context_chars directly
        ctx_end = min(len(text), orig_end + context_chars)

        results.append(
            {
                "start": orig_start,
                "end": orig_end,
                "match": text[orig_start:orig_end],
                "context": text[ctx_start:ctx_end],
            }
        )

        start_search = idx + 1  # allow overlapping matches

    return results


# ---------------------------------------------------------------------------
# FR-4: Highlight Matches
# ---------------------------------------------------------------------------

def highlight(
    text: str,
    query: str,
    before: str = "**",
    after: str = "**",
) -> str:
    """
    Return *text* with every match of *query* wrapped in *before*/*after*.

    Uses normalized matching (same as :func:`find_matches`).  Overlapping
    matches are merged into a single highlighted region.  Adjacent but
    non-overlapping matches are highlighted separately.  Empty *query*
    returns *text* unchanged.

    Parameters
    ----------
    text : str
        Source text.
    query : str
        Search query.
    before : str
        Opening delimiter (default ``"**"``).
    after : str
        Closing delimiter (default ``"**"``).
    """
    if not query:
        return text

    norm_query = normalize(query)
    if not norm_query:
        return text

    norm_text, orig_positions = _build_norm_map(text)
    q_len = len(norm_query)
    n_len = len(norm_text)

    # Collect all match spans in original-text coordinates
    raw_spans: list[tuple[int, int]] = []
    start_search = 0
    while start_search <= n_len - q_len:
        idx = norm_text.find(norm_query, start_search)
        if idx == -1:
            break
        orig_start = orig_positions[idx]
        orig_end = orig_positions[idx + q_len - 1] + 1
        raw_spans.append((orig_start, orig_end))
        start_search = idx + 1

    if not raw_spans:
        return text

    # Merge overlapping spans only (not merely adjacent/touching)
    merged: list[tuple[int, int]] = []
    cur_start, cur_end = raw_spans[0]
    for s, e in raw_spans[1:]:
        if s < cur_end:  # strictly overlapping (not merely adjacent)
            cur_end = max(cur_end, e)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))

    # Reconstruct the string with delimiters inserted
    parts: list[str] = []
    prev = 0
    for s, e in merged:
        parts.append(text[prev:s])
        parts.append(before)
        parts.append(text[s:e])
        parts.append(after)
        prev = e
    parts.append(text[prev:])

    return "".join(parts)
