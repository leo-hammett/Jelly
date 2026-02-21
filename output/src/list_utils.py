def has_close_elements(numbers: list[float], threshold: float) -> bool:
    """Check if any two numbers in the list are closer than the threshold.

    Args:
        numbers: A list of floating-point numbers to check.
        threshold: The distance threshold (exclusive) to compare against.

    Returns:
        True if any two distinct elements in the list have an absolute
        difference strictly less than the threshold, False otherwise.

    Examples:
        >>> has_close_elements([1.0, 2.0, 3.0], 0.5)
        False
        >>> has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
        True
        >>> has_close_elements([], 1.0)
        False
        >>> has_close_elements([42.0], 1.0)
        False
    """
    if len(numbers) < 2:
        return False

    # Sort a copy so we only need to compare adjacent elements — O(n log n)
    # rather than the O(n²) brute-force approach, while still being correct
    # because the closest pair in absolute value will always be adjacent after sorting.
    sorted_nums = sorted(numbers)
    for i in range(len(sorted_nums) - 1):
        if abs(sorted_nums[i + 1] - sorted_nums[i]) < threshold:
            return True
    return False


def is_monotonic(arr: list[int]) -> bool:
    """Check if array is monotonically increasing or decreasing.

    An array is considered monotonic if it is entirely non-decreasing
    (monotonically increasing) or entirely non-increasing (monotonically
    decreasing). Equal adjacent elements are allowed in both cases.

    Args:
        arr: A list of integers to check.

    Returns:
        True if the array is monotonically increasing or decreasing,
        False otherwise.

    Examples:
        >>> is_monotonic([1, 2, 2, 3])
        True
        >>> is_monotonic([6, 5, 4, 4])
        True
        >>> is_monotonic([1, 3, 2])
        False
        >>> is_monotonic([])
        True
        >>> is_monotonic([7])
        True
        >>> is_monotonic([5, 5, 5])
        True
    """
    if len(arr) <= 1:
        return True

    # Determine the direction from the first pair of unequal elements.
    # Then verify all subsequent pairs are consistent with that direction.
    increasing = True
    decreasing = True

    for i in range(len(arr) - 1):
        diff = arr[i + 1] - arr[i]
        if diff > 0:
            decreasing = False
        elif diff < 0:
            increasing = False

        # Early exit: if neither property holds, the array is not monotonic.
        if not increasing and not decreasing:
            return False

    return True
