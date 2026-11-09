"""Compare a generated query's result with the reference result.

Rows are compared as a multiset (order ignored). Numbers are rounded to two
decimal places, and numeric text such as '2021' is treated as the number 2021.

strict   same columns and same rows
lenient  the reference columns appear somewhere in the generated result
         (extra columns allowed), with the same rows
"""

import re
from collections import Counter
from itertools import permutations

_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")
MAX_COLUMNS_FOR_LENIENT = 8


def normalise(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).strip()
    return round(float(text), 2) if _NUMERIC.match(text) else text.casefold()


def _bag(rows, columns=None) -> Counter:
    if columns is None:
        return Counter(tuple(normalise(v) for v in row) for row in rows)
    return Counter(tuple(normalise(row[i]) for i in columns) for row in rows)


def strict_match(reference: list[tuple], predicted: list[tuple]) -> bool:
    return _bag(reference) == _bag(predicted)


def lenient_match(reference: list[tuple], predicted: list[tuple]) -> bool:
    if strict_match(reference, predicted):
        return True
    if not reference or not predicted or len(reference) != len(predicted):
        return False
    n_ref, n_pred = len(reference[0]), len(predicted[0])
    if n_pred < n_ref or n_pred > MAX_COLUMNS_FOR_LENIENT:
        return False
    target = _bag(reference)
    return any(_bag(predicted, cols) == target for cols in permutations(range(n_pred), n_ref))
