"""The version and thresholds of the layered film's visibility evidence."""

VISIBILITY_CHECK = "layered.visibility"
VISIBILITY_OUTPUT = "visibility"
VISIBILITY_VERSION = "1"

ALPHA_FLOOR = 128  # Count pixels where the subject supplies at least half the opacity.
HIDDEN_MAX_PERCENT = 50  # Losing half or more of the unoccluded subject blocks delivery.
VISIBLE_MIN_PERCENT = 85  # Allow minor overlap. The middle band goes to person review.

THRESHOLDS = {
    "alpha_floor": ALPHA_FLOOR,
    "hidden_max_percent": HIDDEN_MAX_PERCENT,
    "visible_min_percent": VISIBLE_MIN_PERCENT,
}


def verdict(support: int, lower: int, upper: int) -> str:
    if support == 0:  # There is no subject support on which to base a fraction.
        return "uncertain"
    if 100 * upper <= HIDDEN_MAX_PERCENT * support:
        return "hidden"
    if 100 * lower >= VISIBLE_MIN_PERCENT * support:
        return "visible"
    return "uncertain"
