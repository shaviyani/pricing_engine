"""
Cancellation Intelligence Service.

Comprehensive cancellation analysis for revenue management:
- Cancel rate by dimension (month, room type, country, channel, LOS, lead time)
- Cancellation timing curve (when do cancellations happen relative to arrival?)
- Revenue impact estimation
- Cancellation forecast for future months with per-booking risk scoring
- Rebooking analysis
"""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    Sum, Count, Avg, Min, Max, Q, F, Case, When, IntegerField, Value,
)


class CancellationAnalysisService:
    """
    Cancellation analysis and forecasting for a single property.

    Key methods:
        get_cancel_rates()              — master analysis across all dimensions
        get_cancellation_timing_curve() — when cancellations happen vs arrival
        get_revenue_impact()            — estimated revenue lost to cancellations
        forecast_cancellations()        — predict cancels for a future month
        get_rebooking_analysis()        — do cancelled guests rebook?
    """

    # Timing curve buckets (days before arrival)
    TIMING_BUCKETS = [
        ('90+', 90, 9999),
        ('61-90', 61, 90),
        ('31-60', 31, 60),
        ('15-30', 15, 30),
        ('8-14', 8, 14),
        ('0-7', 0, 7),
    ]

    # LOS buckets for analysis
    LOS_BUCKETS = [
        ('1-2', 1, 2),
        ('3-5', 3, 5),
        ('6-7', 6, 7),
        ('8-14', 8, 14),
        ('15+', 15, 999),
    ]

    # Lead time buckets
    LEAD_TIME_BUCKETS = [
        ('Same day', 0, 0),
        ('1-7 days', 1, 7),
        ('8-14 days', 8, 14),
        ('15-30 days', 15, 30),
        ('31-60 days', 31, 60),
        ('61-90 days', 61, 90),
        ('90+ days', 91, 9999),
    ]

    def __init__(self, property=None):
        self.property = property

    def _base_queryset(self):
        from pricing.models import Reservation
        qs = Reservation.objects.all()
        if self.property:
            qs = qs.filter(hotel=self.property)
        return qs

    # =================================================================
    # CANCEL RATE BY DIMENSION
    # =================================================================

    def get_cancel_rates(self, year=None, start_date=None, end_date=None):
        """
        Master cancel rate analysis across all dimensions.

        Returns dict with overall stats and breakdowns by month, room type,
        LOS bucket, country, lead time bucket, and channel.
        """
        base = self._base_queryset()
        if year:
            base = base.filter(arrival_date__year=year)
        if start_date:
            base = base.filter(arrival_date__gte=start_date)
        if end_date:
            base = base.filter(arrival_date__lte=end_date)

        total = base.count()
        cancelled = base.filter(status='cancelled')
        cancelled_count = cancelled.count()
        cancel_rate = round(cancelled_count / total * 100, 1) if total > 0 else 0

        cancelled_stats = cancelled.aggregate(
            lost_nights=Sum('nights'),
            est_lost_revenue=Sum('total_amount'),
        )

        overall = {
            'rate': cancel_rate,
            'count': cancelled_count,
            'total': total,
            'lost_nights': cancelled_stats['lost_nights'] or 0,
            'est_lost_revenue': float(cancelled_stats['est_lost_revenue'] or 0),
        }

        return {
            'overall': overall,
            'by_month': self._cancel_rate_by_month(base),
            'by_room_type': self._cancel_rate_by_room_type(base),
            'by_los_bucket': self._cancel_rate_by_los(base),
            'by_country': self._cancel_rate_by_country(base),
            'by_lead_time': self._cancel_rate_by_lead_time(base),
            'by_channel': self._cancel_rate_by_channel(base),
        }

    def _cancel_rate_by_month(self, base_qs):
        result = []
        for month in range(1, 13):
            month_qs = base_qs.filter(arrival_date__month=month)
            total = month_qs.count()
            cancelled = month_qs.filter(status='cancelled').count()
            lost_nights = month_qs.filter(status='cancelled').aggregate(
                n=Sum('nights'))['n'] or 0
            result.append({
                'month': month,
                'month_name': calendar.month_abbr[month],
                'rate': round(cancelled / total * 100, 1) if total > 0 else 0,
                'count': cancelled,
                'total': total,
                'lost_nights': lost_nights,
            })
        return result

    def _cancel_rate_by_room_type(self, base_qs):
        from pricing.models import Reservation
        data = base_qs.filter(room_type__isnull=False).values(
            'room_type__name'
        ).annotate(
            total=Count('id'),
            cancelled=Count('id', filter=Q(status='cancelled')),
        ).order_by('-total')

        return [
            {
                'name': d['room_type__name'],
                'rate': round(d['cancelled'] / d['total'] * 100, 1) if d['total'] > 0 else 0,
                'count': d['cancelled'],
                'total': d['total'],
            }
            for d in data
        ]

    def _cancel_rate_by_los(self, base_qs):
        result = []
        for label, lo, hi in self.LOS_BUCKETS:
            bucket_qs = base_qs.filter(nights__gte=lo, nights__lte=hi)
            total = bucket_qs.count()
            cancelled = bucket_qs.filter(status='cancelled').count()
            result.append({
                'bucket': label,
                'rate': round(cancelled / total * 100, 1) if total > 0 else 0,
                'count': cancelled,
                'total': total,
            })
        return result

    def _cancel_rate_by_country(self, base_qs):
        data = base_qs.filter(
            guest__isnull=False,
            guest__country__gt='',
        ).values('guest__country').annotate(
            total=Count('id'),
            cancelled=Count('id', filter=Q(status='cancelled')),
            avg_los=Avg('nights'),
        ).filter(total__gte=5).order_by('-total')

        return [
            {
                'country': d['guest__country'],
                'rate': round(d['cancelled'] / d['total'] * 100, 1) if d['total'] > 0 else 0,
                'count': d['cancelled'],
                'total': d['total'],
                'avg_los': round(d['avg_los'] or 0, 1),
            }
            for d in data
        ]

    def _cancel_rate_by_lead_time(self, base_qs):
        result = []
        for label, lo, hi in self.LEAD_TIME_BUCKETS:
            bucket_qs = base_qs.filter(lead_time_days__gte=lo, lead_time_days__lte=hi)
            total = bucket_qs.count()
            cancelled = bucket_qs.filter(status='cancelled').count()
            result.append({
                'bucket': label,
                'rate': round(cancelled / total * 100, 1) if total > 0 else 0,
                'count': cancelled,
                'total': total,
            })
        return result

    def _cancel_rate_by_channel(self, base_qs):
        data = base_qs.filter(channel__isnull=False).values(
            'channel__name'
        ).annotate(
            total=Count('id'),
            cancelled=Count('id', filter=Q(status='cancelled')),
        ).filter(total__gte=3).order_by('-total')

        return [
            {
                'channel': d['channel__name'],
                'rate': round(d['cancelled'] / d['total'] * 100, 1) if d['total'] > 0 else 0,
                'count': d['cancelled'],
                'total': d['total'],
            }
            for d in data
        ]

    # =================================================================
    # TIMING CURVE
    # =================================================================

    def get_cancellation_timing_curve(self, year=None):
        """
        When do cancellations happen relative to arrival?

        Returns a list of timing buckets with count and percentage
        of cancellations in each bucket.
        """
        base = self._base_queryset().filter(
            status='cancelled',
            cancellation_date__isnull=False,
        )
        if year:
            base = base.filter(arrival_date__year=year)

        total_cancels = base.count()
        if total_cancels == 0:
            return []

        result = []
        cumulative = 0

        # Calculate days-before-arrival for each cancellation
        # We annotate, but DurationField math varies by DB — iterate instead
        cancel_timing = defaultdict(int)
        for res in base.only('arrival_date', 'cancellation_date'):
            days_before = (res.arrival_date - res.cancellation_date).days
            for label, lo, hi in self.TIMING_BUCKETS:
                if lo <= days_before <= hi:
                    cancel_timing[label] += 1
                    break
            else:
                # After arrival (negative days_before)
                cancel_timing['after_arrival'] = cancel_timing.get('after_arrival', 0) + 1

        for label, lo, hi in self.TIMING_BUCKETS:
            count = cancel_timing.get(label, 0)
            pct = round(count / total_cancels * 100, 1) if total_cancels > 0 else 0
            cumulative += pct
            result.append({
                'bucket': label,
                'days_before_lo': lo,
                'days_before_hi': hi,
                'count': count,
                'pct': pct,
                'cumulative_pct': round(cumulative, 1),
            })

        # After arrival bucket
        after_count = cancel_timing.get('after_arrival', 0)
        if after_count > 0:
            pct = round(after_count / total_cancels * 100, 1)
            cumulative += pct
            result.append({
                'bucket': 'After arrival',
                'days_before_lo': -9999,
                'days_before_hi': -1,
                'count': after_count,
                'pct': pct,
                'cumulative_pct': round(cumulative, 1),
            })

        return result

    # =================================================================
    # ESTIMATED REVENUE IMPACT
    # =================================================================

    def get_revenue_impact(self, year=None):
        """
        Estimate revenue lost to cancellations.

        For cancelled bookings with $0 revenue, applies the average
        confirmed ADR for the same month as the estimate.
        """
        from pricing.models import Reservation

        base = self._base_queryset()
        if year:
            base = base.filter(arrival_date__year=year)

        cancelled = base.filter(status='cancelled')
        confirmed = base.filter(status__in=Reservation.ACTIVE_STATUSES, adr__gt=0)

        monthly_impact = []
        total_lost = Decimal('0')

        for month in range(1, 13):
            cancel_nights = cancelled.filter(
                arrival_date__month=month
            ).aggregate(n=Sum('nights'))['n'] or 0

            # Use confirmed ADR for this month as estimate basis
            month_adr = confirmed.filter(
                arrival_date__month=month
            ).aggregate(avg=Avg('adr'))['avg'] or Decimal('0')

            est_revenue = month_adr * cancel_nights
            total_lost += est_revenue

            # Count how many had estimated vs actual revenue
            estimated_count = cancelled.filter(
                arrival_date__month=month,
                is_revenue_estimated=True,
            ).count()

            monthly_impact.append({
                'month': month,
                'month_name': calendar.month_abbr[month],
                'lost_nights': cancel_nights,
                'est_adr': float(month_adr),
                'est_revenue': float(est_revenue),
                'estimated_count': estimated_count,
            })

        # Late cancellations (within 7 days of arrival)
        late_cancels = cancelled.filter(
            cancellation_date__isnull=False,
        )
        late_count = 0
        late_nights = 0
        for res in late_cancels.only('arrival_date', 'cancellation_date', 'nights'):
            days_before = (res.arrival_date - res.cancellation_date).days
            if 0 <= days_before <= 7:
                late_count += 1
                late_nights += res.nights or 0

        return {
            'total_estimated_lost': float(total_lost),
            'by_month': monthly_impact,
            'late_cancellations': {
                'count': late_count,
                'room_nights': late_nights,
            },
        }

    # =================================================================
    # CANCELLATION FORECAST
    # =================================================================

    def forecast_cancellations(self, target_month, target_year):
        """
        Predict how many current OTB bookings for a future month will cancel.

        Uses historical cancel rate, source market risk, and per-booking
        probability scoring.
        """
        from pricing.models import Reservation

        month_start = date(target_year, target_month, 1)
        _, last_day = calendar.monthrange(target_year, target_month)
        month_end = date(target_year, target_month, last_day)
        today = date.today()

        # Current OTB for this month
        otb = self._base_queryset().filter(
            arrival_date__gte=month_start,
            arrival_date__lte=month_end,
            status__in=Reservation.FUTURE_STATUSES,
        )

        otb_count = otb.count()
        otb_nights = otb.aggregate(n=Sum('nights'))['n'] or 0

        if otb_count == 0:
            return {
                'otb_bookings': 0, 'otb_room_nights': 0,
                'predicted_cancels': 0, 'predicted_cancel_rate': 0,
                'predicted_lost_nights': 0,
                'net_room_nights': 0, 'confidence': 'low',
                'historical_cancel_rate': 0,
                'risk_breakdown': [],
            }

        # Historical cancel rate for this month
        historical_rate = self._get_monthly_cancel_rate(target_month)

        # Pre-fetch country cancel rates to avoid N+1
        country_rates = self._get_all_country_cancel_rates()

        # Score each OTB booking
        risk_scores = []
        for res in otb.select_related('guest'):
            score = self._score_cancel_risk(
                res, today, historical_rate, country_rates
            )
            risk_scores.append(score)

        # Predicted cancels = sum of individual probabilities
        predicted_cancels = sum(s['probability'] for s in risk_scores)
        predicted_cancel_rate = predicted_cancels / otb_count * 100 if otb_count > 0 else 0

        # Predicted lost nights (weighted by probability)
        predicted_lost_nights = sum(
            s['probability'] * s['nights'] for s in risk_scores
        )
        net_room_nights = otb_nights - int(predicted_lost_nights)

        # Risk breakdown
        high_risk = [s for s in risk_scores if s['probability'] >= 0.6]
        medium_risk = [s for s in risk_scores if 0.3 <= s['probability'] < 0.6]
        low_risk = [s for s in risk_scores if s['probability'] < 0.3]

        # Confidence based on data depth
        historical_count = self._base_queryset().filter(
            arrival_date__month=target_month
        ).count()
        confidence = 'high' if historical_count >= 50 else 'medium' if historical_count >= 20 else 'low'

        return {
            'otb_bookings': otb_count,
            'otb_room_nights': otb_nights,
            'predicted_cancels': round(predicted_cancels, 1),
            'predicted_cancel_rate': round(predicted_cancel_rate, 1),
            'predicted_lost_nights': int(predicted_lost_nights),
            'net_room_nights': max(0, net_room_nights),
            'confidence': confidence,
            'historical_cancel_rate': round(historical_rate * 100, 1),
            'risk_breakdown': [
                {'level': 'high', 'count': len(high_risk),
                 'pct': round(len(high_risk) / otb_count * 100, 1) if otb_count > 0 else 0},
                {'level': 'medium', 'count': len(medium_risk),
                 'pct': round(len(medium_risk) / otb_count * 100, 1) if otb_count > 0 else 0},
                {'level': 'low', 'count': len(low_risk),
                 'pct': round(len(low_risk) / otb_count * 100, 1) if otb_count > 0 else 0},
            ],
        }

    # =================================================================
    # INDIVIDUAL BOOKING RISK SCORING
    # =================================================================

    def _score_cancel_risk(self, reservation, today, base_rate, country_rates):
        """
        Score an individual booking's cancellation probability.

        Factors (weighted):
        - Base rate for this month/property (40%)
        - Source market cancel rate (25%)
        - LOS risk (longer stays cancel more) (15%)
        - Lead time risk (further out = more time to cancel) (10%)
        - Days until arrival (close = less likely to cancel now) (10%)
        """
        monthly_prob = base_rate

        # Factor 2: Source market
        country = ''
        if reservation.guest:
            country = reservation.guest.country or ''
        country_rate = country_rates.get(country, base_rate)

        # Factor 3: LOS
        nights = reservation.nights or 1
        if nights >= 10:
            los_factor = 1.15
        elif nights >= 7:
            los_factor = 1.10
        elif nights >= 4:
            los_factor = 1.00
        elif nights >= 2:
            los_factor = 0.90
        else:
            los_factor = 0.85

        # Factor 4: Lead time at booking
        lead_time = reservation.lead_time_days or 0
        if lead_time >= 120:
            lead_factor = 1.15
        elif lead_time >= 60:
            lead_factor = 1.05
        elif lead_time >= 30:
            lead_factor = 1.00
        else:
            lead_factor = 0.85

        # Factor 5: Days until arrival (from today)
        days_to_arrival = (reservation.arrival_date - today).days
        if days_to_arrival <= 7:
            arrival_factor = 0.30
        elif days_to_arrival <= 14:
            arrival_factor = 0.50
        elif days_to_arrival <= 30:
            arrival_factor = 0.75
        elif days_to_arrival <= 60:
            arrival_factor = 0.90
        else:
            arrival_factor = 1.00

        # Weighted probability
        probability = (
            monthly_prob * 0.40 +
            country_rate * 0.25 +
            (monthly_prob * los_factor) * 0.15 +
            (monthly_prob * lead_factor) * 0.10
        ) * arrival_factor

        probability = max(0.05, min(0.95, probability))

        if probability >= 0.6:
            risk_level = 'high'
        elif probability >= 0.3:
            risk_level = 'medium'
        else:
            risk_level = 'low'

        return {
            'reservation_id': reservation.id,
            'confirmation_no': reservation.confirmation_no,
            'probability': probability,
            'risk_level': risk_level,
            'nights': nights,
            'factors': {
                'monthly_base': round(monthly_prob, 3),
                'country_rate': round(country_rate, 3),
                'country': country,
                'los_factor': los_factor,
                'lead_factor': lead_factor,
                'arrival_factor': arrival_factor,
            },
        }

    # =================================================================
    # HELPERS
    # =================================================================

    def _get_monthly_cancel_rate(self, month):
        """Get historical cancel rate for a specific month."""
        base = self._base_queryset().filter(arrival_date__month=month)
        total = base.count()
        if total < 5:
            return 0.50  # Default when insufficient data
        cancelled = base.filter(status='cancelled').count()
        return cancelled / total

    def _get_all_country_cancel_rates(self):
        """
        Pre-fetch cancel rates for all countries in one query.
        Returns dict of {country: cancel_rate}.
        """
        data = self._base_queryset().filter(
            guest__isnull=False,
            guest__country__gt='',
        ).values('guest__country').annotate(
            total=Count('id'),
            cancelled=Count('id', filter=Q(status='cancelled')),
        ).filter(total__gte=5)

        return {
            d['guest__country']: d['cancelled'] / d['total']
            for d in data
        }

    # =================================================================
    # REBOOKING ANALYSIS
    # =================================================================

    def get_rebooking_analysis(self):
        """
        Analyze whether cancelled guests rebook.

        Returns counts of cancel-only guests, rebooked guests,
        and the rebooking rate.
        """
        from pricing.models import Reservation

        base = self._base_queryset().filter(guest__isnull=False)

        guest_stats = base.values('guest_id').annotate(
            has_cancel=Max(Case(
                When(status='cancelled', then=1),
                default=0,
                output_field=IntegerField()
            )),
            has_active=Max(Case(
                When(status__in=Reservation.ACTIVE_STATUSES, then=1),
                default=0,
                output_field=IntegerField()
            )),
        )

        cancel_only = 0
        rebooked = 0
        never_cancelled = 0
        for g in guest_stats:
            if g['has_cancel'] == 1 and g['has_active'] == 0:
                cancel_only += 1
            elif g['has_cancel'] == 1 and g['has_active'] == 1:
                rebooked += 1
            elif g['has_cancel'] == 0 and g['has_active'] == 1:
                never_cancelled += 1

        total_cancellers = cancel_only + rebooked
        rebooking_rate = round(
            rebooked / total_cancellers * 100, 1
        ) if total_cancellers > 0 else 0

        return {
            'cancel_only_guests': cancel_only,
            'rebooked_guests': rebooked,
            'never_cancelled_guests': never_cancelled,
            'rebooking_rate': rebooking_rate,
        }
