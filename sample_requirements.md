# Project: List Utilities

## Overview
Python utility functions for list manipulation.

## Functional Requirements

### FR-1: Find Closest Pair
Given a list of floats and a threshold, determine if any two numbers are closer than the threshold.

- Input: `numbers: list[float]`, `threshold: float`
- Output: `bool`
- Constraints: Empty lists return False. Single-element lists return False.
- Example:
  ```python
  has_close_elements([1.0, 2.0, 3.0], 0.5)  # False
  has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)  # True
  ```

### FR-2: Monotonic Check
Check if an array is monotonically increasing or decreasing.

- Input: `arr: list[int]`
- Output: `bool`
- Constraints: Empty and single-element lists are monotonic. Equal adjacent elements are allowed.

## API Specification
```python
def has_close_elements(numbers: list[float], threshold: float) -> bool:
    """Check if any two numbers in the list are closer than the threshold."""
    ...

def is_monotonic(arr: list[int]) -> bool:
    """Check if array is monotonically increasing or decreasing."""
    ...
```

## Edge Cases
- Empty lists
- Single-element lists
- All identical elements
- Very large lists (10,000+ elements)
- Negative numbers
- Zero threshold
