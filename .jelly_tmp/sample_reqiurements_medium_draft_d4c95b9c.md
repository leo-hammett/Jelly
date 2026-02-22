# Project: Text Processing Utilities

## Overview
Python utility functions for text tokenization, normalization, and basic search. `tokenize` splits strings into tokens while respecting quoted substrings and escape sequences. `normalize` reduces text to a canonical lowercase, accent-stripped, whitespace-collapsed form. `find_matches` locates all occurrences of a normalized query within a text and returns results with original-text positions and surrounding context. `highlight` wraps all matches in configurable delimiters, merging overlapping match regions before insertion.

---

## Functional Requirements

### FR-1: Tokenize with Quoted Strings

Split a string into tokens by whitespace, but preserve quoted substrings (single or double quotes) as single tokens. Quotes themselves are stripped from returned tokens.

- **Input:** `text: str`
- **Output:** `list[str]`

**Tokenization rules (applied left to right):**

1. Outside a quoted region, whitespace (any sequence of `' '`, `'\t'`, `'\n'`, `'\r'`) delimits tokens.
2. When a `"` or `'` is encountered outside a quoted region, it opens a quoted region using that character as the active quote.
3. Inside a quoted region, all characters are accumulated literally **except**:
   - `\` immediately followed by the active quote character: the backslash is consumed and the quote character is added literally to the token (does **not** close the region).
   - The active quote character (unescaped): closes the region. The closing quote is stripped.
4. A `\` followed by **anything other than the active quote character** (including `\` itself, `n`, `t`, etc.) is treated as a **literal backslash** and is **preserved** in the output. Backslashes have no special meaning outside quoted regions.
5. If a quote character is encountered that has no matching closing quote before end-of-string, it is treated as a **literal character** (no region is opened; that character and all subsequent characters are split normally by whitespace).
6. A closing quote immediately adjacent to the next non-whitespace characters (no space between) produces **separate** tokens — one for the quoted region and one for the adjacent characters.
7. An empty quoted region (`""` or `''`) produces one token containing the empty string `""` → `['']`.
8. Whitespace-only or empty input returns `[]`.

**Constraints:**
- Non-string input raises `TypeError`.
- The outer quote type has no special meaning inside the other quote type: `"it's fine"` preserves the `'` literally.

**Examples:**
```python
tokenize('hello world')                         # ['hello', 'world']
tokenize('say "hello world" please')            # ['say', 'hello world', 'please']
tokenize("say 'hello world' please")            # ['say', 'hello world', 'please']
tokenize('say "hello world please')             # ['say', '"hello', 'world', 'please']
                                                # (unmatched " → literal character)
tokenize('say "he said \\"hi\\"" ok')           # ['say', 'he said "hi"', 'ok']
                                                # (\" inside double-quoted region → literal ")
tokenize('"hello"world foo')                    # ['hello', 'world', 'foo']
                                                # (adjacent token after closing quote)
tokenize("he said \"it's fine\" ok")            # ['he', 'said', "it's fine", 'ok']
                                                # (inner ' preserved literally)
tokenize('""')                                  # ['']
                                                # (empty quoted region → one empty-string token)
tokenize("say 'it\\'s fine' ok")               # ['say', "it's fine", 'ok']
                                                # (\' inside single-quoted region → literal ')
tokenize('"hello\\world"')                      # ['hello\\world']
                                                # (\ before w has no special meaning → preserved)
tokenize('"line1\\nline2"')                     # ['line1\\nline2']
                                                # (\n is NOT an escape sequence → literal \ + n)
tokenize('')                                    # []
tokenize('   ')                                 # []
tokenize('\t\n')                                # []
```

---

### FR-2: Normalize Text

Normalize a string for case-insensitive, accent-insensitive comparison.

- **Input:** `text: str`
- **Output:** `str`

**Steps applied in order:**

| Step | Operation | Detail |
|------|-----------|--------|
| 1 | Unicode NFC normalization | `unicodedata.normalize('NFC', text)` |
| 2 | Case folding | `str.casefold()` — handles non-ASCII folding (e.g. `ß` → `ss`, `ﬁ` → `fi`) |
| 3 | Strip combining characters | Remove all code points with Unicode category `Mn` (Non-spacing marks), eliminating accents and diacritics |
| 4 | Collapse whitespace | Replace any run of one or more Unicode whitespace characters (including `U+00A0` NO-BREAK SPACE, `U+2003` EM SPACE, `U+000A`, `U+0009`, etc.) with a single ASCII space `' '` |
| 5 | Strip | Remove leading and trailing ASCII spaces |

**Constraints:**
- Empty string returns `""` (all steps are no-ops or strip nothing).
- Non-string input raises `TypeError`.
- Step 3 must be applied **after** step 2, because case folding can introduce precomposed characters that decompose to base + combining sequences.

**Examples:**
```python
normalize('Héllo  Wörld')           # 'hello world'
normalize('STRASSE ß')              # 'strasse ss'
normalize('  café\u00A0\u00A0 ')   # 'cafe'
normalize('')                       # ''
normalize('naïve résumé')           # 'naive resume'
normalize('ﬁle')                    # 'file'     (ligature ﬁ → fi)
normalize('\t hello \n')            # 'hello'
normalize('\u2003spaced\u00A0out')  # 'spaced out'
```

---

### FR-3: Find All Matches with Context

Search for all non-overlapping-skipped occurrences of a query within a text. Matching is performed on **normalized** forms (via FR-2), but all returned positions and substrings reference the **original** text.

- **Input:**
  - `text: str`
  - `query: str`
  - `context_chars: int = 20`
- **Output:** `list[dict]`, ordered by ascending `start`, where each dict contains:

| Key | Type | Description |
|-----|------|-------------|
| `"start"` | `int` | Start index of the match in the **original** `text` |
| `"end"` | `int` | End index (exclusive) of the match in the **original** `text` |
| `"match"` | `str` | `text[start:end]` — the matched substring from the original text |
| `"context"` | `str` | `text[max(0, start - context_chars) : min(len(text), end + context_chars)]` |

**Position mapping under normalization length changes:**

Normalization can change string length (e.g. `ß` → `ss` adds one character; stripping a combining character removes one). The function must maintain a character-level mapping `norm_pos → orig_pos` so that a match at `[norm_start, norm_end)` in the normalized text maps to the correct `[orig_start, orig_end)` in the original text.

Specifically, build a list `orig_index` of length `len(norm_text) + 1` where:
- `orig_index[i]` is the original-text index corresponding to the start of normalized character position `i`.
- `orig_index[len(norm_text)]` equals `len(text)` (sentinel for end-of-string).

Then: `start = orig_index[norm_start]`, `end = orig_index[norm_end]`.

**Constraints:**
- Empty `query` (or `query` that normalizes to `""`) returns `[]`.
- Overlapping matches are **all** returned: searching `"aa"` in `"aaa"` returns matches at `[0,2)` and `[1,3)`.
- `context_chars = 0` is valid; context equals `text[start:end]`.
- `context_chars < 0` raises `ValueError`.
- Non-string `text` or `query` raises `TypeError`.
- If the normalized query is longer than the normalized text, returns `[]`.

**Examples:**
```python
find_matches('Hello World Hello', 'hello', context_chars=5)
# [
#   {"start": 0,  "end": 5,  "match": "Hello", "context": "Hello Worl"},
#   {"start": 12, "end": 17, "match": "Hello", "context": "d Hello"}
# ]

find_matches('The café is nice', 'cafe', context_chars=5)
# [{"start": 4, "end": 8, "match": "café", "context": "The café is n"}]
# (café is 4 chars in original: c-a-f-é at indices 4,5,6,7)

find_matches('aaa', 'aa', context_chars=0)
# [
#   {"start": 0, "end": 2, "match": "aa", "context": "aa"},
#   {"start": 1, "end": 3, "match": "aa", "context": "aa"}
# ]

find_matches('straße', 'strasse', context_chars=0)
# [{"start": 0, "end": 6, "match": "straße", "context": "straße"}]
# Explanation:
#   original  'straße'  → indices 0–5 (6 chars: s,t,r,a,ß,e)
#   normalized 'strasse' → 7 chars  (ß expands to ss)
#   norm_index mapping: norm[0..3]→orig[0..3], norm[4]→orig[4],
#                       norm[5]→orig[4], norm[6]→orig[5], norm[7]→orig[6]
#   query 'strasse' normalized → 'strasse', matches norm[0:7]
#   orig_start = orig_index[0] = 0, orig_end = orig_index[7] = 6

find_matches('hello', '', context_chars=5)
# []

find_matches('hello', 'hello there', context_chars=5)
# []  (normalized query longer than normalized text)

find_matches('Hello World', 'hello', context_chars=0)
# [{"start": 0, "end": 5, "match": "Hello", "context": "Hello"}]
```

---

### FR-4: Highlight Matches

Return the original text with all query matches wrapped in configurable delimiter strings. Overlapping matches are merged into a single highlighted region before inserting delimiters.

- **Input:**
  - `text: str`
  - `query: str`
  - `before: str = "**"`
  - `after: str = "**"`
- **Output:** `str`

**Algorithm:**

1. Find all match spans `(start, end)` using normalized matching (same logic as FR-3).
2. Merge overlapping or adjacent spans into non-overlapping intervals using a greedy sweep:
   - Sort spans by `start`.
   - Merge span B into the current interval if `B.start <= current.end` (overlapping or adjacent), extending `current.end = max(current.end, B.end)`.
3. Reconstruct the output string by iterating through merged intervals, inserting `before` before `text[start:end]` and `after` after it, and concatenating the non-matched segments unchanged.

**Constraints:**
- Uses the same normalized matching as FR-3 (including length-change position mapping).
- Empty `query` (or query normalizing to `""`) returns `text` unchanged.
- `before` and `after` may be empty strings.
- Delimiters are inserted into the **original** text; no normalization is applied to the output.
- Non-string inputs raise `TypeError`.

**Examples:**
```python
highlight('Hello World Hello', 'hello')
# '**Hello** World **Hello**'

highlight('aaaa', 'aa')
# '**aaaa**'
# Matches: (0,2), (1,3), (2,4) → merged to (0,4)

highlight('The café is nice', 'cafe')
# 'The **café** is nice'

highlight('hello world', 'hello', before='[', after=']')
# '[hello] world'

highlight('hello', '', before='[', after=']')
# 'hello'

highlight('straße and STRASSE', 'strasse')
# '**straße** and **STRASSE**'

highlight('abcabc', 'abc')
# '**abc****abc**'   — two non-overlapping matches, no merge needed
# (if before='<b>' after='</b>': '<b>abc</b><b>abc</b>')

highlight('aabbaab', 'aab')
# '**aab**b**aab**'  — matches at (0,3) and (4,7), non-overlapping
```

---

## API Specification

```python
def tokenize(text: str) -> list[str]:
    """
    Split *text* into tokens by whitespace, preserving quoted substrings as
    single tokens with quotes stripped.

    Escape rule: inside a quoted region, a backslash immediately before the
    active quote character is treated as an escape — the backslash is consumed
    and the quote is added literally without closing the region. A backslash
    before any other character has no special meaning and is preserved as-is.

    An unmatched opening quote (no closing quote found before end-of-string)
    is treated as a literal character; no quoted region is opened.

    An empty quoted region (``""`` or ``''``) produces one token: ``''``.

    Parameters
    ----------
    text : str
        The input string to tokenize.

    Returns
    -------
    list[str]
        Ordered list of token strings. Empty list if *text* is empty or
        whitespace-only.

    Raises
    ------
    TypeError
        If *text* is not a ``str``.

    Examples
    --------
    >>> tokenize('hello world')
    ['hello', 'world']
    >>> tokenize('say "hello world" please')
    ['say', 'hello world', 'please']
    >>> tokenize('say "he said \\\\"hi\\\\"" ok')
    ['say', 'he said "hi"', 'ok']
    >>> tokenize('""')
    ['']
    >>> tokenize('"hello\\\\nworld"')
    ['hello\\\\nworld']
    """
    ...


def normalize(text: str) -> str:
    """
    Normalize *text* for case- and accent-insensitive comparison.

    Steps applied in order:
    1. Unicode NFC normalization.
    2. Case folding (``str.casefold()``), handling non-ASCII (e.g. ß → ss).
    3. Strip all Unicode combining characters (category ``Mn``).
    4. Collapse runs of Unicode whitespace into a single ASCII space.
    5. Strip leading and trailing whitespace.

    Parameters
    ----------
    text : str
        The input string to normalize.

    Returns
    -------
    str
        Normalized string. Empty string if *text* is empty or whitespace-only.

    Raises
    ------
    TypeError
        If *text* is not a ``str``.

    Examples
    --------
    >>> normalize('Héllo  Wörld')
    'hello world'
    >>> normalize('STRASSE ß')
    'strasse ss'
    >>> normalize('  café\\u00A0\\u00A0 ')
    'cafe'
    """
    ...


def find_matches(
    text: str,
    query: str,
    context_chars: int = 20,
) -> list[dict[str, int | str]]:
    """
    Find all occurrences of *query* in *text* using normalized matching,
    returning results with original-text positions and surrounding context.

    Matching is performed on ``normalize(text)`` and ``normalize(query)``.
    A character-level index mapping is constructed so that match positions in
    the normalized string are correctly translated back to positions in the
    original *text*, even when normalization changes string length (e.g. ß → ss).

    Overlapping matches are all returned (e.g. 'aa' in 'aaa' → 2 matches).

    Each result dict contains:
        "start"   : int — match start index in original *text*
        "end"     : int — match end index (exclusive) in original *text*
        "match"   : str — ``text[start:end]``
        "context" : str — ``text[max(0, start-context_chars):
                                 min(len(text), end+context_chars)]``

    Parameters
    ----------
    text : str
        The text to search within.
    query : str
        The query to search for (matched after normalization).
    context_chars : int, optional
        Number of characters of surrounding context to include. Default 20.

    Returns
    -------
    list[dict[str, int | str]]
        Ordered list of match dicts. Empty list if *query* is empty or no
        matches are found.

    Raises
    ------
    TypeError
        If *text* or *query* is not a ``str``.
    ValueError
        If *context_chars* is negative.

    Examples
    --------
    >>> find_matches('The café is nice', 'cafe', context_chars=5)
    [{'start': 4, 'end': 8, 'match': 'café', 'context': 'The café is n'}]
    >>> find_matches('straße', 'strasse', context_chars=0)
    [{'start': 0, 'end': 6, 'match': 'straße', 'context': 'straße'}]
    """
    ...


def highlight(
    text: str,
    query: str,
    before: str = "**",
    after: str = "**",
) -> str:
    """
    Return *text* with all occurrences of *query* wrapped in *before*/*after*
    delimiters. Overlapping or adjacent matches are merged into a single
    highlighted region before delimiter insertion.

    Matching uses the same normalized comparison and position-mapping logic as
    ``find_matches``. Delimiters are inserted at original-text positions;
    the matched substrings in the output are taken verbatim from *text*.

    Parameters
    ----------
    text : str
        The text to highlight within.
    query : str
        The query to search for (matched after normalization).
    before : str, optional
        String inserted immediately before each (merged) match. Default ``"**"``.
    after : str, optional
        String inserted immediately after each (merged) match. Default ``"**"``.

    Returns
    -------
    str
        *text* with all matches highlighted. Returns *text* unchanged if
        *query* is empty or produces no matches.

    Raises
    ------
    TypeError
        If any of *text*, *query*, *before*, or *after* is not a ``str``.

    Examples
    --------
    >>> highlight('Hello World Hello', 'hello')
    '**Hello** World **Hello**'
    >>> highlight('aaaa', 'aa')
    '**aaaa**'
    >>> highlight('The café is nice', 'cafe')
    'The **café** is nice'
    >>> highlight('hello', '', before='[', after=']')
    'hello'
    """
    ...
```

---

## Edge Cases

### Tokenizer (FR-1)
- Empty string `''` → `[]`
- Whitespace-only `'   '`, `'\t\n'` → `[]`
- Unmatched opening quote: `'"hello world'` → `['"hello', 'world']` (literal `"`)
- Escaped active quote: `"say \"hi\""` → `['say', '"hi"']`; backslash consumed, quote preserved
- Non-active-quote backslash: `"hello\\nworld"` → `['hello\\nworld']`; backslash preserved
- Double backslash: `"hello\\\\world"` → `['hello\\\\world']`; both backslashes preserved (no `\\` → `\` collapsing)
- Empty quoted region: `'""'` → `['']`; `"''"` → `['']`
- Adjacent token after closing quote: `'"foo"bar'` → `['foo', 'bar']`
- Nested (non-active) quotes: `"it's here"` → `["it's here"]`; inner `'` is literal
- Quote at end of string with content: `'hello"world'` → `['hello"world']` (unmatched, literal)
- Only an unmatched quote: `'"'` → `['"']`

### Normalizer (FR-2)
- Empty string → `""`
- Non-string input (`None`, `int`, `list`) → `TypeError`
- `ß` → `ss` (casefold length increase)
- `ﬁ` → `fi` (ligature expansion)
- Combining characters: `e\u0301` (e + combining acute) → `e`
- Multiple consecutive Unicode whitespace types → single ASCII space
- Leading/trailing whitespace of any Unicode variety → stripped
- String that is all combining characters after base removal → `""`

### Matching and Position Mapping (FR-3 and FR-4)
- `context_chars = 0`: context equals the match substring only
- `context_chars < 0`: `ValueError`
- Match at start of text: context has no left padding
- Match at end of text: context has no right padding
- Match spanning entire text: `start=0`, `end=len(text)`, context equals full text
- Normalization shrinks text (combining character stripped): e.g. `'café'` (5 bytes NFC, 4 chars) matched by `'cafe'`
- Normalization expands text (`ß` → `ss`): `find_matches('straße', 'strasse')` must correctly return `end=6` (original length), not `7`
- Multiple length-changing characters in one string: e.g. `'straßenmaß'` queried with `'strassenmas'`; every position must map correctly
- Empty query → `[]` (FR-3) / unchanged text (FR-4)
- Query normalizes to empty string (e.g. query is combining characters only) → same as empty query
- Query longer than text after normalization → `[]`
- Overlapping matches: `find_matches('aaa', 'aa')` → 2 results; `highlight('aaaa', 'aa')` → merged to one region
- Adjacent non-overlapping matches: not merged in FR-4 (e.g. `highlight('abcabc', 'abc')` → two separate highlighted regions)
- `before` or `after` is `""`: delimiters are empty strings; output equals original text with empty strings inserted (effectively unchanged)
- Non-string `before`/`after` in FR-4 → `TypeError`
- Very large text (100,000+ characters) with many matches: must complete in sub-second time for typical hardware (no O(n²) scan)