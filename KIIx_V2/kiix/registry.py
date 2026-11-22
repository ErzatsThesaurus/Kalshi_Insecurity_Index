"""The series registry: the one place that knows which series belong to which sleeve.

The spec forbids hardcoding tickers as a *fetch* list, because political series
churn and a namespace rename already caused a multi-day outage. This registry is
not a fetch list. Every run enumerates the category from the API; these entries
say what each discovered series *means*, and an entry that matches nothing raises
a rename alert rather than silently dropping data.

`expected_structure` is a cross-check, not an instruction. If the live ladder
classifies differently from what is recorded here, that is a structural change on
the exchange and it should alert.

Strike widths marked verified were pulled from the API on 2026-09-26. The rest
are the spec's scrape-derived values and are still UNVERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass

ELECTION_DAY = "2026-11-03"


@dataclass(frozen=True)
class SeriesSpec:
    series_ticker: str
    sleeve: str
    # constituent = feeds the index; gate = ingested for cross-checks only.
    role: str
    tenor: str
    expected_structure: str
    # Distinct from expiration_time: the date uncertainty actually collapses.
    # None means constant-maturity, which takes no time normalization.
    information_horizon: str | None
    # Series covering one underlying that must be fitted jointly.
    stitch_group: str | None = None
    # Which of the series' open events belong to this sleeve. A series can carry
    # several live events on different horizons -- KXDSENATESEATS runs both -27
    # (the midterms) and -29 (the 2028 cycle, illiquid and 129c overround) -- and
    # ingesting both would pollute the fit. None means take every open event.
    event_suffix: str | None = None
    notes: str = ""


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        series_ticker="KXTRUMPAPPROVE",
        sleeve="approval",
        role="constituent",
        tenor="daily",
        expected_structure="partitioned",
        information_horizon=None,
        notes=(
            "Anchor. VERIFIED 2026-09-26: 0.1pp point-mass buckets (floor == cap), "
            "window ~0.7pp wide, both tails open, 7 days/week, settles 13:00 ET."
        ),
    ),
    SeriesSpec(
        series_ticker="KXAPRPOTUS",
        sleeve="approval",
        role="constituent",
        tenor="weekly",
        expected_structure="partitioned",
        information_horizon=None,
        notes=(
            "VERIFIED 2026-09-26: 0.3pp interval buckets, range ~1.7pp, both tails "
            "open, settles 11:00 ET Friday. Deeper distribution than the daily."
        ),
    ),
    SeriesSpec(
        series_ticker="KXDSENATESEATS",
        event_suffix="-27",
        sleeve="midterm",
        role="constituent",
        tenor="single_event",
        expected_structure="partitioned",
        information_horizon=ELECTION_DAY,
        stitch_group="d_senate_seats",
        notes="UNVERIFIED: 1 seat, strikes 45-52. Stitch base.",
    ),
    SeriesSpec(
        series_ticker="KXDSENATESEATSH",
        event_suffix="-27",
        sleeve="midterm",
        role="constituent",
        tenor="single_event",
        expected_structure="partitioned",
        information_horizon=ELECTION_DAY,
        stitch_group="d_senate_seats",
        notes="UNVERIFIED: 1 seat, strikes 53-57. Stitch extension.",
    ),
    SeriesSpec(
        series_ticker="KXRHOUSESEATS",
        event_suffix="-27",
        sleeve="midterm",
        role="constituent",
        tenor="single_event",
        expected_structure="partitioned",
        information_horizon=ELECTION_DAY,
        notes="UNVERIFIED: 5 seats. Aligns with KXDHOUSESEATS only at the 218 line.",
    ),
    SeriesSpec(
        series_ticker="KXDHOUSESEATS",
        event_suffix="-27",
        sleeve="midterm",
        role="gate",
        tenor="single_event",
        expected_structure="partitioned",
        information_horizon=ELECTION_DAY,
        notes="UNVERIFIED: 4 seats. Parity gate only, never an index constituent.",
    ),
    SeriesSpec(
        series_ticker="KXBALANCEPOWERCOMBO",
        event_suffix="-27FEB",
        sleeve="control",
        role="constituent",
        tenor="single_event",
        expected_structure="categorical",
        information_horizon=ELECTION_DAY,
        notes=(
            "4 outcomes, no strikes; the sleeve metric is entropy, not sigma. "
            "BLOCKING: the 27FEB suffix implies a Feb 2027 expiry, which is neither "
            "Election Day nor the 2027-01-03 seating."
        ),
    ),
)

SLEEVES: tuple[str, ...] = ("approval", "midterm", "control")


def for_sleeve(sleeve: str) -> tuple[SeriesSpec, ...]:
    """Every registered series in a sleeve, gates included."""
    if sleeve not in SLEEVES:
        raise ValueError(f"unknown sleeve {sleeve!r}; known: {', '.join(SLEEVES)}")
    return tuple(s for s in SERIES if s.sleeve == sleeve)


def by_ticker(sleeve: str) -> dict[str, SeriesSpec]:
    return {s.series_ticker: s for s in for_sleeve(sleeve)}


def horizon_for_sleeve(sleeve: str) -> str | None:
    """The sleeve's information horizon, or None if it is constant-maturity."""
    horizons = {s.information_horizon for s in for_sleeve(sleeve)}
    horizons.discard(None)
    if len(horizons) > 1:
        raise ValueError(f"sleeve {sleeve!r} has conflicting horizons: {sorted(horizons)}")
    return horizons.pop() if horizons else None


def stitch_groups(sleeve: str) -> dict[str, tuple[str, ...]]:
    """Series that cover one underlying and must be fitted jointly."""
    groups: dict[str, list[str]] = {}
    for spec in for_sleeve(sleeve):
        if spec.stitch_group:
            groups.setdefault(spec.stitch_group, []).append(spec.series_ticker)
    return {k: tuple(v) for k, v in groups.items()}
