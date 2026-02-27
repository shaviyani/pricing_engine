"""
Shared utilities for the pricing app.

Functions here are single-source-of-truth implementations used by
multiple views and services.
"""

from datetime import timedelta


def build_daily_occupancy_map(prop, start_date, end_date):
    """Build {date: rooms_occupied} map for a date range.

    Counts the number of occupied rooms on each date by iterating
    reservation stay ranges.  A room is counted on *arrival_date*
    through *departure_date - 1* (standard hotel night convention).

    Args:
        prop: Property instance
        start_date: First date (inclusive) of the range
        end_date: Last date (inclusive) of the range

    Returns:
        dict mapping ``date`` → ``int`` (rooms occupied that night)
    """
    from pricing.models import Reservation

    reservations = Reservation.objects.filter(
        hotel=prop,
        status__in=Reservation.ACTIVE_STATUSES,
        arrival_date__lte=end_date,
        departure_date__gt=start_date,
    ).values('arrival_date', 'departure_date')

    occupancy_map = {}
    for res in reservations:
        current = max(res['arrival_date'], start_date)
        res_end = min(res['departure_date'], end_date + timedelta(days=1))
        while current < res_end:
            occupancy_map[current] = occupancy_map.get(current, 0) + 1
            current += timedelta(days=1)
    return occupancy_map


def calculate_adr(revenue, room_nights):
    """Single source of truth for ADR calculation.

    Always returns a float rounded to 2 decimal places.
    Returns 0.0 when room_nights is zero or None.
    """
    if not room_nights or room_nights == 0:
        return 0.0
    return round(float(revenue) / float(room_nights), 2)
