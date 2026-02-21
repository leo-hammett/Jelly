def has_close_elements(numbers: list[float], threshold: float) -> bool:
    """Check if any two numbers in the list are closer than the threshold."""
    if len(numbers) < 2:
        return False

    sorted_numbers = sorted(numbers)
    return any(
        sorted_numbers[i + 1] - sorted_numbers[i] < threshold
        for i in range(len(sorted_numbers) - 1)
    )


def is_monotonic(arr: list[int]) -> bool:
    """Check if array is monotonically increasing or decreasing."""
    if len(arr) <= 1:
        return True

    return (
        all(arr[i] <= arr[i + 1] for i in range(len(arr) - 1))
        or all(arr[i] >= arr[i + 1] for i in range(len(arr) - 1))
    )
