"""Per-event diagnostics, computed at capture time so they are stored, not re-derived.

Split deliberately in two. `quote_diagnostics` applies to any structure,
including the categorical control market. `bracket_geometry` only means anything
on a strike ladder, and returns None otherwise — a 4-outcome combo market has no
spacing, range or tails.

Note the ladder sum is only an *overround* on a partitioned ladder. On a
cumulative ladder the buckets overlap, so the raw sum is not expected to sit near
1 and must not be gated as if it were.
"""

from __future__ import annotations


def quote_diagnostics(markets: list[dict]) -> dict:
    """Price availability and the raw ladder sum, for any structure."""
    priced = [m["mid"] for m in markets if m["mid"] is not None]
    fallback = [m["last_price"] for m in markets if m["mid"] is None and m["last_price"]]

    one_sided: dict[str, int] = {}
    for market in markets:
        if market["one_sided_reason"]:
            one_sided[market["one_sided_reason"]] = one_sided.get(market["one_sided_reason"], 0) + 1

    return {
        "n_markets": len(markets),
        "n_two_sided": sum(1 for m in markets if m["two_sided"]),
        "n_no_two_sided_quote": sum(1 for m in markets if not m["two_sided"]),
        "one_sided_reasons": one_sided or None,
        "strike_types": sorted({m["strike_type"] for m in markets if m["strike_type"]}),
        # Raw sum before renormalizing, per the overround diagnostic in the spec.
        "ladder_sum_mid_cents": round(sum(priced), 2) if priced else None,
        "ladder_sum_with_last_fallback_cents": (
            round(sum(priced) + sum(fallback), 2) if priced or fallback else None
        ),
        "n_priced_by_mid": len(priced),
        "n_priced_by_last_fallback": len(fallback),
        "total_open_interest": round(
            sum(m["open_interest"] or 0 for m in markets), 2
        ),
    }


def bracket_geometry(markets: list[dict]) -> dict | None:
    """Strike range, bucket spacing and tail presence. None for categorical ladders."""
    interior = sorted(
        (m for m in markets if m["strike_role"] == "interior"),
        key=lambda m: m["floor_strike"],
    )
    if not interior:
        return None

    floors = [m["floor_strike"] for m in interior]
    # Spacing between consecutive floors is the effective bucket width, which is
    # not cap - floor: the daily approval ladder is point masses (floor == cap)
    # spaced 0.1pp apart.
    spacings = [round(b - a, 6) for a, b in zip(floors, floors[1:])]
    modal_spacing = min(spacings) if spacings else None

    # Tails are not reliably flagged by strike_type. The approval ladders express
    # them as open-ended buckets; the seat ladders express them as bounded
    # intervals against domain limits (Below 45 = [0, 44]). Either way the tell is
    # a bucket far wider than the modal one, and for fitting both are censored
    # intervals rather than point masses at the edge.
    wide = []
    if modal_spacing:
        wide = [
            {
                "ticker": m["ticker"],
                "yes_sub_title": m["yes_sub_title"],
                "width": m["bucket_width"],
            }
            for m in interior
            if m["bucket_width"] is not None and m["bucket_width"] > 2 * modal_spacing
        ]

    return {
        "n_interior": len(interior),
        "strike_range": [floors[0], interior[-1]["cap_strike"]],
        "spacing_min": min(spacings) if spacings else None,
        "spacing_max": max(spacings) if spacings else None,
        "spacing_uniform": len(set(spacings)) == 1 if spacings else None,
        "modal_spacing": modal_spacing,
        "all_point_masses": all(m["point_mass"] for m in interior),
        "has_open_lower": any(m["strike_role"] == "open_lower" for m in markets),
        "has_open_upper": any(m["strike_role"] == "open_upper" for m in markets),
        # Bounded buckets acting as tails; empty when the tails are genuinely open.
        "wide_buckets": wide or None,
        "n_effective_tails": (
            sum(1 for m in markets if m["strike_role"] in ("open_lower", "open_upper"))
            + len(wide)
        ),
    }


def event_diagnostics(markets: list[dict], classification: dict) -> dict:
    """Everything stored per event: structure, quotes, and geometry when it applies."""
    return {
        "structure": classification["structure"],
        "fittable": classification["fittable"],
        "structure_reasons": classification["reasons"],
        "quotes": quote_diagnostics(markets),
        "geometry": bracket_geometry(markets),
    }
