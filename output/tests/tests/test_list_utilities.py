import pytest
from list_utilities import has_close_elements, is_monotonic


class TestHasCloseElementsBasic:
    def test_no_close_elements_returns_false(self):
        """Numbers spaced further apart than threshold should return False."""
        result = has_close_elements([1.0, 2.0, 3.0], 0.5)
        assert result == False, f"Expected False when no elements are within threshold, got {result}"

    def test_close_elements_returns_true(self):
        """Numbers closer than threshold should return True."""
        result = has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
        assert result == True, f"Expected True when two elements are within threshold, got {result}"

    def test_two_close_elements(self):
        """Two elements closer than threshold should return True."""
        result = has_close_elements([1.0, 1.1], 0.5)
        assert result == True, f"Expected True for two elements within threshold, got {result}"

    def test_two_far_elements(self):
        """Two elements farther apart than threshold should return False."""
        result = has_close_elements([1.0, 5.0], 0.5)
        assert result == False, f"Expected False for two elements outside threshold, got {result}"

    def test_exactly_at_threshold_boundary(self):
        """Elements exactly at the threshold distance should return False (closer than, not equal)."""
        result = has_close_elements([1.0, 1.5], 0.5)
        assert result == False, f"Expected False when distance equals threshold (not closer than), got {result}"

    def test_negative_numbers_close_together(self):
        """Negative numbers closer than threshold should return True."""
        result = has_close_elements([-1.0, -1.05, -5.0], 0.1)
        assert result == True, f"Expected True for close negative numbers, got {result}"

    def test_mixed_positive_negative_close(self):
        """A positive and negative number close together should return True."""
        result = has_close_elements([-0.1, 0.1], 0.3)
        assert result == True, f"Expected True for mixed-sign numbers within threshold, got {result}"


class TestHasCloseElementsEdgeCases:
    def test_empty_list_returns_false(self):
        """Empty list must return False per spec."""
        result = has_close_elements([], 0.5)
        assert result == False, f"Expected False for empty list, got {result}"

    def test_single_element_returns_false(self):
        """Single-element list must return False per spec."""
        result = has_close_elements([42.0], 0.5)
        assert result == False, f"Expected False for single-element list, got {result}"

    def test_zero_threshold_no_duplicates(self):
        """With zero threshold, distinct elements should return False (none are closer than 0)."""
        result = has_close_elements([1.0, 2.0, 3.0], 0.0)
        assert result == False, f"Expected False with zero threshold and no duplicates, got {result}"

    def test_zero_threshold_with_duplicates(self):
        """With zero threshold, duplicate elements have distance 0, not closer than 0."""
        result = has_close_elements([1.0, 1.0, 3.0], 0.0)
        assert result == False, f"Expected False with zero threshold even for duplicates (0 is not < 0), got {result}"

    def test_identical_elements_positive_threshold(self):
        """All identical elements with positive threshold should return True."""
        result = has_close_elements([5.0, 5.0, 5.0], 0.1)
        assert result == True, f"Expected True for identical elements with positive threshold, got {result}"

    def test_two_identical_elements(self):
        """Two identical elements with positive threshold should return True."""
        result = has_close_elements([3.14, 3.14], 1.0)
        assert result == True, f"Expected True for two identical elements with positive threshold, got {result}"

    def test_very_small_threshold(self):
        """Very small threshold should not trigger on elements with small but larger differences."""
        result = has_close_elements([1.0, 1.001, 2.0], 0.0001)
        assert result == False, f"Expected False when differences exceed very small threshold, got {result}"

    def test_very_small_threshold_with_close_pair(self):
        """Very small threshold triggers when a pair is truly that close."""
        result = has_close_elements([1.0, 1.000001, 2.0], 0.00001)
        assert result == True, f"Expected True when pair is within very small threshold, got {result}"

    def test_large_threshold_always_true(self):
        """Threshold larger than max spread should always return True for 2+ elements."""
        result = has_close_elements([1.0, 1000.0], 10000.0)
        assert result == True, f"Expected True when threshold exceeds all pairwise distances, got {result}"

    def test_negative_numbers_far_apart(self):
        """Negative numbers far apart should return False."""
        result = has_close_elements([-100.0, -200.0, -300.0], 5.0)
        assert result == False, f"Expected False for negative numbers far apart, got {result}"

    def test_close_pair_not_adjacent(self):
        """Close pair that are not adjacent in the list should still be detected."""
        result = has_close_elements([1.0, 10.0, 20.0, 1.05], 0.1)
        assert result == True, f"Expected True when non-adjacent elements are close, got {result}"

    def test_floats_with_precision(self):
        """Should handle floating point values correctly."""
        result = has_close_elements([0.1, 0.2, 0.3], 0.15)
        assert result == True, f"Expected True when 0.1 and 0.2 are within 0.15 of each other, got {result}"


class TestHasCloseElementsLargeScale:
    def test_large_list_no_close_elements(self):
        """10,000 evenly spaced elements with threshold below spacing should return False."""
        numbers = [float(i) for i in range(10_000)]  # spacing of 1.0
        result = has_close_elements(numbers, 0.5)
        assert result == False, f"Expected False for 10,000 evenly-spaced elements with threshold=0.5, got {result}"

    def test_large_list_with_one_close_pair(self):
        """10,000 evenly spaced elements with one close pair injected should return True."""
        numbers = [float(i * 10) for i in range(10_000)]  # spacing of 10.0
        numbers[5000] = numbers[4999] + 0.1  # inject a close pair
        result = has_close_elements(numbers, 1.0)
        assert result == True, f"Expected True when one close pair exists in 10,000 elements, got {result}"

    def test_large_list_all_identical(self):
        """10,000 identical elements should return True for any positive threshold."""
        numbers = [3.14] * 10_000
        result = has_close_elements(numbers, 0.001)
        assert result == True, f"Expected True for 10,000 identical elements with positive threshold, got {result}"


class TestIsMonotonicBasic:
    def test_strictly_increasing(self):
        """Strictly increasing list should return True."""
        result = is_monotonic([1, 2, 3, 4, 5])
        assert result == True, f"Expected True for strictly increasing list, got {result}"

    def test_strictly_decreasing(self):
        """Strictly decreasing list should return True."""
        result = is_monotonic([5, 4, 3, 2, 1])
        assert result == True, f"Expected True for strictly decreasing list, got {result}"

    def test_not_monotonic(self):
        """A list that goes up then down should return False."""
        result = is_monotonic([1, 3, 2, 4])
        assert result == False, f"Expected False for non-monotonic list, got {result}"

    def test_not_monotonic_down_then_up(self):
        """A list that goes down then up should return False."""
        result = is_monotonic([5, 3, 4, 1])
        assert result == False, f"Expected False for list that decreases then increases, got {result}"

    def test_increasing_with_plateau(self):
        """Non-strictly increasing list (with equal adjacent elements) should return True."""
        result = is_monotonic([1, 2, 2, 3])
        assert result == True, f"Expected True for increasing list with equal adjacent elements, got {result}"

    def test_decreasing_with_plateau(self):
        """Non-strictly decreasing list (with equal adjacent elements) should return True."""
        result = is_monotonic([4, 3, 3, 2])
        assert result == True, f"Expected True for decreasing list with equal adjacent elements, got {result}"

    def test_two_element_increasing(self):
        """Two-element increasing list should return True."""
        result = is_monotonic([1, 2])
        assert result == True, f"Expected True for two-element increasing list, got {result}"

    def test_two_element_decreasing(self):
        """Two-element decreasing list should return True."""
        result = is_monotonic([2, 1])
        assert result == True, f"Expected True for two-element decreasing list, got {result}"


class TestIsMonotonicEdgeCases:
    def test_empty_list_is_monotonic(self):
        """Empty list must return True per spec."""
        result = is_monotonic([])
        assert result == True, f"Expected True for empty list, got {result}"

    def test_single_element_is_monotonic(self):
        """Single-element list must return True per spec."""
        result = is_monotonic([42])
        assert result == True, f"Expected True for single-element list, got {result}"

    def test_all_identical_elements(self):
        """All identical elements list should return True (equal adjacent elements allowed)."""
        result = is_monotonic([7, 7, 7, 7, 7])
        assert result == True, f"Expected True for all-identical elements, got {result}"

    def test_two_identical_elements(self):
        """Two identical elements should return True."""
        result = is_monotonic([3, 3])
        assert result == True, f"Expected True for two identical elements, got {result}"

    def test_negative_numbers_increasing(self):
        """Increasing sequence of negative numbers should return True."""
        result = is_monotonic([-5, -4, -3, -2, -1])
        assert result == True, f"Expected True for increasing negative numbers, got {result}"

    def test_negative_numbers_decreasing(self):
        """Decreasing sequence of negative numbers should return True."""
        result = is_monotonic([-1, -2, -3, -4, -5])
        assert result == True, f"Expected True for decreasing negative numbers, got {result}"

    def test_negative_to_positive_increasing(self):
        """Sequence crossing from negative to positive should return True if increasing."""
        result = is_monotonic([-3, -1, 0, 2, 5])
        assert result == True, f"Expected True for increasing sequence crossing zero, got {result}"

    def test_positive_to_negative_decreasing(self):
        """Sequence crossing from positive to negative should return True if decreasing."""
        result = is_monotonic([5, 2, 0, -1, -3])
        assert result == True, f"Expected True for decreasing sequence crossing zero, got {result}"

    def test_last_element_breaks_increase(self):
        """List that is increasing except for the last element should return False."""
        result = is_monotonic([1, 2, 3, 4, 3])
        assert result == False, f"Expected False when last element breaks increasing trend, got {result}"

    def test_last_element_breaks_decrease(self):
        """List that is decreasing except for the last element should return False."""
        result = is_monotonic([5, 4, 3, 2, 3])
        assert result == False, f"Expected False when last element breaks decreasing trend, got {result}"

    def test_first_element_breaks_increase(self):
        """List that has a drop at the start and then increases should return False."""
        result = is_monotonic([3, 1, 2, 3, 4])
        assert result == False, f"Expected False when first transition breaks monotonic increase, got {result}"

    def test_contains_zero(self):
        """Monotonic increasing list containing zero should return True."""
        result = is_monotonic([-2, -1, 0, 1, 2])
        assert result == True, f"Expected True for monotonic list containing zero, got {result}"

    def test_large_jump_still_monotonic(self):
        """Large jump between elements should still be monotonic if direction is consistent."""
        result = is_monotonic([1, 2, 1000000, 1000001])
        assert result == True, f"Expected True for monotonic list with large jumps, got {result}"

    def test_plateau_then_direction_change_not_monotonic(self):
        """Plateau followed by reversal should return False."""
        result = is_monotonic([1, 2, 2, 1])
        assert result == False, f"Expected False for list with plateau then decrease after increase, got {result}"


class TestIsMonotonicLargeScale:
    def test_large_strictly_increasing(self):
        """10,000 strictly increasing integers should return True."""
        arr = list(range(10_000))
        result = is_monotonic(arr)
        assert result == True, f"Expected True for 10,000 strictly increasing integers, got {result}"

    def test_large_strictly_decreasing(self):
        """10,000 strictly decreasing integers should return True."""
        arr = list(range(10_000, 0, -1))
        result = is_monotonic(arr)
        assert result == True, f"Expected True for 10,000 strictly decreasing integers, got {result}"

    def test_large_all_identical(self):
        """10,000 identical integers should return True."""
        arr = [0] * 10_000
        result = is_monotonic(arr)
        assert result == True, f"Expected True for 10,000 identical integers, got {result}"

    def test_large_increasing_with_one_dip(self):
        """10,000 increasing integers with one dip injected should return False."""
        arr = list(range(10_000))
        arr[5000] = arr[5000] - 5  # introduce a dip
        result = is_monotonic(arr)
        assert result == False, f"Expected False for 10,000 increasing integers with one dip, got {result}"

    def test_large_negative_increasing(self):
        """10,000 increasing negative integers should return True."""
        arr = list(range(-10_000, 0))
        result = is_monotonic(arr)
        assert result == True, f"Expected True for 10,000 increasing negative integers, got {result}"
