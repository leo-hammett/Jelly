"""
Comprehensive tests for list_utils module.
Tests are written against the specification, not any specific implementation.

Functions under test:
  - has_close_elements(numbers: list[float], threshold: float) -> bool
  - is_monotonic(arr: list[int]) -> bool
"""

import pytest
from list_utils import has_close_elements, is_monotonic


# =============================================================================
# FR-1: has_close_elements
# =============================================================================

class TestHasCloseElementsBasic:
    """Basic functionality tests for has_close_elements (FR-1)."""

    def test_no_close_elements_evenly_spaced(self):
        """Elements spaced wider than threshold should return False."""
        result = has_close_elements([1.0, 2.0, 3.0], 0.5)
        assert result is False, (
            "Elements [1.0, 2.0, 3.0] are all 1.0 apart; "
            "threshold 0.5 should yield False"
        )

    def test_close_elements_present(self):
        """List with at least one pair closer than threshold should return True."""
        result = has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
        assert result is True, (
            "2.8 and 3.0 are 0.2 apart, which is less than threshold 0.3; "
            "should return True"
        )

    def test_exactly_one_close_pair_among_many(self):
        """Should detect a single close pair regardless of list length."""
        result = has_close_elements([10.0, 20.0, 30.0, 30.05, 50.0], 0.1)
        assert result is True, (
            "30.0 and 30.05 are 0.05 apart (< 0.1 threshold); "
            "should return True"
        )

    def test_all_elements_far_apart(self):
        """All pairs wider than threshold should return False."""
        result = has_close_elements([0.0, 100.0, 200.0, 300.0], 50.0)
        assert result is False, (
            "All adjacent elements are 100.0 apart; "
            "threshold 50.0 should yield False"
        )

    def test_negative_numbers_no_close_pair(self):
        """Negative numbers spaced wider than threshold should return False."""
        result = has_close_elements([-10.0, -5.0, 0.0, 5.0], 4.9)
        assert result is False, (
            "All pairs are 5.0 apart; threshold 4.9 should yield False"
        )

    def test_negative_numbers_with_close_pair(self):
        """Negative numbers with a close pair should return True."""
        result = has_close_elements([-3.0, -2.95, 0.0, 5.0], 0.1)
        assert result is True, (
            "-3.0 and -2.95 differ by 0.05 (< 0.1 threshold); "
            "should return True"
        )

    def test_mixed_sign_numbers_close_across_zero(self):
        """Numbers close across zero should be detected."""
        result = has_close_elements([-0.1, 0.1], 0.3)
        assert result is True, (
            "-0.1 and 0.1 differ by 0.2 (< 0.3 threshold); "
            "should return True"
        )


class TestHasCloseElementsEdgeCases:
    """Edge case tests for has_close_elements (FR-1)."""

    def test_empty_list_returns_false(self):
        """Empty list must return False per spec."""
        result = has_close_elements([], 1.0)
        assert result is False, "Empty list should return False per FR-1 spec"

    def test_single_element_returns_false(self):
        """Single-element list must return False per spec (no pair exists)."""
        result = has_close_elements([42.0], 0.5)
        assert result is False, (
            "Single-element list has no pair to compare; "
            "should return False per FR-1 spec"
        )

    def test_zero_threshold_no_duplicates(self):
        """Zero threshold with distinct elements should return False."""
        result = has_close_elements([1.0, 2.0, 3.0], 0.0)
        assert result is False, (
            "No two elements are strictly closer than 0; "
            "should return False with zero threshold and distinct values"
        )

    def test_zero_threshold_with_duplicate_elements(self):
        """Zero threshold with duplicate values — distance is 0, not < 0."""
        # Per spec: closer THAN threshold (strict inequality implied by example)
        # Two identical elements have distance 0; 0 < 0 is False
        result = has_close_elements([1.0, 1.0, 2.0], 0.0)
        assert result is False, (
            "Identical elements have distance 0; "
            "0 is not strictly less than threshold 0, should return False"
        )

    def test_duplicate_elements_above_zero_threshold(self):
        """Identical elements with positive threshold should return True."""
        result = has_close_elements([5.0, 5.0], 0.001)
        assert result is True, (
            "Two identical elements have distance 0 (< 0.001 threshold); "
            "should return True"
        )

    def test_all_identical_elements(self):
        """All-identical list with positive threshold should return True."""
        result = has_close_elements([7.0, 7.0, 7.0, 7.0], 0.5)
        assert result is True, (
            "All elements are identical (distance 0 < 0.5 threshold); "
            "should return True"
        )

    def test_two_elements_exactly_at_threshold(self):
        """Two elements exactly at the threshold distance — boundary check."""
        result = has_close_elements([1.0, 1.5], 0.5)
        # distance == threshold → NOT closer than threshold (strict)
        assert result is False, (
            "Elements exactly at threshold distance (0.5) are not "
            "CLOSER THAN threshold 0.5; should return False"
        )

    def test_two_elements_just_below_threshold(self):
        """Two elements just under the threshold should return True."""
        result = has_close_elements([1.0, 1.4999], 0.5)
        assert result is True, (
            "Elements 0.4999 apart are closer than threshold 0.5; "
            "should return True"
        )

    def test_two_elements_just_above_threshold(self):
        """Two elements just over the threshold should return False."""
        result = has_close_elements([1.0, 1.5001], 0.5)
        assert result is False, (
            "Elements 0.5001 apart are not closer than threshold 0.5; "
            "should return False"
        )

    def test_non_adjacent_pair_is_closest(self):
        """Closest pair need not be adjacent in the list."""
        result = has_close_elements([1.0, 10.0, 1.05, 20.0], 0.1)
        assert result is True, (
            "1.0 and 1.05 are 0.05 apart (< 0.1 threshold) and non-adjacent; "
            "should still return True"
        )

    def test_very_large_threshold(self):
        """Enormous threshold — any two-element list should match."""
        result = has_close_elements([1.0, 1_000_000.0], 1_000_001.0)
        assert result is True, (
            "Distance 999_999 is less than threshold 1_000_001; "
            "should return True"
        )

    def test_very_small_threshold_with_close_floats(self):
        """Very small threshold should still detect sufficiently close values."""
        result = has_close_elements([0.0, 1e-10], 1e-9)
        assert result is True, (
            "1e-10 distance is less than 1e-9 threshold; "
            "should return True"
        )

    def test_negative_threshold_behavior(self):
        """No pair can be 'closer than' a negative threshold; expect False."""
        result = has_close_elements([1.0, 2.0, 3.0], -1.0)
        assert result is False, (
            "No absolute distance is less than a negative threshold; "
            "should return False"
        )


class TestHasCloseElementsLargeScale:
    """Large-scale tests for has_close_elements (FR-1)."""

    def test_large_list_no_close_pair(self):
        """10,000 integers cast to float — no pair is within 0.5."""
        numbers = [float(i) for i in range(10_000)]  # gaps of exactly 1.0
        result = has_close_elements(numbers, 0.5)
        assert result is False, (
            "10,000 elements spaced 1.0 apart; "
            "threshold 0.5 should yield False"
        )

    def test_large_list_with_one_close_pair_at_end(self):
        """10,000 elements with a single close pair hidden at the end."""
        numbers = [float(i * 10) for i in range(9_999)]  # spaced 10 apart
        numbers.append(numbers[-1] + 0.1)               # close pair at end
        result = has_close_elements(numbers, 0.5)
        assert result is True, (
            "10,000-element list with exactly one close pair (0.1 apart) "
            "at the end; threshold 0.5 should yield True"
        )

    def test_large_list_all_identical(self):
        """10,000 identical elements should detect close (distance-0) pair."""
        numbers = [3.14] * 10_000
        result = has_close_elements(numbers, 0.001)
        assert result is True, (
            "10,000 identical elements all have distance 0 (< 0.001); "
            "should return True"
        )


# =============================================================================
# FR-2: is_monotonic
# =============================================================================

class TestIsMonotonicBasic:
    """Basic functionality tests for is_monotonic (FR-2)."""

    def test_strictly_increasing(self):
        """Strictly increasing list should return True."""
        result = is_monotonic([1, 2, 3, 4, 5])
        assert result is True, "[1,2,3,4,5] is strictly increasing; should return True"

    def test_strictly_decreasing(self):
        """Strictly decreasing list should return True."""
        result = is_monotonic([5, 4, 3, 2, 1])
        assert result is True, "[5,4,3,2,1] is strictly decreasing; should return True"

    def test_not_monotonic_mixed(self):
        """List that goes up then down should return False."""
        result = is_monotonic([1, 3, 2, 4])
        assert result is False, "[1,3,2,4] is not monotonic; should return False"

    def test_not_monotonic_down_then_up(self):
        """List that goes down then up should return False."""
        result = is_monotonic([5, 3, 4, 1])
        assert result is False, "[5,3,4,1] is not monotonic; should return False"

    def test_increasing_with_negatives(self):
        """Increasing list with negative values should return True."""
        result = is_monotonic([-5, -3, -1, 0, 2, 4])
        assert result is True, (
            "[-5,-3,-1,0,2,4] is monotonically increasing; should return True"
        )

    def test_decreasing_with_negatives(self):
        """Decreasing list through negative values should return True."""
        result = is_monotonic([10, 5, 0, -5, -10])
        assert result is True, (
            "[10,5,0,-5,-10] is monotonically decreasing; should return True"
        )


class TestIsMonotonicEdgeCases:
    """Edge case tests for is_monotonic (FR-2)."""

    def test_empty_list_is_monotonic(self):
        """Empty list must return True per spec."""
        result = is_monotonic([])
        assert result is True, "Empty list should be considered monotonic per FR-2 spec"

    def test_single_element_is_monotonic(self):
        """Single-element list must return True per spec."""
        result = is_monotonic([42])
        assert result is True, (
            "Single-element list should be considered monotonic per FR-2 spec"
        )

    def test_all_identical_elements_is_monotonic(self):
        """All-equal list is both non-decreasing and non-increasing — monotonic."""
        result = is_monotonic([7, 7, 7, 7, 7])
        assert result is True, (
            "All-identical list [7,7,7,7,7] is monotonic (equal adjacent "
            "elements are allowed per spec); should return True"
        )

    def test_two_equal_elements_is_monotonic(self):
        """Two identical elements should return True."""
        result = is_monotonic([3, 3])
        assert result is True, "[3,3] has equal adjacent elements; should return True"

    def test_increasing_with_equal_adjacent(self):
        """Non-strictly increasing (plateau) should return True."""
        result = is_monotonic([1, 2, 2, 3, 4])
        assert result is True, (
            "[1,2,2,3,4] is non-decreasing with a plateau; should return True"
        )

    def test_decreasing_with_equal_adjacent(self):
        """Non-strictly decreasing (plateau) should return True."""
        result = is_monotonic([5, 4, 4, 3, 1])
        assert result is True, (
            "[5,4,4,3,1] is non-increasing with a plateau; should return True"
        )

    def test_two_elements_increasing(self):
        """Two-element increasing list should return True."""
        result = is_monotonic([1, 2])
        assert result is True, "[1,2] is increasing; should return True"

    def test_two_elements_decreasing(self):
        """Two-element decreasing list should return True."""
        result = is_monotonic([2, 1])
        assert result is True, "[2,1] is decreasing; should return True"

    def test_spike_at_end_breaks_monotonicity(self):
        """Increasing list with a drop at the very end should return False."""
        result = is_monotonic([1, 2, 3, 4, 3])
        assert result is False, (
            "[1,2,3,4,3] has a drop at the end; should return False"
        )

    def test_dip_at_start_breaks_monotonicity(self):
        """Decreasing list with a rise at the very beginning should return False."""
        result = is_monotonic([5, 6, 4, 3, 2])
        assert result is False, (
            "[5,6,4,3,2] rises then falls; should return False"
        )

    def test_large_negative_values(self):
        """Monotonically decreasing list of large negatives."""
        result = is_monotonic([-1, -100, -1000, -10000])
        assert result is True, (
            "[-1,-100,-1000,-10000] is monotonically decreasing; "
            "should return True"
        )

    def test_single_violation_in_long_sequence(self):
        """One out-of-order element in an otherwise increasing list."""
        arr = list(range(1, 101))  # 1..100
        arr[50] = 0                # inject a violation
        result = is_monotonic(arr)
        assert result is False, (
            "One out-of-order element (0 at index 50) breaks monotonicity; "
            "should return False"
        )

    def test_zero_in_sequence(self):
        """Zero within an increasing sequence should not disrupt result."""
        result = is_monotonic([-3, -2, -1, 0, 1, 2])
        assert result is True, (
            "[-3,-2,-1,0,1,2] crosses zero monotonically; should return True"
        )


class TestIsMonotonicLargeScale:
    """Large-scale tests for is_monotonic (FR-2)."""

    def test_large_strictly_increasing_list(self):
        """10,000 strictly increasing integers should return True."""
        arr = list(range(10_000))
        result = is_monotonic(arr)
        assert result is True, (
            "10,000 strictly increasing integers should return True"
        )

    def test_large_strictly_decreasing_list(self):
        """10,000 strictly decreasing integers should return True."""
        arr = list(range(10_000, 0, -1))
        result = is_monotonic(arr)
        assert result is True, (
            "10,000 strictly decreasing integers should return True"
        )

    def test_large_all_equal_list(self):
        """10,000 identical integers should return True."""
        arr = [42] * 10_000
        result = is_monotonic(arr)
        assert result is True, (
            "10,000 identical elements are monotonic (equal adjacents allowed); "
            "should return True"
        )

    def test_large_list_with_single_violation_at_midpoint(self):
        """10,000 increasing integers with one violation at the midpoint."""
        arr = list(range(10_000))
        arr[5_000] = arr[4_999]  # duplicate causes then-decrease
        arr[5_001] = arr[4_999] - 1  # forces a decrease
        result = is_monotonic(arr)
        assert result is False, (
            "10,000-element increasing list with a mid-point decrease "
            "should return False"
        )
