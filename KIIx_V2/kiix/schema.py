"""Market normalization and ladder structure classification.

Two jobs, both at the ingestion boundary:

1. Map Kalshi's live field names onto one canonical schema, so an API rename
   touches this file and nothing else.
2. Classify the ladder's *structure*, because the spec's three incompatible
   strike shapes are not distinguishable from the series name — and, as it turns
   out, not reliably from `strike_type` either. See `classify_ladder`.
"""

from __future__ import annotations

import re

from .convert import as_float, cents

SCHEMA_VERSION = 2

# strike_type is NOT a reliable structure signal, so it is used only to catch the
# one shape that can never be fitted. Everything else is classified from the
# strike geometry by `strike_role` below.
#
# Why: the approval series label their ladders between/less/greater, while the
# seat series label an identical partition "custom" and express the tails as
# bounded intervals against domain limits (Below 45 = floor 0, cap 44; Above 52 =
# floor 53, cap 100). Same structure, different label. Trusting the label
# rejected a fittable ladder.
BARRIER_STRIKE_TYPES = frozenset({"touch"})

# strike_types whose geometry we have seen and understood. An unfamiliar label on
# an otherwise well-formed ladder is worth a warning, not a rejection.
KNOWN_STRIKE_TYPES = frozenset(
    {"between", "less", "less_or_equal", "greater", "greater_or_equal", "custom"}
)

# Only these ladder structures may be fitted. Everything else excludes the
# series and alerts; nothing defaults to the partitioned path.
FITTABLE_STRUCTURES = frozenset({"partitioned", "categorical"})


_RANGE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(-?\d+(?:\.\d+)?)$", re.I)
_ABOVE = re.compile(r"^(?:above|over|more than|greater than)\s+(-?\d+(?:\.\d+)?)$", re.I)
_BELOW = re.compile(r"^(?:below|under|less than|fewer than)\s+(-?\d+(?:\.\d+)?)$", re.I)
_AT_LEAST = re.compile(r"^at\s+least\s+(-?\d+(?:\.\d+)?)$", re.I)
_AT_MOST = re.compile(r"^at\s+most\s+(-?\d+(?:\.\d+)?)$", re.I)
_EXACT = re.compile(r"^(-?\d+(?:\.\d+)?)\s*%?$")


def parse_strike_text(text: str) -> tuple[float | None, float | None] | None:
    """Parse a displayed bucket label into (floor, cap). None if not numeric.

    Needed because the House seat ladders carry no numeric strikes at all: the
    range exists only as a string under custom_strike ({"Seats": "233-237"}).
    Parsing a display string is fragile by nature, so every market records which
    source its strikes came from and the snapshot warns when parsing was used.

    "Above N" / "Below N" become open-ended on an integer domain (Above 237 ->
    floor 238), matching how the API itself renders the Senate tails.
    """
    text = (text or "").strip()
    if not text:
        return None

    if m := _RANGE.match(text):
        return float(m.group(1)), float(m.group(2))
    if m := _EXACT.match(text):
        value = float(m.group(1))
        return value, value
    # "at least" / "at most" are cumulative markers; parsed so the ladder-level
    # classifier sees several open tails on one side and calls it cumulative.
    if m := _AT_LEAST.match(text):
        return float(m.group(1)), None
    if m := _AT_MOST.match(text):
        return None, float(m.group(1))
    if m := _ABOVE.match(text):
        value = float(m.group(1))
        return (value + 1 if value.is_integer() else value), None
    if m := _BELOW.match(text):
        value = float(m.group(1))
        return None, (value - 1 if value.is_integer() else value)
    return None


def derive_strikes(raw: dict) -> tuple[float | None, float | None, str]:
    """Resolve a market's strikes and say where they came from.

    Precedence is deliberate: the API's numeric fields always win. custom_strike
    is only self-describing on some series — for the Senate ladder "Below 45"
    carries custom_strike {"Seats": "45"}, which is the reference point, not the
    range — so it is a fallback used only when floor and cap are both absent.
    """
    floor_strike, cap_strike = raw.get("floor_strike"), raw.get("cap_strike")
    if floor_strike is not None or cap_strike is not None:
        return floor_strike, cap_strike, "api"

    # custom_strike is not consistent within a single ladder: KXDHOUSESEATS gives
    # the range on interior buckets ({"Seats": "214-217"}) but a bare reference
    # point on the tails ({"Seats": "210"} for "Below 210"), and KXRHOUSESEATS
    # gives the full label on both. Parsing a bare point where the bucket is
    # actually a tail invents an overlap and misclassifies the ladder as
    # cumulative, so score the candidates and take the most informative parse.
    candidates: list[tuple[int, tuple[float | None, float | None], str]] = []
    custom = raw.get("custom_strike")
    if isinstance(custom, dict) and len(custom) == 1:
        (value,) = custom.values()
        if parsed := parse_strike_text(str(value)):
            candidates.append((_informativeness(parsed), parsed, "custom_strike"))
    if parsed := parse_strike_text(raw.get("yes_sub_title") or ""):
        candidates.append((_informativeness(parsed), parsed, "subtitle"))

    if not candidates:
        return None, None, "none"
    _, (floor_strike, cap_strike), source = max(candidates, key=lambda c: c[0])
    return floor_strike, cap_strike, source


def _informativeness(parsed: tuple[float | None, float | None]) -> int:
    """Rank a parse: open-ended or a real range beats a bare point."""
    floor_strike, cap_strike = parsed
    if floor_strike is None or cap_strike is None:
        return 2  # open-ended: unambiguously a tail
    if floor_strike != cap_strike:
        return 2  # a genuine range
    return 1  # a point, which may be a reference value rather than the bucket


def strike_role(floor_strike, cap_strike, strike_type: str | None) -> str:
    """The market's geometric role in its ladder, read from the strikes themselves.

    barrier         resolves on a level being touched; never fittable
    outcome         no strikes at all — a categorical leg
    open_lower      bounded above only
    open_upper      bounded below only
    interior        bounded both sides (a point mass when floor == cap)
    """
    if strike_type in BARRIER_STRIKE_TYPES:
        return "barrier"
    if floor_strike is None and cap_strike is None:
        return "outcome"
    if floor_strike is None:
        return "open_lower"
    if cap_strike is None:
        return "open_upper"
    return "interior"


def normalize_market(
    raw: dict, series_ticker: str, captured_at: str, keep_raw: bool = False
) -> dict:
    """Map one raw market payload onto the canonical capture schema.

    The API exposes prices as *_dollars strings and sizes/volumes as *_fp
    strings; the spec's original field list (yes_bid, volume, open_interest)
    predates that rename, so the mapping is explicit here rather than at fit time.
    """
    yes_bid = cents(raw.get("yes_bid_dollars"))
    yes_ask = cents(raw.get("yes_ask_dollars"))
    floor_strike, cap_strike, strike_source = derive_strikes(raw)
    strike_type = raw.get("strike_type")

    # A side is "absent" when Kalshi fills it with the boundary (0 or 100).
    # The None checks are load-bearing, not redundant with the comparisons:
    # `0 < None` raises TypeError.
    if yes_bid is None or yes_ask is None:
        two_sided, reason = False, "missing_field"
    elif yes_bid == 0:
        two_sided, reason = False, "no_bid"
    elif yes_ask >= 100:
        two_sided, reason = False, "no_ask"
    elif yes_bid > yes_ask:
        two_sided, reason = False, "crossed_book"
    else:
        two_sided, reason = True, None

    row = {
        "ticker": raw.get("ticker"),
        "event_ticker": raw.get("event_ticker"),
        "series_ticker": series_ticker,
        "captured_at": captured_at,
        "status": raw.get("status"),
        "yes_sub_title": raw.get("yes_sub_title"),
        # prices, integer cents
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": cents(raw.get("no_bid_dollars")),
        "no_ask": cents(raw.get("no_ask_dollars")),
        "last_price": cents(raw.get("last_price_dollars")),
        "previous_price": cents(raw.get("previous_price_dollars")),
        "mid": (yes_bid + yes_ask) / 2 if two_sided else None,
        "two_sided": two_sided,
        # Recorded so we learn which edge actually fires on thin tail buckets
        # rather than guessing. The tails are where these ladders break.
        "one_sided_reason": reason,
        # size / activity
        "yes_bid_size": as_float(raw.get("yes_bid_size_fp")),
        "yes_ask_size": as_float(raw.get("yes_ask_size_fp")),
        "volume": as_float(raw.get("volume_fp")),
        "volume_24h": as_float(raw.get("volume_24h_fp")),
        "open_interest": as_float(raw.get("open_interest_fp")),
        "liquidity": as_float(raw.get("liquidity_dollars")),
        # structure
        "floor_strike": floor_strike,
        "cap_strike": cap_strike,
        "strike_type": strike_type,
        "strike_role": strike_role(floor_strike, cap_strike, strike_type),
        # The seat series carry the strike again under a domain-named key
        # ({"Seats": "45"}); kept because it names the unit.
        "custom_strike": raw.get("custom_strike"),
        # api | custom_strike | subtitle | none. Anything but "api" means the
        # strikes were parsed from a display string and a format change there
        # would silently reshape the ladder.
        "strike_source": strike_source,
        "has_strikes": floor_strike is not None or cap_strike is not None,
        "point_mass": floor_strike is not None and floor_strike == cap_strike,
        "bucket_width": (
            round(cap_strike - floor_strike, 6)
            if floor_strike is not None and cap_strike is not None
            else None
        ),
        "market_type": raw.get("market_type"),
        # timing. updated_time is book activity, not trade time: true trade age
        # for the staleness gate needs the /trades endpoint.
        "open_time": raw.get("open_time"),
        "close_time": raw.get("close_time"),
        "expiration_time": raw.get("expiration_time"),
        "updated_time": raw.get("updated_time"),
        "settlement_timer_seconds": raw.get("settlement_timer_seconds"),
    }
    if keep_raw:
        row["raw"] = raw
    return row


def classify_ladder(markets: list[dict]) -> dict:
    """Classify one event's ladder structurally, and say why.

    `strike_type` alone cannot separate the spec's partitioned and cumulative
    shapes. A single open-ended `greater` bucket is the upper tail of a
    partition; a whole ladder of `greater_or_equal` buckets is a survival
    function that must be differenced first. Same strike_type, opposite handling.

    The structural tell is the count: a partition has at most one tail per side.
    Overlapping interior intervals are the second tell.

    Returns {"structure", "fittable", "reasons"} where structure is one of
    partitioned / cumulative / categorical / barrier / unknown.
    """
    def result(structure: str, fittable: bool, reasons: list[str]) -> dict:
        labels = sorted({m["strike_type"] for m in markets if m["strike_type"]})
        unfamiliar = sorted(set(labels) - KNOWN_STRIKE_TYPES - BARRIER_STRIKE_TYPES)
        return {
            "structure": structure,
            "fittable": fittable,
            "reasons": reasons,
            "strike_types": labels,
            # An unfamiliar label on a well-formed ladder is worth seeing, but the
            # geometry decides. Rejecting on the label alone is what wrongly
            # excluded the seat ladders.
            "unfamiliar_strike_types": unfamiliar or None,
            "strike_sources": sorted({m["strike_source"] for m in markets}),
        }

    if not markets:
        return result("unknown", False, ["no markets"])

    roles = [m["strike_role"] for m in markets]

    if "barrier" in roles:
        return result(
            "barrier", False, ["barrier/touch market present; prices a running extremum"]
        )

    n_outcome = roles.count("outcome")
    if n_outcome == len(markets):
        return result("categorical", True, [f"no strikes on any of {len(markets)} outcomes"])
    if n_outcome:
        return result(
            "unknown",
            False,
            [f"{n_outcome} of {len(markets)} markets carry no strikes; mixed ladder"],
        )

    n_lower = roles.count("open_lower")
    n_upper = roles.count("open_upper")
    if n_lower > 1 or n_upper > 1:
        return result(
            "cumulative",
            False,
            [
                f"{n_lower} open-lower and {n_upper} open-upper buckets; a partition "
                "has at most one per side, so this reads as a survival function and "
                "must be differenced before fitting"
            ],
        )

    # Overlap is the second tell for a cumulative ladder, and the one that still
    # works when the tails are expressed as bounded domain intervals.
    bounded = sorted(
        (m for m in markets if m["floor_strike"] is not None and m["cap_strike"] is not None),
        key=lambda m: (m["floor_strike"], m["cap_strike"]),
    )
    overlaps = [
        f"{prev['ticker']} spans [{prev['floor_strike']}, {prev['cap_strike']}] but "
        f"{nxt['ticker']} floors at {nxt['floor_strike']}"
        for prev, nxt in zip(bounded, bounded[1:])
        if nxt["floor_strike"] <= prev["cap_strike"]
    ]
    if overlaps:
        return result("cumulative", False, overlaps)

    return result(
        "partitioned",
        True,
        [
            f"{len(bounded)} disjoint bounded buckets, {n_lower} open-lower, "
            f"{n_upper} open-upper"
        ],
    )
