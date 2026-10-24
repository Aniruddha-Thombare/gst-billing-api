from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class BucketBoundaries:
    """
    Cut-off dates for the five AR aging buckets, measured from as_of.

    An invoice's age is as_of - effective_due_date (effective due date =
    due_date, or invoice_date when there is no due date). In terms of the
    effective due date (eff):
      current  : eff >= as_of                    (not yet due)
      1-30     : cutoff_30 <= eff < as_of
      31-60    : cutoff_60 <= eff < cutoff_30
      61-90    : cutoff_90 <= eff < cutoff_60
      over 90  : eff < cutoff_90
    Comparing dates (instead of subtracting them in SQL) keeps the query
    index-friendly.
    """
    as_of: date
    cutoff_30: date
    cutoff_60: date
    cutoff_90: date


def bucket_boundaries(as_of_date: date) -> BucketBoundaries:
    """Pure function: the four cut-off dates for a report date."""
    return BucketBoundaries(
        as_of=as_of_date,
        cutoff_30=as_of_date - timedelta(days=30),
        cutoff_60=as_of_date - timedelta(days=60),
        cutoff_90=as_of_date - timedelta(days=90),
    )