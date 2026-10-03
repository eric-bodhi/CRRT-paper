"""Small-cell suppression for every count this repo prints or commits.

Plan Part 1.4 and the 2026-10-02 decision in docs/decisions.md: aggregate
results may leave the machine, but only when every cell under
`reporting.small_cell_threshold` is suppressed. A count that small can
describe a handful of identifiable patients. Route every printed or written
count through here so the rule is applied in one place.
"""


def count(v: int, threshold: int) -> str:
    """`v` with thousands separators, or "<threshold" when 0 < v < threshold.

    Zero is shown as zero: an item with no rows identifies nobody, and the
    itemid sweep needs to show that an item is empty.
    """
    return f"<{threshold}" if 0 < v < threshold else f"{v:,}"
