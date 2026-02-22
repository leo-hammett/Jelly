def has_close_elements(numbers: list[float], threshold: float) -> bool:
    """Check if any two numbers in the list are closer than the threshold.

    Args:
        numbers: List of floats to check.
        threshold: Distance threshold (exclusive).

    Returns:
        True if any two numbers differ by less than threshold, False otherwise.
    """
    if len(numbers) < 2:
        return False

    sorted_numbers = sorted(numbers)
    for i in range(len(sorted_numbers) - 1):
        if abs(sorted_numbers[i + 1] - sorted_numbers[i]) < threshold:
            return True
    return False


def is_monotonic(arr: list[int]) -> bool:
    """Check if array is monotonically increasing or decreasing.

    Equal adjacent elements are permitted in both directions.
    Empty and single-element lists are considered monotonic.

    Args:
        arr: List of integers to check.

    Returns:
        True if the array is monotonically non-decreasing or non-increasing.
    """
    if len(arr) <= 1:
        return True

    increasing = all(arr[i] <= arr[i + 1] for i in range(len(arr) - 1))
    decreasing = all(arr[i] >= arr[i + 1] for i in range(len(arr) - 1))
    return increasing or decreasing
