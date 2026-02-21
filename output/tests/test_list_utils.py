"""
Comprehensive tests for list_utils module.
Tests are written against the specification (FR-1 and FR-2),
not any particular implementation.
"""

import pytest
from list_utils import has_close_elements, is_monotonic


# ===========================================================================
# FR-1: has_close_elements
# ===========================================================================

class TestHasCloseElementsBasicFunctionality:
    """Happy-path tests for has_close_elements (FR-1)."""

    def test_no_close_elements_returns_false(self):
        result = has_close_elements([1.0, 2.0, 3.0], 0.5)
        assert result is False, (
            "Elements spaced 1.0 apart with threshold 0.5 should return False"
        )

    def test_close_elements_present_returns_true(self):
        result = has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
        assert result is True, (
            "2.8 and 3.0 are 0.2 apart, which is less than threshold 0.3 — should return True"
        )

    def test_exactly_two_elements_not_close(self):
        result = has_close_elements([1.0, 5.0], 3.0)
        assert result is False, (
            "1.0 and 5.0 are 4.0 apart, which is greater than threshold 3.0 — should return False"
        )

    def test_exactly_two_elements_close(self):
        result = has_close_elements([1.0, 1.2], 0.5)
        assert result is True, (
            "1.0 and 1.2 are 0.2 apart, which is less than threshold 0.5 — should return True"
        )

    def test_non_adjacent_close_pair_detected(self):
        result = has_close_elements([0.0, 10.0, 20.0, 10.05], 0.1)
        assert result is True, (
            "10.0 and 10.05 are 0.05 apart, which is less than threshold 0.1 — should return True"
        )

    def test_negative_numbers_no_close_pair(self):
        result = has_close_elements([-5.0, -3.0, -1.0], 1.5)
        assert result is False, (
            "Elements spaced 2.0 apart with threshold 1.5 should return False"
        )

    def test_negative_numbers_close_pair(self):
        result = has_close_elements([-1.0, -0.9, -5.0], 0.5)
        assert result is True, (
            "-1.0 and -0.9 are 0.1 apart, which is less than threshold 0.5 — should return True"
        )


class TestHasCloseElementsEdgeCases:
    """Edge-case tests for has_close_elements (FR-1)."""

    def test_empty_list_returns_false(self):
        result = has_close_elements([], 1.0)
        assert result is False, (
            "Spec requires empty list to return False"
        )

    def test_single_element_returns_false(self):
        result = has_close_elements([42.0], 0.0)
        assert result is False, (
            "Spec requires single-element list to return False (no pair to compare)"
        )

    def test_zero_threshold_identical_elements(self):
        result = has_close_elements([1.0, 1.0], 0.0)
        assert result is False, (
            "Distance is 0.0 and threshold is 0.0; spec says *closer than* threshold, "
            "so exactly equal distance should NOT trigger True"
        )

    def test_zero_threshold_distinct_elements(self):
        result = has_close_elements([1.0, 2.0], 0.0)
        assert result is False, (
            "No elements are closer than 0.0 to each other when they differ — should return False"
        )

    def test_all_identical_elements_above_zero_threshold(self):
        result = has_close_elements([3.0, 3.0, 3.0, 3.0], 0.5)
        assert result is True, (
            "Identical elements have distance 0.0 which is less than threshold 0.5 — should return True"
        )

    def test_threshold_greater_than_all_distances_returns_true(self):
        result = has_close_elements([1.0, 2.0, 3.0], 100.0)
        assert result is True, (
            "Threshold 100.0 is larger than any pairwise distance — should return True"
        )

    def test_very_small_threshold_returns_false(self):
        result = has_close_elements([0.0, 1.0, 2.0], 1e-10)
        assert result is False, (
            "Elements spaced 1.0 apart with threshold 1e-10 should return False"
        )

    def test_very_small_difference_detected(self):
        result = has_close_elements([0.0, 1e-9], 1e-8)
        assert result is True, (
            "1e-9 difference is less than 1e-8 threshold — should return True"
        )

    def test_mixed_positive_and_negative(self):
        result = has_close_elements([-0.1, 0.1], 0.3)
        assert result is True, (
            "-0.1 and 0.1 are 0.2 apart, which is less than threshold 0.3 — should return True"
        )

    def test_unsorted_list_close_pair_at_end(self):
        result = has_close_elements([100.0, 50.0, 25.0, 25.1], 0.2)
        assert result is True, (
            "25.0 and 25.1 are 0.1 apart regardless of order — should return True"
        )

    def test_duplicate_values_large_threshold(self):
        result = has_close_elements([7.7, 7.7], 1.0)
        assert result is True, (
            "Two identical values have distance 0.0 which is less than threshold 1.0"
        )

    def test_boundary_distance_equals_threshold_returns_false(self):
        result = has_close_elements([0.0, 1.0], 1.0)
        assert result is False, (
            "Distance exactly equals threshold; spec uses strict 'closer than', so should return False"
        )


class TestHasCloseElementsLargeScale:
    """Large-scale tests for has_close_elements (FR-1)."""

    def test_large_list_no_close_pair(self):
        # Integers cast to float, each 1.0 apart — nothing is closer than 0.5
        numbers = [float(i) for i in range(10_000)]
        result = has_close_elements(numbers, 0.5)
        assert result is False, (
            "10,000 elements each 1.0 apart with threshold 0.5 should return False"
        )

    def test_large_list_with_close_pair_at_end(self):
        # All elements far apart, but last two are very close
        numbers = [float(i * 10) for i in range(9_999)] + [99_990.0, 99_990.0001]
        result = has_close_elements(numbers, 0.001)
        assert result is True, (
            "10,000 elements where the final pair is 0.0001 apart with threshold 0.001 — "
            "should return True"
        )

    def test_large_list_all_identical(self):
        numbers = [5.5] * 10_000
        result = has_close_elements(numbers, 0.1)
        assert result is True, (
            "10,000 identical elements all have distance 0.0, which is less than 0.1"
        )


# ===========================================================================
# FR-2: is_monotonic
# ===========================================================================

class TestIsMonotonicBasicFunctionality:
    """Happy-path tests for is_monotonic (FR-2)."""

    def test_strictly_increasing_is_monotonic(self):
        result = is_monotonic([1, 2, 3, 4, 5])
        assert result is True, (
            "Strictly increasing sequence should be monotonic"
        )

    def test_strictly_decreasing_is_monotonic(self):
        result = is_monotonic([5, 4, 3, 2, 1])
        assert result is True, (
            "Strictly decreasing sequence should be monotonic"
        )

    def test_non_monotonic_returns_false(self):
        result = is_monotonic([1, 3, 2, 4])
        assert result is False, (
            "[1, 3, 2, 4] increases then decreases — should return False"
        )

    def test_non_monotonic_valley_shape(self):
        result = is_monotonic([5, 1, 5])
        assert result is False, (
            "V-shaped sequence is neither monotonically increasing nor decreasing"
        )

    def test_two_element_increasing(self):
        result = is_monotonic([1, 2])
        assert result is True, (
            "Two elements in increasing order are monotonically increasing"
        )

    def test_two_element_decreasing(self):
        result = is_monotonic([2, 1])
        assert result is True, (
            "Two elements in decreasing order are monotonically decreasing"
        )


class TestIsMonotonicEdgeCases:
    """Edge-case tests for is_monotonic (FR-2)."""

    def test_empty_list_is_monotonic(self):
        result = is_monotonic([])
        assert result is True, (
            "Spec requires empty list to be considered monotonic"
        )

    def test_single_element_is_monotonic(self):
        result = is_monotonic([42])
        assert result is True, (
            "Spec requires single-element list to be considered monotonic"
        )

    def test_all_equal_elements_is_monotonic(self):
        result = is_monotonic([7, 7, 7, 7])
        assert result is True, (
            "Spec explicitly allows equal adjacent elements — all-equal is monotonic"
        )

    def test_non_decreasing_with_equal_adjacent(self):
        result = is_monotonic([1, 2, 2, 3])
        assert result is True, (
            "Non-strictly increasing with equal adjacent elements should be monotonic"
        )

    def test_non_increasing_with_equal_adjacent(self):
        result = is_monotonic([3, 2, 2, 1])
        assert result is True, (
            "Non-strictly decreasing with equal adjacent elements should be monotonic"
        )

    def test_plateau_then_decrease_is_monotonic(self):
        result = is_monotonic([5, 5, 3, 1])
        assert result is True, (
            "Non-strictly decreasing with leading plateau should be monotonic"
        )

    def test_increase_then_plateau_is_monotonic(self):
        result = is_monotonic([1, 3, 5, 5])
        assert result is True, (
            "Non-strictly increasing with trailing plateau should be monotonic"
        )

    def test_negative_numbers_increasing(self):
        result = is_monotonic([-5, -3, -1, 0, 2])
        assert result is True, (
            "Increasing sequence of negative and non-negative numbers is monotonic"
        )

    def test_negative_numbers_decreasing(self):
        result = is_monotonic([2, 0, -1, -3, -5])
        assert result is True, (
            "Decreasing sequence through negative numbers is monotonic"
        )

    def test_negative_numbers_non_monotonic(self):
        result = is_monotonic([-1, -3, -2])
        assert result is False, (
            "[-1, -3, -2] decreases then increases — should return False"
        )

    def test_single_dip_makes_non_monotonic(self):
        result = is_monotonic([1, 2, 3, 2, 4, 5])
        assert result is False, (
            "A single decrease in an otherwise increasing sequence makes it non-monotonic"
        )

    def test_single_rise_in_decreasing_makes_non_monotonic(self):
        result = is_monotonic([5, 4, 3, 4, 2, 1])
        assert result is False, (
            "A single increase in an otherwise decreasing sequence makes it non-monotonic"
        )

    def test_two_equal_elements_is_monotonic(self):
        result = is_monotonic([3, 3])
        assert result is True, (
            "Two equal elements should be considered monotonic per spec"
        )

    def test_large_negative_to_positive_increasing(self):
        result = is_monotonic([-1_000_000, 0, 1_000_000])
        assert result is True, (
            "Large-range increasing sequence should be monotonic"
        )


class TestIsMonotonicLargeScale:
    """Large-scale tests for is_monotonic (FR-2)."""

    def test_large_strictly_increasing_list(self):
        arr = list(range(10_000))
        result = is_monotonic(arr)
        assert result is True, (
            "10,000-element strictly increasing range should be monotonic"
        )

    def test_large_strictly_decreasing_list(self):
        arr = list(range(10_000, 0, -1))
        result = is_monotonic(arr)
        assert result is True, (
            "10,000-element strictly decreasing range should be monotonic"
        )

    def test_large_non_monotonic_list(self):
        # Build an increasing list, then introduce a dip near the end
        arr = list(range(9_999)) + [9_000]  # final element breaks the trend
        result = is_monotonic(arr)
        assert result is False, (
            "10,000-element list that dips at the very end should not be monotonic"
        )

    def test_large_all_equal_list(self):
        arr = [0] * 10_000
        result = is_monotonic(arr)
        assert result is True, (
            "10,000 identical elements should be considered monotonic per spec"
        )

    def test_large_non_decreasing_list(self):
        # Each value repeats twice: [0,0,1,1,2,2,...,4999,4999]
        arr = [i // 2 for i in range(10_000)]
        result = is_monotonic(arr)
        assert result is True, (
            "10,000-element non-strictly increasing list with duplicates should be monotonic"
        )
