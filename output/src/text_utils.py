"""
Text processing utilities: tokenization, normalization, search, and highlighting.
"""

import unicodedata
import re


# ---------------------------------------------------------------------------
# FR-1: Tokenize with Quoted Strings
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """
    Tokenize string respecting quoted substrings.

    Quoted regions (single or double quotes) are returned as single tokens with
    the surrounding quotes stripped.  Escaped quotes (backslash + quote char)
    inside a quoted region are treated as literal quote characters.  Unmatched
    opening quotes are treated as ordinary characters.  Adjacent tokens with no
    whitespace between the closing quote and the next non-whitespace run are
    returned as separate tokens.
    """
    tokens: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # --- Skip leading whitespace ---
        if ch.isspace():
            i += 1
            continue

        # --- Quoted region ---
        if ch in ('"', "'"):
            quote_char = ch
            # Look ahead to find a matching (non-escaped) closing quote.
            j = i + 1
            content: list[str] = []
            found_close = False
            while j < n:
                if text[j] == '\\' and j + 1 < n and text[j + 1] == quote_char:
                    # Escaped quote inside the region → literal quote, skip backslash.
                    content.append(quote_char)
                    j += 2
                elif text[j] == quote_char:
                    # Closing quote found.
                    found_close = True
                    j += 1
                    break
                else:
                    content.append(text[j])
                    j += 1

            if found_close:
                tokens.append(''.join(content))
                i = j  # Continue right after the closing quote (may be mid-word).
            else:
                # Unmatched quote → treat as literal character; collect until whitespace.
                word_chars = [quote_char]
                i += 1
                while i < n and not text[i].isspace():
                    word_chars.append(text[i])
                    i += 1
                tokens.append(''.join(word_chars))

        # --- Normal (unquoted) token ---
        else:
            word_chars = []
            while i < n and not text[i].isspace() and text[i] not in ('"', "'"):
                word_chars.append(text[i])
                i += 1
            if word_chars:
                tokens.append(''.join(word_chars))
            # Do not advance i here – let the next iteration handle quotes/whitespace.

    return tokens


# ---------------------------------------------------------------------------
# FR-2: Normalize Text
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """
    Normalize text for accent- and case-insensitive comparison.

    Steps (in order):
      1. Unicode NFC normalization.
      2. Case folding (handles non-ASCII, e.g. ß → ss).
      3. Strip combining characters (Unicode category Mn).
      4. Collapse runs of whitespace (including Unicode whitespace) to a single space.
      5. Strip leading/trailing whitespace.

    Raises TypeError for non-string input.
    """
    if not isinstance(text, str):
        raise TypeError(f"normalize() expects str, got {type(text).__name__!r}")
    if not text:
        return ""

    # Step 1: NFC
    result = unicodedata.normalize('NFC', text)
    # Step 2: Case fold
    result = result.casefold()
    # Step 3: Decompose and strip combining characters
    result = unicodedata.normalize('NFD', result)
    result = ''.join(ch for ch in result if unicodedata.category(ch) != 'Mn')
    # Step 4: Collapse all whitespace (including Unicode whitespace) → single space
    result = re.sub(r'\s+', ' ', result)
    # Step 5: Strip
    result = result.strip()
    return result


# ---------------------------------------------------------------------------
# Helpers for position-aware normalization (FR-3 / FR-4)
# ---------------------------------------------------------------------------

def _build_norm_map(text: str) -> tuple[str, list[int]]:
    """
    Normalize *text* character by character, returning:
      - ``norm_text``: the normalized string (without whitespace run-collapsing)
      - ``mapping``:  list of length ``len(norm_text)``; ``mapping[k]`` is the
        index in *text* that the k-th normalized character originated from.

    Each whitespace character is individually replaced by a single ASCII space
    (no run collapsing, so original positions remain meaningful).
    Combining characters (Mn) produced during normalization are dropped.
    """
    norm_chars: list[str] = []
    mapping: list[int] = []

    for orig_idx, ch in enumerate(text):
        # Per-character NFC then casefold then decompose + strip Mn
        nfc = unicodedata.normalize('NFC', ch)
        folded = nfc.casefold()
        decomposed = unicodedata.normalize('NFD', folded)
        expanded = ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')

        for c in expanded:
            # Replace any Unicode whitespace with a plain ASCII space
            if re.match(r'\s', c):
                c = ' '
            norm_chars.append(c)
            mapping.append(orig_idx)

    return ''.join(norm_chars), mapping


def _orig_span(
    norm_start: int,
    norm_end: int,
    mapping: list[int],
    orig_len: int,
) -> tuple[int, int]:
    """
    Convert a [norm_start, norm_end) span in normalized text back to a
    [orig_start, orig_end) span in the original text.

    orig_len is used to clamp orig_end so it never exceeds len(original text).
    """
    orig_start = mapping[norm_start]

    if norm_end > norm_start:
        # The last original character covered is mapping[norm_end - 1].
        # orig_end is exclusive, so + 1.
        orig_end = mapping[norm_end - 1] + 1
    else:
        orig_end = orig_start

    # Clamp to valid range (shouldn't normally be needed, but protects against
    # edge cases where normalization expands a character at the very end).
    orig_end = min(orig_end, orig_len)
    orig_start = min(orig_start, orig_len)

    return orig_start, orig_end


# ---------------------------------------------------------------------------
# FR-3: Find All Matches with Context
# ---------------------------------------------------------------------------

def find_matches(text: str, query: str, context_chars: int = 20) -> list[dict]:
    """
    Find all occurrences of *query* in *text* using normalized matching.

    Returns a list of dicts with keys:
      - ``start``  : start index in original text (inclusive)
      - ``end``    : end index in original text (exclusive)
      - ``match``  : matched substring from original text
      - ``context``: surrounding window in original text (±context_chars)

    Overlapping matches are all returned.
    Raises ValueError if context_chars < 0.
    """
    if context_chars < 0:
        raise ValueError("context_chars must be non-negative")
    if not query:
        return []

    norm_text, mapping = _build_norm_map(text)
    norm_query = normalize(query)  # Full normalization (with whitespace collapse) for the query

    if not norm_query:
        return []

    results: list[dict] = []
    q_len = len(norm_query)
    t_len = len(norm_text)
    orig_len = len(text)

    pos = 0
    while pos <= t_len - q_len:
        if norm_text[pos: pos + q_len] == norm_query:
            orig_start, orig_end = _orig_span(pos, pos + q_len, mapping, orig_len)
            ctx_start = max(0, orig_start - context_chars)
            ctx_end = min(orig_len, orig_end + context_chars)
            results.append({
                "start":   orig_start,
                "end":     orig_end,
                "match":   text[orig_start:orig_end],
                "context": text[ctx_start:ctx_end],
            })
        pos += 1

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
    Return *text* with all normalized matches of *query* wrapped in
    *before*/*after* delimiters.

    Overlapping matches are merged into a single highlighted region.
    Adjacent but non-overlapping matches are highlighted separately.
    Empty query returns *text* unchanged.
    """
    if not query:
        return text

    matches = find_matches(text, query, context_chars=0)
    if not matches:
        return text

    # Collect (start, end) spans and merge overlapping ones.
    spans = [(m["start"], m["end"]) for m in matches]
    spans.sort()

    merged: list[tuple[int, int]] = []
    cur_start, cur_end = spans[0]
    for s, e in spans[1:]:
        if s < cur_end:             # strictly overlapping (not merely touching)
            cur_end = max(cur_end, e)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))

    # Reconstruct the string with delimiters inserted.
    parts: list[str] = []
    prev = 0
    for s, e in merged:
        parts.append(text[prev:s])
        parts.append(before)
        parts.append(text[s:e])
        parts.append(after)
        prev = e
    parts.append(text[prev:])
    return ''.join(parts)
