import pytest
import unicodedata
from text_utils import tokenize, normalize, find_matches, highlight


# =============================================================================
# FR-1: tokenize
# =============================================================================

class TestTokenizeBasicFunctionality:
    """Happy-path tests for tokenize (FR-1)."""

    def test_simple_whitespace_split(self):
        result = tokenize('hello world')
        assert result == ['hello', 'world'], (
            "Simple whitespace-separated words should be split into individual tokens"
        )

    def test_double_quoted_phrase_preserved(self):
        result = tokenize('say "hello world" please')
        assert result == ['say', 'hello world', 'please'], (
            "Double-quoted substring should be preserved as a single token without quotes"
        )

    def test_single_quoted_phrase_preserved(self):
        result = tokenize("say 'hello world' please")
        assert result == ['say', 'hello world', 'please'], (
            "Single-quoted substring should be preserved as a single token without quotes"
        )

    def test_multiple_quoted_tokens(self):
        result = tokenize('"foo bar" and "baz qux"')
        assert result == ['foo bar', 'and', 'baz qux'], (
            "Multiple quoted substrings in one input should each be a single token"
        )

    def test_quoted_token_at_start_and_end(self):
        result = tokenize('"start" middle "end"')
        assert result == ['start', 'middle', 'end'], (
            "Quoted tokens at start and end of string should be handled correctly"
        )

    def test_escaped_double_quote_inside_double_quoted_region(self):
        result = tokenize('say "he said \\"hi\\"" ok')
        assert result == ['say', 'he said "hi"', 'ok'], (
            "Escaped double-quotes inside a double-quoted region should become literal quotes; "
            "backslash should be removed"
        )

    def test_escaped_single_quote_inside_single_quoted_region(self):
        result = tokenize("say 'it\\'s fine' ok")
        assert result == ['say', "it's fine", 'ok'], (
            "Escaped single-quote inside single-quoted region should become a literal quote"
        )

    def test_nested_quote_type_preserved_literally(self):
        result = tokenize("he said \"it's fine\" ok")
        assert result == ['he', 'said', "it's fine", 'ok'], (
            "A quoted region using double-quotes should preserve inner single-quotes literally"
        )


class TestTokenizeEdgeCases:
    """Edge-case tests for tokenize (FR-1)."""

    def test_empty_string_returns_empty_list(self):
        result = tokenize('')
        assert result == [], "Empty string should return an empty list"

    def test_whitespace_only_returns_empty_list(self):
        result = tokenize('   ')
        assert result == [], "Whitespace-only string should return an empty list"

    def test_tabs_and_newlines_as_whitespace(self):
        result = tokenize('hello\tworld\nfoo')
        assert result == ['hello', 'world', 'foo'], (
            "Tabs and newlines should act as whitespace delimiters"
        )

    def test_unmatched_double_quote_treated_as_literal(self):
        result = tokenize('say "hello world please')
        assert result == ['say', '"hello', 'world', 'please'], (
            "Unmatched double-quote should be treated as a literal character, splitting normally"
        )

    def test_unmatched_single_quote_treated_as_literal(self):
        result = tokenize("say 'hello world please")
        assert result == ['say', "'hello", 'world', 'please'], (
            "Unmatched single-quote should be treated as a literal character, splitting normally"
        )

    def test_adjacent_quoted_and_unquoted_token_separated(self):
        result = tokenize('"hello"world foo')
        assert result == ['hello', 'world', 'foo'], (
            "Closing quote immediately followed by non-whitespace should produce separate tokens"
        )

    def test_adjacent_unquoted_then_quoted_token_separated(self):
        result = tokenize('hello"world" foo')
        assert result == ['hello', 'world', 'foo'], (
            "Non-whitespace immediately followed by opening quote should produce separate tokens"
        )

    def test_empty_double_quoted_string(self):
        result = tokenize('hello "" world')
        assert result == ['hello', '', 'world'], (
            "An empty double-quoted substring should produce an empty-string token"
        )

    def test_empty_single_quoted_string(self):
        result = tokenize("hello '' world")
        assert result == ['hello', '', 'world'], (
            "An empty single-quoted substring should produce an empty-string token"
        )

    def test_single_unquoted_token(self):
        result = tokenize('hello')
        assert result == ['hello'], (
            "A single unquoted word should return a list with that one token"
        )

    def test_only_a_quoted_token(self):
        result = tokenize('"hello world"')
        assert result == ['hello world'], (
            "A string that is entirely a quoted phrase should return it as one token"
        )

    def test_leading_and_trailing_whitespace(self):
        result = tokenize('  hello world  ')
        assert result == ['hello', 'world'], (
            "Leading and trailing whitespace should be ignored"
        )

    def test_multiple_spaces_between_tokens(self):
        result = tokenize('hello    world')
        assert result == ['hello', 'world'], (
            "Multiple spaces between tokens should not produce empty tokens"
        )

    def test_single_quote_inside_double_quoted_region_is_literal(self):
        result = tokenize("\"it's fine\"")
        assert result == ["it's fine"], (
            "Single-quote inside a double-quoted region should be preserved literally"
        )

    def test_double_quote_inside_single_quoted_region_is_literal(self):
        result = tokenize('\'say "hi"\'')
        assert result == ['say "hi"'], (
            "Double-quote inside a single-quoted region should be preserved literally"
        )


class TestTokenizeLargeScale:
    """Large-scale tests for tokenize (FR-1)."""

    def test_large_number_of_simple_tokens(self):
        words = [f'word{i}' for i in range(10_000)]
        text = ' '.join(words)
        result = tokenize(text)
        assert result == words, (
            "tokenize should correctly split 10,000 simple whitespace-separated tokens"
        )

    def test_large_number_of_quoted_tokens(self):
        phrases = [f'phrase {i}' for i in range(5_000)]
        text = ' '.join(f'"{p}"' for p in phrases)
        result = tokenize(text)
        assert result == phrases, (
            "tokenize should correctly preserve 5,000 quoted phrases as single tokens"
        )

    def test_large_text_with_mixed_quoted_and_plain_tokens(self):
        # Alternating plain and quoted tokens
        plain_tokens = [f'plain{i}' for i in range(5_000)]
        quoted_tokens = [f'quoted phrase {i}' for i in range(5_000)]
        parts = []
        expected = []
        for p, q in zip(plain_tokens, quoted_tokens):
            parts.append(p)
            parts.append(f'"{q}"')
            expected.append(p)
            expected.append(q)
        text = ' '.join(parts)
        result = tokenize(text)
        assert result == expected, (
            "tokenize should handle 10,000 alternating plain and quoted tokens correctly"
        )


# =============================================================================
# FR-2: normalize
# =============================================================================

class TestNormalizeBasicFunctionality:
    """Happy-path tests for normalize (FR-2)."""

    def test_lowercase_conversion(self):
        result = normalize('HELLO WORLD')
        assert result == 'hello world', (
            "ASCII uppercase characters should be case-folded to lowercase"
        )

    def test_accent_removal(self):
        result = normalize('Héllo Wörld')
        assert result == 'hello world', (
            "Accented characters should have diacritics stripped"
        )

    def test_eszett_casefold_expansion(self):
        result = normalize('STRASSE ß')
        assert result == 'strasse ss', (
            "ß should be case-folded to 'ss' (casefold, not just lower)"
        )

    def test_nonbreaking_space_collapsed(self):
        result = normalize('café\u00A0\u00A0nice')
        assert result == 'cafe nice', (
            "Non-breaking spaces (U+00A0) should be collapsed into a single ASCII space"
        )

    def test_leading_trailing_whitespace_stripped(self):
        result = normalize('  café\u00A0\u00A0 ')
        assert result == 'cafe', (
            "Leading and trailing whitespace should be stripped after collapsing runs"
        )

    def test_multiple_whitespace_runs_collapsed(self):
        result = normalize('hello   world')
        assert result == 'hello world', (
            "Multiple consecutive spaces should be collapsed to a single space"
        )

    def test_naive_resume_accent_removal(self):
        result = normalize('naïve résumé')
        assert result == 'naive resume', (
            "Multiple accented characters in a string should all be stripped"
        )

    def test_empty_string_returns_empty(self):
        result = normalize('')
        assert result == '', "Empty string input should return empty string"


class TestNormalizeEdgeCases:
    """Edge-case tests for normalize (FR-2)."""

    def test_non_string_integer_raises_type_error(self):
        with pytest.raises(TypeError, match=""):
            normalize(42)  # type: ignore

    def test_non_string_none_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize(None)  # type: ignore

    def test_non_string_list_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize(['hello'])  # type: ignore

    def test_whitespace_only_returns_empty_string(self):
        result = normalize('    ')
        assert result == '', (
            "A whitespace-only string should return an empty string after strip"
        )

    def test_unicode_em_space_collapsed(self):
        result = normalize('hello\u2003world')
        assert result == 'hello world', (
            "Em space (U+2003) should be treated as whitespace and collapsed"
        )

    def test_already_normalized_string_unchanged(self):
        result = normalize('hello world')
        assert result == 'hello world', (
            "A string that is already normalized should be returned unchanged"
        )

    def test_combining_characters_stripped(self):
        # e + combining acute accent (U+0301) should become just 'e'
        text = 'e\u0301'  # é as base + combining
        result = normalize(text)
        assert result == 'e', (
            "Combining characters (Unicode category Mn) should be stripped"
        )

    def test_nfc_normalization_applied(self):
        # NFD form of é vs precomposed form — both should normalize the same
        text_nfd = unicodedata.normalize('NFD', 'café')
        text_nfc = unicodedata.normalize('NFC', 'café')
        assert normalize(text_nfd) == normalize(text_nfc), (
            "NFC normalization should make NFD and NFC forms of the same text compare equal"
        )

    def test_mixed_unicode_whitespace(self):
        result = normalize('a\u00A0\u2003\tb')
        assert result == 'a b', (
            "Mixed Unicode whitespace characters should all be collapsed into a single space"
        )

    def test_string_with_only_combining_characters(self):
        # A string of only combining characters should result in empty or just spaces
        text = '\u0301\u0302\u0303'  # three combining accents, no base
        result = normalize(text)
        # All Mn category chars should be stripped; remaining should be empty after strip
        assert result == '', (
            "A string consisting only of combining characters should normalize to empty string"
        )

    def test_casefold_non_ascii(self):
        # Dotted I in Turkish — casefold handles this
        result = normalize('\u0130')  # İ (Latin capital I with dot above)
        # casefold of İ is 'i\u0307'; stripping Mn (U+0307) gives 'i'
        assert 'i' in result, (
            "Non-ASCII uppercase characters should be properly case-folded"
        )


class TestNormalizeLargeScale:
    """Large-scale tests for normalize (FR-2)."""

    def test_large_string_with_accents(self):
        # 10,000 accented characters
        text = 'é ' * 10_000
        result = normalize(text)
        expected = 'e ' * 10_000
        expected = expected.strip()
        # After normalize, multiple spaces collapse — reconstruct expected properly
        expected = ' '.join(['e'] * 10_000)
        assert result == expected, (
            "normalize should correctly strip accents from 10,000 accented characters"
        )

    def test_large_string_case_fold(self):
        text = 'HELLO ' * 10_000
        result = normalize(text)
        expected = ' '.join(['hello'] * 10_000)
        assert result == expected, (
            "normalize should correctly case-fold a 10,000-word uppercase string"
        )

    def test_large_string_with_eszett(self):
        # ß expands to ss — test that length changes are handled
        text = 'ß' * 5_000
        result = normalize(text)
        assert result == 'ss' * 5_000, (
            "normalize should expand ß to ss for all 5,000 occurrences"
        )


# =============================================================================
# FR-3: find_matches
# =============================================================================

class TestFindMatchesBasicFunctionality:
    """Happy-path tests for find_matches (FR-3)."""

    def test_single_match_simple(self):
        results = find_matches('Hello World', 'hello')
        assert len(results) == 1, "Should find exactly one match for 'hello' in 'Hello World'"
        assert results[0]['start'] == 0, "Match start should be 0"
        assert results[0]['end'] == 5, "Match end should be 5"
        assert results[0]['match'] == 'Hello', "Match text should be original-case 'Hello'"

    def test_multiple_non_overlapping_matches(self):
        results = find_matches('Hello World Hello', 'hello', context_chars=3)
        assert len(results) == 2, "Should find two matches for 'hello' in 'Hello World Hello'"
        assert results[0]['start'] == 0, "First match should start at 0"
        assert results[0]['end'] == 5, "First match should end at 5"
        assert results[1]['start'] == 12, "Second match should start at 12"
        assert results[1]['end'] == 17, "Second match should end at 17"

    def test_match_text_from_original(self):
        results = find_matches('Hello World Hello', 'hello')
        for r in results:
            assert r['match'] == 'Hello', (
                "match field should contain the original-text substring, not normalized form"
            )

    def test_context_window_correct(self):
        results = find_matches('Hello World Hello', 'hello', context_chars=3)
        assert results[0]['context'] == 'Hello W', (
            "First match context should be 3 chars after match end: 'Hello W'"
        )
        assert results[1]['context'] == 'ld Hello', (
            "Second match context should include 3 chars before start and be clipped at end"
        )

    def test_accent_insensitive_match(self):
        results = find_matches('The café is nice', 'cafe', context_chars=5)
        assert len(results) == 1, "Should find 'cafe' matching 'café' via normalization"
        assert results[0]['start'] == 4, "Match start should map to original 'café' position"
        assert results[0]['end'] == 8, "Match end should map to original 'café' end position"
        assert results[0]['match'] == 'café', "match field should be original 'café'"

    def test_overlapping_matches_all_returned(self):
        results = find_matches('aaa', 'aa')
        assert len(results) == 2, "Overlapping matches should both be returned"
        assert results[0] == {'start': 0, 'end': 2, 'match': 'aa', 'context': 'aaa'}, (
            "First overlapping match should start at 0"
        )
        assert results[1] == {'start': 1, 'end': 3, 'match': 'aa', 'context': 'aaa'}, (
            "Second overlapping match should start at 1"
        )

    def test_result_dict_has_required_keys(self):
        results = find_matches('hello world', 'hello')
        assert len(results) == 1, "Should find exactly one match"
        for key in ('start', 'end', 'match', 'context'):
            assert key in results[0], f"Result dict must contain key '{key}'"


class TestFindMatchesEdgeCases:
    """Edge-case tests for find_matches (FR-3)."""

    def test_empty_query_returns_empty_list(self):
        results = find_matches('hello world', '')
        assert results == [], "Empty query should return empty list"

    def test_query_not_found_returns_empty_list(self):
        results = find_matches('hello world', 'xyz')
        assert results == [], "No match should return empty list"

    def test_empty_text_returns_empty_list(self):
        results = find_matches('', 'hello')
        assert results == [], "Empty text should return empty list"

    def test_context_chars_zero(self):
        results = find_matches('hello world', 'hello', context_chars=0)
        assert len(results) == 1, "Should find one match with context_chars=0"
        assert results[0]['context'] == 'hello', (
            "With context_chars=0, context should equal just the match substring"
        )

    def test_negative_context_chars_raises_value_error(self):
        with pytest.raises(ValueError):
            find_matches('hello world', 'hello', context_chars=-1)

    def test_context_clipped_at_text_start(self):
        results = find_matches('hello world', 'hello', context_chars=20)
        assert results[0]['context'].startswith('hello'), (
            "Context should be clipped at text start and not go before index 0"
        )

    def test_context_clipped_at_text_end(self):
        results = find_matches('hello world', 'world', context_chars=20)
        assert results[0]['context'].endswith('world'), (
            "Context should be clipped at text end and not go beyond len(text)"
        )

    def test_entire_text_is_one_match(self):
        results = find_matches('hello', 'hello')
        assert len(results) == 1, "Should find one match when entire text matches"
        assert results[0]['start'] == 0, "Match start should be 0"
        assert results[0]['end'] == 5, "Match end should be 5"
        assert results[0]['match'] == 'hello', "Match should be the full text"

    def test_query_longer_than_text_returns_empty(self):
        results = find_matches('hi', 'hello world')
        assert results == [], "Query longer than text with no match should return empty list"

    def test_eszett_normalization_position_mapping(self):
        # 'ß' in original text (1 char) normalizes to 'ss' (2 chars)
        # Searching for 'ss' should match 'ß' at position 4
        text = 'Der Straße entlang'
        results = find_matches(text, 'straße')
        assert len(results) >= 1, "Should find 'straße' in text"
        first = results[0]
        assert text[first['start']:first['end']] == first['match'], (
            "start/end indices must correctly slice the original text"
        )

    def test_case_insensitive_match(self):
        results = find_matches('HELLO hello Hello', 'hello')
        assert len(results) == 3, "Case-insensitive matching should find all 3 occurrences"

    def test_context_chars_default_is_20(self):
        text = 'a' * 50 + 'hello' + 'b' * 50
        results = find_matches(text, 'hello')
        context = results[0]['context']
        assert len(context) == 5 + 20 + 20, (
            "Default context_chars=20 should give 20 chars before and after match"
        )


class TestFindMatchesLargeScale:
    """Large-scale tests for find_matches (FR-3)."""

    def test_many_matches_in_large_text(self):
        # 'hello' repeated 10,000 times separated by spaces
        text = 'hello ' * 10_000
        text = text.rstrip()
        results = find_matches(text, 'hello')
        assert len(results) == 10_000, (
            "find_matches should locate all 10,000 occurrences of 'hello'"
        )

    def test_overlapping_matches_large_scale(self):
        # 'aaa...a' (10,001 'a's) → searching 'aa' gives 10,000 overlapping matches
        text = 'a' * 10_001
        results = find_matches(text, 'aa')
        assert len(results) == 10_000, (
            "find_matches should return 10,000 overlapping 'aa' matches in a string of 10,001 'a's"
        )

    def test_no_false_positives_large_text(self):
        text = 'b' * 100_000
        results = find_matches(text, 'hello')
        assert results == [], (
            "find_matches should return no matches when query is absent from a 100,000-char text"
        )


# =============================================================================
# FR-4: highlight
# =============================================================================

class TestHighlightBasicFunctionality:
    """Happy-path tests for highlight (FR-4)."""

    def test_simple_highlight_default_delimiters(self):
        result = highlight('Hello World Hello', 'hello')
        assert result == '**Hello** World **Hello**', (
            "Both occurrences of 'hello' (case-insensitive) should be wrapped with '**'"
        )

    def test_custom_delimiters(self):
        result = highlight('Hello World', 'hello', before='[', after=']')
        assert result == '[Hello] World', (
            "Custom before/after delimiters should be used instead of '**'"
        )

    def test_accent_insensitive_highlight(self):
        result = highlight('The café is nice', 'cafe')
        assert result == 'The **café** is nice', (
            "Accent-insensitive match should highlight 'café' when searching for 'cafe'"
        )

    def test_overlapping_matches_merged(self):
        result = highlight('aaaa', 'aa')
        assert result == '**aaaa**', (
            "Overlapping matches (0-2, 1-3, 2-4) should be merged into one highlighted region"
        )

    def test_empty_query_returns_original_text(self):
        result = highlight('hello', '')
        assert result == 'hello', (
            "Empty query should return original text unchanged"
        )

    def test_no_match_returns_original_text(self):
        result = highlight('hello world', 'xyz')
        assert result == 'hello world', (
            "No match should return original text unchanged"
        )

    def test_entire_text_highlighted(self):
        result = highlight('hello', 'hello')
        assert result == '**hello**', (
            "When entire text is a match, entire text should be wrapped in delimiters"
        )


class TestHighlightEdgeCases:
    """Edge-case tests for highlight (FR-4)."""

    def test_empty_text_empty_query(self):
        result = highlight('', '')
        assert result == '', "Empty text with empty query should return empty string"

    def test_empty_text_nonempty_query(self):
        result = highlight('', 'hello')
        assert result == '', "Empty text with a query should return empty string"

    def test_case_insensitive_all_occurrences(self):
        result = highlight('HELLO hello Hello', 'hello')
        assert result == '**HELLO** **hello** **Hello**', (
            "All case variants of 'hello' should be highlighted"
        )

    def test_adjacent_non_overlapping_matches_separately_highlighted(self):
        result = highlight('abcabc', 'abc')
        assert result == '**abc****abc**' or result == '**abc**' + '**abc**', (
            "Two adjacent non-overlapping matches should each be wrapped independently"
        )

    def test_overlapping_three_way_merged(self):
        # 'aaaa' with 'aa': matches at 0-2, 1-3, 2-4 → merged to 0-4
        result = highlight('aaaa', 'aa')
        assert result == '**aaaa**', (
            "Three overlapping 'aa' matches in 'aaaa' should merge into one region"
        )

    def test_eszett_highlight_position_mapping(self):
        result = highlight('Die Straße', 'strasse')
        assert '**' in result, (
            "ß (normalizes to 'ss') should be found when searching 'strasse' and highlighted"
        )
        assert 'Straße' in result, (
            "The original 'Straße' text should appear (possibly wrapped) in the output"
        )

    def test_before_after_empty_strings(self):
        result = highlight('Hello World', 'hello', before='', after='')
        assert result == 'Hello World', (
            "Empty before/after delimiters should still return original text"
        )

    def test_html_tag_delimiters(self):
        result = highlight('Hello World', 'hello', before='<mark>', after='</mark>')
        assert result == '<mark>Hello</mark> World', (
            "HTML tag delimiters should be inserted around matches correctly"
        )

    def test_query_longer_than_text_no_highlight(self):
        result = highlight('hi', 'hello world')
        assert result == 'hi', (
            "Query longer than text with no match should return original text"
        )

    def test_whitespace_only_text(self):
        result = highlight('   ', 'hello')
        assert result == '   ', (
            "Whitespace-only text with no match should return original whitespace text"
        )

    def test_match_at_start_of_text(self):
        result = highlight('hello world', 'hello')
        assert result.startswith('**hello**'), (
            "A match at the very start of the text should be highlighted correctly"
        )

    def test_match_at_end_of_text(self):
        result = highlight('world hello', 'hello')
        assert result.endswith('**hello**'), (
            "A match at the very end of the text should be highlighted correctly"
        )


class TestHighlightLargeScale:
    """Large-scale tests for highlight (FR-4)."""

    def test_many_matches_highlighted(self):
        # 10,000 'hello' tokens
        text = 'hello ' * 10_000
        text = text.rstrip()
        result = highlight(text, 'hello')
        expected_count = text.count('hello')
        highlighted_count = result.count('**hello**')
        assert highlighted_count == expected_count, (
            f"All {expected_count} occurrences of 'hello' should be highlighted"
        )

    def test_fully_overlapping_large_text_merged_to_one(self):
        # 'a' * 10,000 with query 'aa' → all overlapping → one big region
        text = 'a' * 10_000
        result = highlight(text, 'aa', before='[', after=']')
        assert result == '[' + 'a' * 10_000 + ']', (
            "All overlapping 'aa' matches across 10,000 'a's should merge into one highlighted region"
        )

    def test_large_text_no_match_unchanged(self):
        text = 'b' * 100_000
        result = highlight(text, 'hello')
        assert result == text, (
            "highlight should return original 100,000-char text unchanged when query is not found"
        )
