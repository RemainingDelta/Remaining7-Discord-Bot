"""Tests for evaluate_count in features/counting.py."""

import pytest

from features.counting import evaluate_count


# --- Plain numbers (backward compatible) ---


@pytest.mark.parametrize(
    "content,expected",
    [
        ("70", 70),
        ("0", 0),
        (" 42 ", 42),
    ],
)
def test_plain_numbers(content, expected):
    assert evaluate_count(content) == expected


# --- Arithmetic expressions ---


@pytest.mark.parametrize(
    "content,expected",
    [
        ("6+9", 15),
        ("7*10", 70),
        ("(2+3)*4", 20),
        ("100/2", 50),
        ("-5+75", 70),
        ("7 * 10", 70),
        ("100-30", 70),
    ],
)
def test_valid_expressions(content, expected):
    assert evaluate_count(content) == expected


# --- Rejected input ---


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "hello",
        "142!",
        "70 nice",
        "7/2",  # non-whole result
        "2**6",  # exponent not allowed
        "10%3",  # modulo not allowed
        "1/0",  # division by zero
        "__import__('os')",
        "True",
    ],
)
def test_rejected_input(content):
    assert evaluate_count(content) is None
