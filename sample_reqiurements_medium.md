# Project: Text Processing Utilities

## Overview
Python utility functions for text tokenization, normalization, and basic search.

## Functional Requirements

### FR-1: Tokenize with Quoted Strings
Split a string into tokens by whitespace, but preserve quoted substrings (single or double quotes) as single tokens. Quotes themselves are stripped from the returned tokens.

- Input: `text: str`
- Output: `list[str]`
- Constraints:
  - Empty string returns `[]`.
  - Unmatched quotes treat the quote as a literal character (no special behavior from that quote onward — split normally).
  - Escaped quotes (`\"` or `\'`) inside a quoted region are treated as literal quote characters and do not close the region. The backslash is removed in the output.
  - Adjacent tokens with no whitespace between closing quote and next token are **separate** tokens: `"hello"world` → `["hello", "world"]`.
  - Whitespace-only input returns `[]`.
  - Nested quotes (a quoted region using one quote type containing the other) preserve the inner quotes literally: `"it's fine"` → `it's fine`.

- Examples:
  ```python
  tokenize('hello world')                        # ['hello', 'world']
  tokenize('say "hello world" please')           # ['say', 'hello world', 'please']
  tokenize("say 'hello world' please")           # ['say', 'hello world', 'please']
  tokenize('say "hello world please')            # ['say', '"hello', 'world', 'please']
  tokenize('say "he said \\"hi\\"" ok')          # ['say', 'he said "hi"', 'ok']
  tokenize('"hello"world foo')                   # ['hello', 'world', 'foo']
  tokenize("he said \"it's fine\" ok")           # ['he', "said", "it's fine", 'ok']
  tokenize('')                                   # []
  tokenize('   ')                                # []
  ```

### FR-2: Normalize Text
Normalize a string for case-insensitive, accent-insensitive comparison.

- Input: `text: str`
- Output: `str`
- Steps (applied in order):
  1. Unicode NFC normalization.
  2. Case fold (not just `.lower()` — must handle non-ASCII case folding, e.g. `ß` → `ss`).
  3. Strip all combining characters (Unicode category `Mn`) to remove accents/diacritics.
  4. Collapse all runs of whitespace (including Unicode whitespace like `\u00A0`, `\u2003`) into a single ASCII space.
  5. Strip leading and trailing whitespace.

- Constraints:
  - Empty string returns `""`.
  - Non-string input raises `TypeError`.

- Examples:
  ```python
  normalize('Héllo  Wörld')         # 'hello world'
  normalize('STRASSE ß')            # 'strasse ss'
  normalize('  café\u00A0\u00A0 ')  # 'cafe'
  normalize('')                     # ''
  normalize('naïve résumé')         # 'naive resume'
  ```

### FR-3: Find All Matches with Context
Search for all occurrences of a query within a text, returning each match with surrounding context. Matching is performed on **normalized** forms (using FR-2), but the returned context windows use the **original** text positions.

- Input: `text: str`, `query: str`, `context_chars: int = 20`
- Output: `list[dict]` where each dict has:
  - `"start"`: int — start index in original text
  - `"end"`: int — end index (exclusive) in original text
  - `"match"`: str — the matched substring from original text
  - `"context"`: str — substring from `max(0, start - context_chars)` to `min(len(text), end + context_chars)`

- Constraints:
  - Empty query returns `[]`.
  - Overlapping matches are **all** returned (e.g. searching `"aa"` in `"aaa"` returns 2 matches).
  - When normalization changes string length (e.g. `ß` → `ss`), character positions must still correctly map back to the original text.
  - `context_chars` must be non-negative; raise `ValueError` if negative.

- Examples:
  ```python
  find_matches('Hello World Hello', 'hello', context_chars=3)
  # [
  #   {"start": 0,  "end": 5,  "match": "Hello", "context": "Hel..."},  
  #   {"start": 12, "end": 17, "match": "Hello", "context": "...llo"}
  # ]
  # (context truncated here for readability — actual output includes full window)
  
  find_matches('The café is nice', 'cafe', context_chars=5)
  # [{"start": 4, "end": 8, "match": "café", "context": "The café is n"}]
  
  find_matches('aaa', 'aa')
  # [
  #   {"start": 0, "end": 2, "match": "aa", "context": "aaa"},
  #   {"start": 1, "end": 3, "match": "aa", "context": "aaa"}
  # ]
  ```

### FR-4: Highlight Matches
Given a text and a query, return the original text with all matches wrapped in configurable delimiters.

- Input: `text: str`, `query: str`, `before: str = "**"`, `after: str = "**"`
- Output: `str`
- Constraints:
  - Uses normalized matching (same as FR-3).
  - When matches overlap, merge them into a single highlighted region rather than nesting delimiters.
  - Empty query returns the original text unchanged.
  - Delimiters are inserted based on **original** text positions.

- Examples:
  ```python
  highlight('Hello World Hello', 'hello')
  # '**Hello** World **Hello**'
  
  highlight('aabaa', 'aba')
  # '**aabaa**'  — wait, "aba" doesn't overlap here. Let me fix:
  
  highlight('aaaa', 'aa')
  # '**aaaa**'  (matches at 0-2, 1-3, 2-4 overlap → merge into one region 0-4)
  
  highlight('The café is nice', 'cafe')
  # 'The **café** is nice'
  
  highlight('hello', '', before='[', after=']')
  # 'hello'
  ```

## API Specification
```python
def tokenize(text: str) -> list[str]:
    """Tokenize string respecting quoted substrings."""
    ...

def normalize(text: str) -> str:
    """Normalize text for accent- and case-insensitive comparison."""
    ...

def find_matches(text: str, query: str, context_chars: int = 20) -> list[dict]:
    """Find all normalized matches with original-text positions and context."""
    ...

def highlight(text: str, query: str, before: str = "**", after: str = "**") -> str:
    """Highlight all matches with configurable delimiters, merging overlaps."""
    ...
```

## Edge Cases
- Empty strings (text and/or query)
- Whitespace-only strings
- Unmatched / escaped / nested quotes in tokenizer
- Unicode edge cases: `ß` (casefold length change), combining characters, non-breaking spaces
- Normalization length mismatches between original and normalized text (critical for FR-3/FR-4 position mapping)
- Overlapping matches and overlap merging
- `context_chars = 0`
- Very large texts (100,000+ characters) with many matches
- Query longer than text
- Entire text is one match
- Adjacent but non-overlapping matches