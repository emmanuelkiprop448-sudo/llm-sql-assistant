from sql_assistant.compare import lenient_match, strict_match


def test_row_order_is_ignored():
    assert strict_match([("a", 1), ("b", 2)], [("b", 2), ("a", 1)])


def test_float_noise_is_ignored():
    assert strict_match([(2328.6,)], [(2328.6000000000004,)])


def test_numeric_text_matches_number():
    assert strict_match([("2021", 83)], [(2021, 83)])


def test_different_values_fail():
    assert not strict_match([("USA", 13)], [("Canada", 8)])


def test_duplicate_rows_count():
    assert not strict_match([("a",), ("a",)], [("a",)])


def test_extra_columns_pass_lenient_only():
    reference = [("Rock", 826.65)]
    predicted = [(1, "Rock", 826.65)]
    assert not strict_match(reference, predicted)
    assert lenient_match(reference, predicted)


def test_reordered_columns_pass_lenient():
    assert lenient_match([("Jane", "Peacock", 833.04)], [(833.04, "Jane", "Peacock")])


def test_missing_column_fails_lenient():
    assert not lenient_match([("Jane", "Peacock", 833.04)], [("Jane Peacock", 833.04)])
