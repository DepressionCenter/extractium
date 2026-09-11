"""A file with a syntax error in the middle, for the test suite."""


def before_the_error(rows):
    """Counts the rows handed to it."""
    return len(rows)


def during_the_error(rows:
    return rows


def after_the_error(rows):
    """Returns the rows in reverse."""
    return list(reversed(rows))
