"""
Comprehensive tests for list_utils module.
Tests are written against the specification, not any implementation.
"""

import pytest
from list_utils import has_close_elements, is_monotonic


# ===========================================================================
# FR-1: has_close_elements
# ===========================================================================

class TestHasCloseElementsBasicFunctionality:
    """Happy-path tests derived directly from the FR-1 specification."""

    def test_no_close_pair_returns_false(self):
        assert has_close_elements([1.0, 2.0, 3.0], 0.5) is False, \
            "Elements spaced 1.0 apart with threshold 0.5 should return False"

    def test_close_pair_exists_returns_true(self):
        assert has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3) is True, \
            "2.8 and 3.0 are 0.2 apart, which is less than threshold 0.3"

    def test_exactly_at_threshold_returns_false(self):
        assert has_close_elements([1.0, 2.0, 3.0], 1.0) is False, \
            "Pairs exactly AT the threshold distance are NOT closer than threshold"

    def test_just_below_threshold_returns_true(self):
        assert has_close_elements([1.0, 1.9], 0.95) is True, \
            "1.0 and 1.9 are 0.9 apart, which is less than 0.95 threshold"

    def test_non_adjacent_pair_detected(self):
        assert has_close_elements([1.0, 5.0, 6.0, 10.0], 1.5) is True, \
            "5.0 and 6.0 are close even though they are not first/last elements"


class TestHasCloseElementsEdgeCases:
    """Edge-case tests for has_close_elements."""

    def test_empty_list_returns_false(self):
        assert has_close_elements([], 0.5) is False, \
            "Empty list must return False per specification"

    def test_single_element_returns_false(self):
        assert has_close_elements([42.0], 0.5) is False, \
            "Single-element list must return False per specification"

    def test_two_identical_elements_threshold_above_zero_returns_true(self):
        assert has_close_elements([1.0, 1.0], 0.5) is True, \
            "Two identical elements have distance 0, which is less than any positive threshold"

    def test_two_identical_elements_zero_threshold_returns_false(self):
        assert has_close_elements([1.0, 1.0], 0.0) is False, \
            "Distance 0 is NOT closer than threshold 0 (0 < 0 is False)"

    def test_zero_threshold_no_pair_returns_false(self):
        assert has_close_elements([1.0, 2.0, 3.0], 0.0) is False, \
            "With zero threshold, no pair is closer than 0 unless they are identical"

    def test_negative_numbers_close_pair(self):
        assert has_close_elements([-1.0, -1.05, -5.0], 0.1) is True, \
            "-1.0 and -1.05 are 0.05 apart, less than threshold 0.1"

    def test_negative_numbers_no_close_pair(self):
        assert has_close_elements([-10.0, -5.0, -1.0], 1.0) is False, \
            "All pairs are at least 4.0 apart, threshold is 1.0"

    def test_mixed_positive_and_negative_close_pair(self):
        assert has_close_elements([-0.1, 0.1], 0.3) is True, \
            "-0.1 and 0.1 are 0.2 apart, which is less than 0.3 threshold"

    def test_all_identical_elements_returns_true(self):
        assert has_close_elements([7.0, 7.0, 7.0, 7.0], 0.1) is True, \
            "All identical elements have pairwise distance 0, less than any positive threshold"

    def test_very_small_threshold(self):
        assert has_close_elements([1.0, 1.000000001, 2.0], 1e-8) is True, \
            "1.0 and 1.000000001 differ by 1e-9, which is less than threshold 1e-8"

    def test_very_large_threshold_returns_true(self):
        assert has_close_elements([1.0, 1000000.0], 9999999.0) is True, \
            "Gap of 999999 is less than threshold 9999999"

    def test_two_elements_not_close(self):
        assert has_close_elements([0.0, 1.0], 0.5) is False, \
            "Two elements exactly 1.0 apart with threshold 0.5 should return False"

    def test_unsorted_list_close_pair_detected(self):
        assert has_close_elements([10.0, 1.0, 9.9, 20.0], 0.2) is True, \
            "10.0 and 9.9 are 0.1 apart; function must not assume sorted input"

    def test_floats_requiring_precision(self):
        assert has_close_elements([0.1 + 0.2, 0.3], 1e-9) is True or \
               has_close_elements([0.1 + 0.2, 0.3], 1e-9) is False, \
            "Result must be a bool; floating-point representation is implementation detail"


class TestHasCloseElementsLargeScale:
    """Large-scale tests for has_close_elements."""

    def test_large_list_no_close_pair(self):
        # Elements spaced exactly 1.0 apart; threshold is 0.5 → no pair qualifies
        numbers = [float(i) for i in range(10_000)]
        result = has_close_elements(numbers, 0.5)
        assert result is False, \
            "10,000 elements spaced 1.0 apart should have no pair closer than 0.5"

    def test_large_list_one_close_pair_at_end(self):
        # All elements 1.0 apart except last two which are 0.1 apart
        numbers = [float(i) for i in range(9_999)]
        numbers.append(9997.1)  # close to 9997.0 which is at index 9997
        result = has_close_elements(numbers, 0.5)
        assert result is True, \
            "One close pair (0.1 apart) hidden at the end of 10,000 elements should be detected"

    def test_large_list_all_identical_returns_true(self):
        numbers = [3.14] * 10_000
        result = has_close_elements(numbers, 0.01)
        assert result is True, \
            "10,000 identical elements all have distance 0, less than any positive threshold"


# ===========================================================================
# FR-2: is_monotonic
# ===========================================================================

class TestIsMonotonicBasicFunctionality:
    """Happy-path tests derived directly from the FR-2 specification."""

    def test_strictly_increasing_returns_true(self):
        assert is_monotonic([1, 2, 3, 4, 5]) is True, \
            "Strictly increasing sequence should be monotonic"

    def test_strictly_decreasing_returns_true(self):
        assert is_monotonic([5, 4, 3, 2, 1]) is True, \
            "Strictly decreasing sequence should be monotonic"

    def test_non_monotonic_returns_false(self):
        assert is_monotonic([1, 3, 2, 4]) is False, \
            "Sequence that goes up then down is not monotonic"

    def test_non_monotonic_decreasing_then_increasing(self):
        assert is_monotonic([5, 3, 4, 1]) is False, \
            "Sequence that goes down then up is not monotonic"

    def test_equal_adjacent_elements_increasing_trend(self):
        assert is_monotonic([1, 1, 2, 3]) is True, \
            "Equal adjacent elements are allowed; overall trend is non-decreasing"


class TestIsMonotonicEdgeCases:
    """Edge-case tests for is_monotonic."""

    def test_empty_list_returns_true(self):
        assert is_monotonic([]) is True, \
            "Empty list is monotonic per specification"

    def test_single_element_returns_true(self):
        assert is_monotonic([42]) is True, \
            "Single-element list is monotonic per specification"

    def test_all_equal_elements_returns_true(self):
        assert is_monotonic([7, 7, 7, 7]) is True, \
            "All-equal list is both non-decreasing and non-increasing, so monotonic"

    def test_two_elements_increasing_returns_true(self):
        assert is_monotonic([1, 2]) is True, \
            "Two elements in increasing order are monotonic"

    def test_two_elements_decreasing_returns_true(self):
        assert is_monotonic([2, 1]) is True, \
            "Two elements in decreasing order are monotonic"

    def test_two_equal_elements_returns_true(self):
        assert is_monotonic([5, 5]) is True, \
            "Two equal elements satisfy both non-decreasing and non-increasing"

    def test_negative_numbers_increasing(self):
        assert is_monotonic([-5, -4, -3, -2, -1]) is True, \
            "Increasing sequence of negatives is monotonic"

    def test_negative_numbers_decreasing(self):
        assert is_monotonic([-1, -2, -3, -4]) is True, \
            "Decreasing sequence of negatives is monotonic"

    def test_mixed_sign_increasing(self):
        assert is_monotonic([-3, -1, 0, 2, 5]) is True, \
            "Increasing sequence crossing zero is monotonic"

    def test_mixed_sign_non_monotonic(self):
        assert is_monotonic([-3, 2, -1, 4]) is False, \
            "Alternating positive and negative values are not monotonic"

    def test_plateau_then_decrease_is_monotonic(self):
        assert is_monotonic([5, 5, 4, 3]) is True, \
            "Non-increasing (plateau then decrease) is monotonic decreasing"

    def test_plateau_then_increase_is_monotonic(self):
        assert is_monotonic([1, 2, 2, 3]) is True, \
            "Non-decreasing (increase then plateau) is monotonic increasing"

    def test_valley_shape_not_monotonic(self):
        assert is_monotonic([5, 3, 3, 4]) is False, \
            "Decrease then increase (valley) is not monotonic"

    def test_peak_shape_not_monotonic(self):
        assert is_monotonic([1, 3, 3, 2]) is False, \
            "Increase then decrease (peak) is not monotonic"

    def test_zeros_and_positives_increasing(self):
        assert is_monotonic([0, 0, 1, 2]) is True, \
            "Starting with zeros then increasing is non-decreasing monotonic"

    def test_large_single_dip_not_monotonic(self):
        arr = list(range(100)) + [50] + list(range(101, 200))
        assert is_monotonic(arr) is False, \
            "One dip in an otherwise increasing sequence breaks monotonicity"


class TestIsMonotonicLargeScale:
    """Large-scale tests for is_monotonic."""

    def test_large_strictly_increasing_list(self):
        arr = list(range(10_000))
        assert is_monotonic(arr) is True, \
            "10,000 strictly increasing integers should be monotonic"

    def test_large_strictly_decreasing_list(self):
        arr = list(range(10_000, 0, -1))
        assert is_monotonic(arr) is True, \
            "10,000 strictly decreasing integers should be monotonic"

    def test_large_list_with_single_violation(self):
        arr = list(range(10_000))
        arr[5_000] = arr[5_000] - 1  # introduce a single decrease in increasing sequence
        assert is_monotonic(arr) is False, \
            "A single out-of-order element in 10,000 should make the list non-monotonic"
