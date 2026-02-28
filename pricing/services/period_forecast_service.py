"""
Period Forecast Service: bi-weekly demand forecast with rate suggestions.

Generates occupancy forecasts for 2-week periods and suggests BB/HB/FB
rates based on demand pressure, calibrated against competitive market data.
"""

import logging
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q

logger = logging.getLogger(__name__)


class PeriodForecastService:
    """
    Bi-weekly occupancy forecast with market-calibrated rate suggestions.

    Each 2-week period produces:
    - OTB room nights (confirmed reservations overlapping that period)
    - Expected room nights (forecast after pickup + cancellation adjustment)
    - Expected occupancy %
    - Suggested BB / HB / FB rate (demand-driven within floor-ceiling range)

    Rate logic uses a demand-pressure curve:
      occ > 70%   -> push toward ceiling
      occ 50-70%  -> hold mid-range
      occ 30-50%  -> discount toward floor
      occ < 30%   -> floor rate + flag for tactical offers
    """

    # Defaults (Dharavandhoo market positioning)
    DEFAULT_BB_FLOOR = 50
    DEFAULT_BB_CEILING = 80
    DEFAULT_HB_SUPPLEMENT = 25   # per pax
    DEFAULT_FB_SUPPLEMENT = 40   # per pax
    DEFAULT_PAX = 2
    DEFAULT_CANCEL_RATE = 0.10   # 10% cancellation assumption

    def __init__(self, property):
        self.property = property
        self._load_market_position()

    def _load_market_position(self):
        """
        Load floor/ceiling/supplements from MarketPosition if it exists.
        Falls back to class-level defaults if not configured.
        """
        try:
            from pricing.models import MarketPosition
            mp = MarketPosition.objects.get(hotel=self.property)
            self.DEFAULT_BB_FLOOR = int(mp.bb_floor)
            self.DEFAULT_BB_CEILING = int(mp.bb_ceiling)
            self.DEFAULT_HB_SUPPLEMENT = int(mp.hb_supplement / self.DEFAULT_PAX)
            self.DEFAULT_FB_SUPPLEMENT = int(mp.fb_supplement / self.DEFAULT_PAX)
            logger.info(
                "Loaded MarketPosition for %s: floor=$%d, ceiling=$%d",
                self.property.code, self.DEFAULT_BB_FLOOR, self.DEFAULT_BB_CEILING
            )
        except Exception:
            # No MarketPosition configured — use class defaults
            pass

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def generate_forecast(self, months_ahead=3, bb_floor=None, bb_ceiling=None,
                          cancel_rate=None):
        """
        Generate bi-weekly forecast for the next N months.

        Args:
            months_ahead: Number of months to forecast (default 3)
            bb_floor: Override BB floor rate (or use MarketPosition/default)
            bb_ceiling: Override BB ceiling rate (or use MarketPosition/default)
            cancel_rate: Override cancellation rate (0-1, default 0.10)

        Returns:
            dict with assumptions, market_context, periods[]
        """
        from pricing.models import Reservation

        bb_floor = bb_floor if bb_floor is not None else self.DEFAULT_BB_FLOOR
        bb_ceiling = bb_ceiling if bb_ceiling is not None else self.DEFAULT_BB_CEILING
        cancel_rate = cancel_rate if cancel_rate is not None else self.DEFAULT_CANCEL_RATE

        total_rooms = self.property.total_rooms or self.property.get_total_rooms()
        if total_rooms <= 0:
            return {
                'assumptions': {
                    'total_rooms': 0,
                    'bb_floor': bb_floor,
                    'bb_ceiling': bb_ceiling,
                    'cancel_rate': cancel_rate,
                },
                'market_context': self._get_market_context(),
                'periods': [],
                'error': 'Property has no rooms configured.',
            }

        today = date.today()
        periods = self._build_periods(today, months_ahead)

        results = []
        for period in periods:
            result = self._forecast_period(
                period, total_rooms, bb_floor, bb_ceiling, cancel_rate
            )
            results.append(result)

        return {
            'assumptions': {
                'total_rooms': total_rooms,
                'bb_floor': bb_floor,
                'bb_ceiling': bb_ceiling,
                'cancel_rate': cancel_rate,
                'months_ahead': months_ahead,
            },
            'market_context': self._get_market_context(),
            'periods': results,
        }

    # -----------------------------------------------------------------
    # Period building
    # -----------------------------------------------------------------

    def _build_periods(self, start_date, months_ahead):
        """Build list of bi-weekly period dicts."""
        periods = []
        current = date(start_date.year, start_date.month, 1)
        # If we're past the 15th, start from the 16th period
        if start_date.day > 15:
            current = date(start_date.year, start_date.month, 16)

        end_limit = date(
            start_date.year + (start_date.month + months_ahead - 1) // 12,
            (start_date.month + months_ahead - 1) % 12 + 1,
            28  # safe end
        )

        while current <= end_limit:
            year, month = current.year, current.month
            _, last_day = calendar.monthrange(year, month)

            if current.day <= 15:
                # First half: 1-15
                period_start = date(year, month, 1)
                period_end = date(year, month, 15)
                label = f"{calendar.month_abbr[month]} 1\u201315"
            else:
                # Second half: 16-end
                period_start = date(year, month, 16)
                period_end = date(year, month, last_day)
                label = f"{calendar.month_abbr[month]} 16\u2013{last_day}"

            periods.append({
                'start': period_start,
                'end': period_end,
                'days': (period_end - period_start).days + 1,
                'label': label,
                'month': month,
                'year': year,
            })

            # Advance to next period
            if current.day <= 15:
                current = date(year, month, 16)
            else:
                # Next month 1st
                if month == 12:
                    current = date(year + 1, 1, 1)
                else:
                    current = date(year, month + 1, 1)

        return periods

    # -----------------------------------------------------------------
    # Per-period forecast
    # -----------------------------------------------------------------

    def _forecast_period(self, period, total_rooms, bb_floor, bb_ceiling,
                         cancel_rate):
        """
        Forecast a single bi-weekly period.

        1. Count OTB room nights (reservations overlapping the period)
        2. Estimate pickup from STLY and booking velocity
        3. Apply cancellation adjustment
        4. Calculate occupancy and suggest rates
        """
        from pricing.models import Reservation

        p_start = period['start']
        p_end = period['end']
        p_days = period['days']
        capacity = total_rooms * p_days

        today = date.today()
        days_out = max((p_start - today).days, 0)

        # ── 1. OTB: reservations overlapping this period ──
        otb_qs = Reservation.objects.filter(
            hotel=self.property,
            arrival_date__lte=p_end,
            departure_date__gte=p_start,
            status__in=Reservation.ACTIVE_STATUSES,
        )
        # Sum actual nights that fall within the period window
        otb_rn = 0
        for res in otb_qs.only('arrival_date', 'departure_date'):
            stay_start = max(res.arrival_date, p_start)
            stay_end = min(res.departure_date, p_end + timedelta(days=1))
            overlap = (stay_end - stay_start).days
            if overlap > 0:
                otb_rn += overlap

        # ── 2. STLY: same period last year ──
        stly_start = date(p_start.year - 1, p_start.month, p_start.day)
        stly_end = date(p_end.year - 1, p_end.month, min(p_end.day, calendar.monthrange(p_end.year - 1, p_end.month)[1]))
        stly_qs = Reservation.objects.filter(
            hotel=self.property,
            arrival_date__lte=stly_end,
            departure_date__gte=stly_start,
            status__in=Reservation.ACTIVE_STATUSES,
        )
        stly_rn = 0
        for res in stly_qs.only('arrival_date', 'departure_date'):
            stay_start = max(res.arrival_date, stly_start)
            stay_end = min(res.departure_date, stly_end + timedelta(days=1))
            overlap = (stay_end - stay_start).days
            if overlap > 0:
                stly_rn += overlap

        # ── 3. Booking velocity (last 14 days) ──
        velocity_window = 14
        vel_start = today - timedelta(days=velocity_window)
        vel_bookings = Reservation.objects.filter(
            hotel=self.property,
            booking_date__gte=vel_start,
            booking_date__lte=today,
            arrival_date__lte=p_end,
            arrival_date__gte=p_start,
            status__in=Reservation.ACTIVE_STATUSES,
        ).aggregate(nights=Sum('nights'))
        vel_nights = vel_bookings['nights'] or 0
        vel_per_day = vel_nights / velocity_window if velocity_window > 0 else 0

        # ── 4. Demand signal from MoT ──
        demand_signal = 1.0
        try:
            from platform_data.services import MarketSignalService
            idx = MarketSignalService.get_monthly_demand_index(
                self.property, date(p_start.year, p_start.month, 1)
            )
            demand_signal = idx.get('factor', 1.0)
        except Exception:
            pass

        # ── 5. Blended forecast ──
        # Velocity projection: OTB + remaining days * pace
        vel_forecast = otb_rn + int(vel_per_day * max(days_out, 0))

        # STLY-based forecast: use STLY as direct estimate (adjusted for demand)
        stly_forecast = stly_rn if stly_rn > 0 else otb_rn

        # Weighted blend: 40% OTB-momentum, 40% STLY, 20% velocity
        if days_out <= 7:
            # Very close: trust OTB heavily
            raw_forecast = int(otb_rn * 0.90 + stly_forecast * 0.10)
        elif days_out <= 30:
            raw_forecast = int(otb_rn * 0.50 + stly_forecast * 0.30 + vel_forecast * 0.20)
        else:
            raw_forecast = int(otb_rn * 0.30 + stly_forecast * 0.40 + vel_forecast * 0.30)

        # Apply demand signal
        raw_forecast = int(raw_forecast * demand_signal)

        # Apply cancellation haircut
        net_forecast = int(raw_forecast * (1 - cancel_rate))

        # Cap at capacity
        net_forecast = min(net_forecast, capacity)
        # Floor at OTB (can't forecast below what's confirmed)
        net_forecast = max(net_forecast, otb_rn)

        # ── 6. Occupancy + rates ──
        occupancy = net_forecast / capacity if capacity > 0 else 0

        rates = self._suggest_rates(occupancy, demand_signal, bb_floor, bb_ceiling)

        return {
            'label': period['label'],
            'start': period['start'].isoformat(),
            'end': period['end'].isoformat(),
            'days': p_days,
            'days_out': days_out,
            'capacity': capacity,
            # OTB
            'otb_rn': otb_rn,
            'otb_occ': round(otb_rn / capacity * 100, 1) if capacity > 0 else 0,
            # Forecast
            'raw_forecast': raw_forecast,
            'net_forecast': net_forecast,
            'occupancy_pct': round(occupancy * 100, 1),
            # STLY
            'stly_rn': stly_rn,
            'vs_stly': round((net_forecast - stly_rn) / stly_rn * 100, 1) if stly_rn > 0 else None,
            # Rates
            'rate_bb': rates['bb'],
            'rate_hb': rates['hb'],
            'rate_fb': rates['fb'],
            'demand_signal': round(demand_signal, 3),
            'offers_recommended': occupancy < 0.30,
            # Velocity
            'velocity_per_day': round(vel_per_day, 1),
        }

    # -----------------------------------------------------------------
    # Rate suggestion (demand-pressure curve)
    # -----------------------------------------------------------------

    def _suggest_rates(self, occupancy, demand_signal, bb_floor, bb_ceiling):
        """
        Suggest BB/HB/FB rates based on projected occupancy and demand.

        Demand pressure -> rate curve:
          occ > 70%   -> push toward ceiling ($75-80 BB)
          occ 50-70%  -> hold mid-range ($65-70 BB)
          occ 30-50%  -> discount toward floor ($58-63 BB)
          occ < 30%   -> floor rate ($50-55 BB) + activate offers

        The demand_signal (from MoT arrivals) adjusts +/-10% within band.
        """
        spread = bb_ceiling - bb_floor  # e.g. 80 - 50 = 30

        # Map occupancy to a position in the floor-ceiling range
        if occupancy >= 0.70:
            band_low = bb_ceiling - spread * 0.17
            band_high = bb_ceiling
        elif occupancy >= 0.50:
            band_low = bb_floor + spread * 0.50
            band_high = bb_floor + spread * 0.67
        elif occupancy >= 0.30:
            band_low = bb_floor + spread * 0.27
            band_high = bb_floor + spread * 0.43
        else:
            band_low = bb_floor
            band_high = bb_floor + spread * 0.17

        # Interpolate within the band using exact occupancy
        if occupancy >= 0.70:
            t = min((occupancy - 0.70) / 0.30, 1.0)
        elif occupancy >= 0.50:
            t = (occupancy - 0.50) / 0.20
        elif occupancy >= 0.30:
            t = (occupancy - 0.30) / 0.20
        else:
            t = max(occupancy / 0.30, 0.0)

        base_bb = band_low + t * (band_high - band_low)

        # Demand signal adjustment (MoT arrivals):
        # signal = 1.0 is neutral. Above 1.0 = stronger demand -> nudge up.
        demand_adj = 1.0 + (demand_signal - 1.0) * 0.10
        base_bb = base_bb * demand_adj

        # Round and clamp
        base_bb = int(round(max(bb_floor, min(bb_ceiling, base_bb))))

        # Meal plan supplements
        hb_supp = self.DEFAULT_HB_SUPPLEMENT * self.DEFAULT_PAX
        fb_supp = self.DEFAULT_FB_SUPPLEMENT * self.DEFAULT_PAX

        return {
            'bb': base_bb,
            'hb': base_bb + hb_supp,
            'fb': base_bb + fb_supp,
        }

    # -----------------------------------------------------------------
    # Market context
    # -----------------------------------------------------------------

    def _get_market_context(self):
        """Return competitive market context if available."""
        try:
            from pricing.models import MarketPosition
            mp = MarketPosition.objects.get(hotel=self.property)
            return {
                'market_avg_bb': float(mp.market_avg_bb or 0),
                'market_median_bb': float(mp.market_median_bb or 0),
                'competitor_count': mp.competitor_count,
                'strategy': mp.get_strategy_display() if mp.strategy else '',
                'last_survey': mp.last_survey_date.isoformat() if mp.last_survey_date else None,
            }
        except Exception:
            return {
                'market_avg_bb': 63,
                'market_median_bb': 55,
                'competitor_count': 8,
                'strategy': 'Mid-Premium',
                'last_survey': None,
            }
