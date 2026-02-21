import unicodedata
import pytest
from text_utils import tokenize, normalize, find_matches, highlight


# ===========================================================================
# FR-1: tokenize
# ===========================================================================

class TestTokenizeBasicFunctionality:
    """Happy-path tests for tokenize()."""

    def test_simple_whitespace_split(self):
        result = tokenize("hello world")
        assert result == ["hello", "world"], (
            "Two whitespace-separated words should become two tokens"
        )

    def test_double_quoted_phrase_preserved(self):
        result = tokenize('say "hello world" please')
        assert result == ["say", "hello world", "please"], (
            "Double-quoted phrase must be a single token with quotes stripped"
        )

    def test_single_quoted_phrase_preserved(self):
        result = tokenize("say 'hello world' please")
        assert result == ["say", "hello world", "please"], (
            "Single-quoted phrase must be a single token with quotes stripped"
        )

    def test_multiple_quoted_regions(self):
        result = tokenize('"foo bar" baz "qux quux"')
        assert result == ["foo bar", "baz", "qux quux"], (
            "Multiple quoted regions should each become single tokens"
        )

    def test_single_unquoted_word(self):
        result = tokenize("hello")
        assert result == ["hello"], (
            "Single unquoted word should be returned as a one-element list"
        )

    def test_leading_and_trailing_whitespace(self):
        result = tokenize("  hello world  ")
        assert result == ["hello", "world"], (
            "Leading and trailing whitespace should not produce empty tokens"
        )

    def test_multiple_spaces_between_tokens(self):
        result = tokenize("hello   world")
        assert result == ["hello", "world"], (
            "Multiple spaces between tokens should not produce empty tokens"
        )


class TestTokenizeEdgeCases:
    """Edge-case tests for tokenize()."""

    def test_empty_string_returns_empty_list(self):
        result = tokenize("")
        assert result == [], "Empty string must return []"

    def test_whitespace_only_returns_empty_list(self):
        result = tokenize("   ")
        assert result == [], "Whitespace-only string must return []"

    def test_tabs_and_newlines_as_whitespace(self):
        result = tokenize("hello\tworld\nfoo")
        assert result == ["hello", "world", "foo"], (
            "Tabs and newlines should act as whitespace delimiters"
        )

    def test_unmatched_double_quote_treated_as_literal(self):
        result = tokenize('say "hello world please')
        assert result == ["say", '"hello', "world", "please"], (
            "Unmatched opening quote must be treated as a literal character"
        )

    def test_unmatched_single_quote_treated_as_literal(self):
        result = tokenize("say 'hello world please")
        assert result == ["say", "'hello", "world", "please"], (
            "Unmatched single quote must be treated as a literal character"
        )

    def test_escaped_double_quote_inside_double_quoted_region(self):
        result = tokenize(r'say "he said \"hi\"" ok')
        assert result == ["say", 'he said "hi"', "ok"], (
            r'Escaped \" inside double-quoted region must become literal " in token'
        )

    def test_escaped_single_quote_inside_single_quoted_region(self):
        result = tokenize(r"say 'it\'s fine' ok")
        assert result == ["say", "it's fine", "ok"], (
            r"Escaped \' inside single-quoted region must become literal ' in token"
        )

    def test_adjacent_quoted_and_unquoted_are_separate_tokens(self):
        result = tokenize('"hello"world foo')
        assert result == ["hello", "world", "foo"], (
            '"hello"world must produce two separate tokens: hello and world'
        )

    def test_nested_single_quote_inside_double_quoted_region(self):
        result = tokenize("\"it's fine\"")
        assert result == ["it's fine"], (
            "Single quote inside double-quoted region must be preserved literally"
        )

    def test_nested_double_quote_inside_single_quoted_region(self):
        result = tokenize("'say \"hi\" please'")
        assert result == ['say "hi" please'], (
            "Double quote inside single-quoted region must be preserved literally"
        )

    def test_empty_double_quoted_string(self):
        result = tokenize('""')
        assert result == [""], (
            "Empty double-quoted string should produce a single empty-string token"
        )

    def test_empty_single_quoted_string(self):
        result = tokenize("''")
        assert result == [""], (
            "Empty single-quoted string should produce a single empty-string token"
        )

    def test_quoted_region_at_end_of_string(self):
        result = tokenize('hello "world foo"')
        assert result == ["hello", "world foo"], (
            "Quoted region at the end of the string must be handled correctly"
        )

    def test_quoted_region_at_start_of_string(self):
        result = tokenize('"hello world" foo')
        assert result == ["hello world", "foo"], (
            "Quoted region at the start of the string must be handled correctly"
        )

    def test_adjacent_quoted_tokens_no_space(self):
        result = tokenize('"foo""bar"')
        assert result == ["foo", "bar"], (
            "Two adjacent quoted tokens with no whitespace must be separate tokens"
        )


class TestTokenizeLargeScale:
    """Large-scale tests for tokenize()."""

    def test_large_number_of_simple_tokens(self):
        n = 10_000
        text = " ".join(f"word{i}" for i in range(n))
        result = tokenize(text)
        assert len(result) == n, (
            f"Tokenizing {n} space-separated words must return exactly {n} tokens"
        )
        assert result[0] == "word0", "First token must be word0"
        assert result[-1] == f"word{n-1}", f"Last token must be word{n-1}"

    def test_large_number_of_quoted_tokens(self):
        n = 5_000
        phrases = [f'"phrase {i}"' for i in range(n)]
        text = " ".join(phrases)
        result = tokenize(text)
        assert len(result) == n, (
            f"Tokenizing {n} double-quoted phrases must return exactly {n} tokens"
        )
        assert result[0] == "phrase 0", "First quoted token must be 'phrase 0'"
        assert result[-1] == f"phrase {n-1}", f"Last quoted token must be 'phrase {n-1}'"

    def test_large_interleaved_quoted_and_unquoted(self):
        n = 3_000
        parts = []
        for i in range(n):
            if i % 2 == 0:
                parts.append(f'"quoted {i}"')
            else:
                parts.append(f"plain{i}")
        text = " ".join(parts)
        result = tokenize(text)
        assert len(result) == n, (
            f"Interleaved quoted/unquoted tokens: expected {n} tokens"
        )
        assert result[0] == "quoted 0", "First token should be 'quoted 0'"
        assert result[1] == "plain1", "Second token should be 'plain1'"


# ===========================================================================
# FR-2: normalize
# ===========================================================================

class TestNormalizeBasicFunctionality:
    """Happy-path tests for normalize()."""

    def test_lowercase_conversion(self):
        result = normalize("HELLO WORLD")
        assert result == "hello world", (
            "normalize() must case-fold ASCII uppercase letters to lowercase"
        )

    def test_accent_removal(self):
        result = normalize("Héllo Wörld")
        assert result == "hello world", (
            "normalize() must strip combining diacritics and case-fold"
        )

    def test_cafe_accent(self):
        result = normalize("café")
        assert result == "cafe", (
            "normalize() must strip the accent from é in 'café'"
        )

    def test_naive_resume(self):
        result = normalize("naïve résumé")
        assert result == "naive resume", (
            "normalize() must remove all diacritics from 'naïve résumé'"
        )

    def test_collapse_multiple_spaces(self):
        result = normalize("hello   world")
        assert result == "hello world", (
            "Multiple consecutive spaces must be collapsed to a single space"
        )

    def test_strip_leading_trailing_whitespace(self):
        result = normalize("  hello world  ")
        assert result == "hello world", (
            "Leading and trailing whitespace must be stripped"
        )

    def test_plain_ascii_unchanged(self):
        result = normalize("hello world")
        assert result == "hello world", (
            "Plain ASCII text should be returned unchanged (except case-fold)"
        )


class TestNormalizeEdgeCases:
    """Edge-case tests for normalize()."""

    def test_empty_string_returns_empty_string(self):
        result = normalize("")
        assert result == "", "Empty string must normalize to empty string"

    def test_non_string_raises_type_error(self):
        with pytest.raises(TypeError, match=""):
            normalize(123)  # type: ignore

    def test_none_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize(None)  # type: ignore

    def test_list_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize(["hello"])  # type: ignore

    def test_eszett_casefolded_to_ss(self):
        result = normalize("ß")
        assert result == "ss", (
            "German ß must casefold to 'ss' (length-changing casefold)"
        )

    def test_strasse_with_eszett(self):
        result = normalize("STRASSE ß")
        assert result == "strasse ss", (
            "Mixed 'STRASSE ß' must normalize to 'strasse ss'"
        )

    def test_non_breaking_space_collapsed(self):
        result = normalize("hello\u00A0world")
        assert result == "hello world", (
            "Non-breaking space (U+00A0) must be treated as whitespace and collapsed"
        )

    def test_em_space_collapsed(self):
        result = normalize("hello\u2003world")
        assert result == "hello world", (
            "Em space (U+2003) must be treated as whitespace and collapsed"
        )

    def test_multiple_unicode_whitespace_collapsed(self):
        result = normalize("café\u00A0\u00A0 ")
        assert result == "cafe", (
            "Multiple trailing Unicode whitespace chars must be collapsed and stripped"
        )

    def test_combining_characters_stripped(self):
        # Build a string with a combining character directly
        text = "a\u0300"  # 'a' + combining grave accent
        result = normalize(text)
        assert result == "a", (
            "Combining grave accent (Mn category) must be stripped"
        )

    def test_whitespace_only_returns_empty_string(self):
        result = normalize("   ")
        assert result == "", (
            "Whitespace-only input must normalize to empty string after strip"
        )

    def test_nfc_normalization_applied(self):
        # é can be represented as U+00E9 (precomposed) or U+0065 U+0301 (decomposed)
        precomposed = "\u00e9"
        decomposed = "e\u0301"
        assert normalize(precomposed) == normalize(decomposed), (
            "NFC normalization must make precomposed and decomposed forms equivalent"
        )

    def test_greek_capital_sigma_casefolded(self):
        result = normalize("Σ")
        assert result == "σ" or result == "ς" or result == normalize("σ"), (
            "Greek capital sigma must be case-folded"
        )


class TestNormalizeLargeScale:
    """Large-scale tests for normalize()."""

    def test_large_ascii_string(self):
        n = 100_000
        text = "Hello World " * (n // 12 + 1)
        text = text[:n]
        result = normalize(text)
        assert "hello" in result, "Normalized large ASCII string must contain 'hello'"
        assert result == result.lower(), (
            "Normalized large ASCII string must be all lowercase"
        )

    def test_large_accented_string(self):
        n = 10_000
        word = "Héllo"
        text = " ".join([word] * n)
        result = normalize(text)
        tokens = result.split(" ")
        assert all(t == "hello" for t in tokens), (
            f"Every token in normalized output must be 'hello', got first={tokens[0]!r}"
        )

    def test_large_string_with_eszett(self):
        n = 10_000
        text = " ".join(["ß"] * n)
        result = normalize(text)
        tokens = result.split(" ")
        assert all(t == "ss" for t in tokens), (
            "Every ß token must normalize to 'ss'"
        )


# ===========================================================================
# FR-3: find_matches
# ===========================================================================

class TestFindMatchesBasicFunctionality:
    """Happy-path tests for find_matches()."""

    def test_single_match_basic(self):
        results = find_matches("Hello World", "hello")
        assert len(results) == 1, "Must find exactly one match for 'hello' in 'Hello World'"
        m = results[0]
        assert m["start"] == 0, "Match start must be 0"
        assert m["end"] == 5, "Match end must be 5"
        assert m["match"] == "Hello", "Match text must be 'Hello' from original"

    def test_multiple_non_overlapping_matches(self):
        results = find_matches("Hello World Hello", "hello", context_chars=3)
        assert len(results) == 2, "Must find two matches of 'hello'"
        assert results[0]["start"] == 0, "First match start must be 0"
        assert results[0]["end"] == 5, "First match end must be 5"
        assert results[1]["start"] == 12, "Second match start must be 12"
        assert results[1]["end"] == 17, "Second match end must be 17"

    def test_context_window_correct(self):
        results = find_matches("Hello World Hello", "hello", context_chars=3)
        assert len(results) == 2, "Must find two matches"
        # First match: start=0, end=5, context = max(0,0-3) to min(17, 5+3) = 0..8
        assert results[0]["context"] == "Hello Wo", (
            "First match context window must span [0, 8)"
        )
        # Second match: start=12, end=17, context = max(0,12-3) to min(17, 17+3) = 9..17
        assert results[1]["context"] == "d Hello", (
            "Second match context window must span [9, 17)"
        )

    def test_accent_insensitive_match(self):
        results = find_matches("The café is nice", "cafe", context_chars=5)
        assert len(results) == 1, "Must find 'cafe' in 'café' via normalized matching"
        assert results[0]["start"] == 4, "Match start must be 4"
        assert results[0]["end"] == 8, "Match end must be 8 (original text positions)"
        assert results[0]["match"] == "café", "Matched text from original must be 'café'"

    def test_context_chars_zero(self):
        results = find_matches("Hello World", "hello", context_chars=0)
        assert len(results) == 1, "Must find one match with context_chars=0"
        assert results[0]["context"] == "Hello", (
            "With context_chars=0, context must equal just the matched substring"
        )

    def test_result_dict_keys_present(self):
        results = find_matches("hello", "hello")
        assert len(results) == 1, "Must find one match"
        m = results[0]
        for key in ("start", "end", "match", "context"):
            assert key in m, f"Result dict must contain key '{key}'"

    def test_case_insensitive_matching(self):
        results = find_matches("HELLO hello Hello", "hello")
        assert len(results) == 3, (
            "Case-insensitive matching must find all 3 variations of 'hello'"
        )


class TestFindMatchesEdgeCases:
    """Edge-case tests for find_matches()."""

    def test_empty_query_returns_empty_list(self):
        results = find_matches("hello world", "")
        assert results == [], "Empty query must return []"

    def test_empty_text_returns_empty_list(self):
        results = find_matches("", "hello")
        assert results == [], "Empty text with non-empty query must return []"

    def test_both_empty_returns_empty_list(self):
        results = find_matches("", "")
        assert results == [], "Both empty strings must return []"

    def test_negative_context_chars_raises_value_error(self):
        with pytest.raises(ValueError):
            find_matches("hello world", "hello", context_chars=-1)

    def test_overlapping_matches_all_returned(self):
        results = find_matches("aaa", "aa")
        assert len(results) == 2, "Overlapping 'aa' in 'aaa' must return 2 matches"
        assert results[0]["start"] == 0 and results[0]["end"] == 2, (
            "First overlapping match must span [0, 2)"
        )
        assert results[1]["start"] == 1 and results[1]["end"] == 3, (
            "Second overlapping match must span [1, 3)"
        )

    def test_query_longer_than_text(self):
        results = find_matches("hi", "hello world")
        assert results == [], "Query longer than text must return no matches"

    def test_no_match_returns_empty_list(self):
        results = find_matches("hello world", "xyz")
        assert results == [], "Non-matching query must return []"

    def test_entire_text_is_one_match(self):
        results = find_matches("hello", "hello")
        assert len(results) == 1, "Entire text matching query must return one match"
        assert results[0]["start"] == 0, "Start must be 0"
        assert results[0]["end"] == 5, "End must be 5"
        assert results[0]["context"] == "hello", (
            "Context must equal the full text when text==query with default context_chars"
        )

    def test_eszett_normalization_match(self):
        # "Straße" normalizes to "strasse"
        results = find_matches("Straße", "strasse")
        assert len(results) == 1, "Must match 'strasse' against 'Straße' via normalization"
        assert results[0]["match"] == "Straße", (
            "Matched text must come from original ('Straße'), not normalized form"
        )

    def test_context_clamped_at_text_boundaries(self):
        results = find_matches("hi", "hi", context_chars=100)
        assert len(results) == 1, "Must find one match"
        assert results[0]["context"] == "hi", (
            "Context must clamp to text boundaries, not go out of range"
        )

    def test_adjacent_non_overlapping_matches(self):
        results = find_matches("abab", "ab")
        assert len(results) == 2, "Must find two adjacent non-overlapping 'ab' matches"
        assert results[0]["start"] == 0 and results[0]["end"] == 2, (
            "First match must be at [0, 2)"
        )
        assert results[1]["start"] == 2 and results[1]["end"] == 4, (
            "Second match must be at [2, 4)"
        )

    def test_match_field_uses_original_text(self):
        results = find_matches("Héllo", "hello")
        assert len(results) == 1, "Must match normalized 'hello' against 'Héllo'"
        assert results[0]["match"] == "Héllo", (
            "'match' field must contain original text, not normalized form"
        )


class TestFindMatchesLargeScale:
    """Large-scale tests for find_matches()."""

    def test_many_non_overlapping_matches(self):
        n = 5_000
        text = "hello world " * n
        results = find_matches(text, "hello")
        assert len(results) == n, (
            f"Must find exactly {n} matches of 'hello' in repeated text"
        )

    def test_large_text_no_match(self):
        text = "a" * 100_000
        results = find_matches(text, "b")
        assert results == [], (
            "Large text with no matching query must return []"
        )

    def test_overlapping_matches_large(self):
        # "aaa...a" (n chars) with query "aa" → n-1 overlapping matches
        n = 1_000
        text = "a" * n
        results = find_matches(text, "aa")
        assert len(results) == n - 1, (
            f"'aa' in a string of {n} 'a's must produce {n-1} overlapping matches"
        )


# ===========================================================================
# FR-4: highlight
# ===========================================================================

class TestHighlightBasicFunctionality:
    """Happy-path tests for highlight()."""

    def test_single_match_default_delimiters(self):
        result = highlight("Hello World", "hello")
        assert result == "**Hello** World", (
            "Single match must be wrapped in '**' delimiters"
        )

    def test_multiple_non_overlapping_matches(self):
        result = highlight("Hello World Hello", "hello")
        assert result == "**Hello** World **Hello**", (
            "Both non-overlapping matches must be wrapped independently"
        )

    def test_custom_delimiters(self):
        result = highlight("Hello World", "hello", before="[", after="]")
        assert result == "[Hello] World", (
            "Custom before/after delimiters must be used instead of '**'"
        )

    def test_accent_insensitive_highlight(self):
        result = highlight("The café is nice", "cafe")
        assert result == "The **café** is nice", (
            "highlight() must use normalized matching to find accented matches"
        )

    def test_empty_query_returns_original_text(self):
        result = highlight("hello", "")
        assert result == "hello", (
            "Empty query must return the original text unchanged"
        )


class TestHighlightEdgeCases:
    """Edge-case tests for highlight()."""

    def test_overlapping_matches_merged(self):
        result = highlight("aaaa", "aa")
        assert result == "**aaaa**", (
            "Overlapping matches at 0-2, 1-3, 2-4 must merge into one region 0-4"
        )

    def test_three_way_overlap_merged(self):
        # "aaa" with query "aa" → matches [0,2) and [1,3) → merged to [0,3)
        result = highlight("aaa", "aa")
        assert result == "**aaa**", (
            "Overlapping matches in 'aaa' must merge into a single highlighted region"
        )

    def test_no_match_returns_original_text(self):
        result = highlight("hello world", "xyz")
        assert result == "hello world", (
            "No match must return original text unchanged"
        )

    def test_entire_text_is_match(self):
        result = highlight("hello", "hello")
        assert result == "**hello**", (
            "Entire text matching query must be wrapped in delimiters"
        )

    def test_empty_text_empty_query(self):
        result = highlight("", "")
        assert result == "", (
            "Empty text with empty query must return empty string"
        )

    def test_empty_text_non_empty_query(self):
        result = highlight("", "hello")
        assert result == "", (
            "Empty text with non-empty query must return empty string"
        )

    def test_adjacent_non_overlapping_matches_separate_highlights(self):
        result = highlight("abab", "ab")
        assert result == "**ab****ab**" or result == "**ab**" + "**ab**", (
            "Adjacent non-overlapping matches must each be wrapped separately"
        )

    def test_eszett_highlight(self):
        result = highlight("Straße", "strasse")
        assert result == "**Straße**", (
            "'Straße' matched by 'strasse' must be fully wrapped in delimiters"
        )

    def test_case_insensitive_highlight(self):
        result = highlight("Hello HELLO hello", "hello")
        assert result == "**Hello** **HELLO** **hello**", (
            "All case variants must be highlighted via normalized matching"
        )

    def test_custom_html_delimiters(self):
        result = highlight("Hello World", "world", before="<b>", after="</b>")
        assert result == "Hello <b>World</b>", (
            "HTML-style custom delimiters must be inserted correctly"
        )

    def test_overlapping_then_adjacent_structure(self):
        # 'aabaa': query 'aa' matches at [0,2) and [3,5) — non-overlapping
        result = highlight("aabaa", "aa")
        assert result == "**aa**b**aa**", (
            "'aa' matches at positions 0-2 and 3-5 in 'aabaa' must be separate highlights"
        )


class TestHighlightLargeScale:
    """Large-scale tests for highlight()."""

    def test_large_text_many_matches(self):
        n = 5_000
        text = "hello world " * n
        result = highlight(text, "hello")
        count = result.count("**hello**") + result.count("**Hello**")
        # Due to exact original-text casing, count "hello" occurrences
        assert result.count("**hello**") == n, (
            f"Must wrap all {n} occurrences of 'hello' in the large repeated text"
        )

    def test_large_overlapping_highlight_merged(self):
        n = 10_000
        text = "a" * n
        result = highlight(text, "aa")
        # All overlapping matches merge into one region covering the full text
        assert result == f"**{'a' * n}**", (
            f"All overlapping 'aa' matches in a {n}-char 'a'-string must merge into one highlight"
        )

    def test_large_text_no_match(self):
        text = "hello world " * 5_000
        result = highlight(text, "xyz")
        assert result == text, (
            "Large text with no matching query must be returned unchanged"
        )
