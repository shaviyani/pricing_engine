"""
Market Intelligence Service.

Crosses national MoT arrival data with property reservation data to
produce property-specific market positioning and forward indicators.
"""

import calendar as cal
import logging
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum, Count, Q

logger = logging.getLogger(__name__)


class MarketIntelligenceService:

    COUNTRY_ALIASES = {
        'United States of America': 'United States',
        'USA': 'United States',
        'UK': 'United Kingdom',
        'UAE': 'United Arab Emirates',
        'S. Korea': 'South Korea',
        'Rep. of Korea': 'South Korea',
    }

    ISO_TO_NAME = {
        'IT': 'Italy', 'DE': 'Germany', 'GB': 'United Kingdom',
        'RU': 'Russia', 'CN': 'China', 'IN': 'India',
        'US': 'United States', 'FR': 'France', 'ES': 'Spain',
        'CH': 'Switzerland', 'AU': 'Australia', 'GR': 'Greece',
        'NL': 'Netherlands', 'AT': 'Austria', 'PL': 'Poland',
        'CZ': 'Czech Republic', 'ZA': 'South Africa', 'SI': 'Slovenia',
        'TR': 'Turkey', 'GE': 'Georgia', 'SE': 'Sweden',
        'JP': 'Japan', 'KR': 'South Korea', 'BR': 'Brazil',
        'PT': 'Portugal', 'HU': 'Hungary', 'RO': 'Romania',
        'BG': 'Bulgaria', 'SK': 'Slovakia', 'DK': 'Denmark',
        'BE': 'Belgium', 'IE': 'Ireland', 'NO': 'Norway',
        'FI': 'Finland', 'SA': 'Saudi Arabia', 'AE': 'United Arab Emirates',
        'KW': 'Kuwait', 'QA': 'Qatar', 'MY': 'Malaysia',
        'SG': 'Singapore', 'TH': 'Thailand', 'ID': 'Indonesia',
        'PH': 'Philippines', 'BD': 'Bangladesh', 'PK': 'Pakistan',
        'LK': 'Sri Lanka', 'MV': 'Maldives', 'KZ': 'Kazakhstan',
        'UZ': 'Uzbekistan', 'UA': 'Ukraine', 'BY': 'Belarus',
        'CA': 'Canada', 'MX': 'Mexico', 'AR': 'Argentina',
        'EG': 'Egypt', 'IL': 'Israel', 'JO': 'Jordan',
    }

    def __init__(self, property):
        self.property = property
        self.country_code = getattr(property, 'country_code', 'MV') or 'MV'

    def _normalize_country(self, name):
        if not name:
            return None
        name = name.strip()
        if len(name) == 2 and name.upper() in self.ISO_TO_NAME:
            return self.ISO_TO_NAME[name.upper()]
        return self.COUNTRY_ALIASES.get(name, name)

    def _get_property_market_mix(self, year=None):
        from pricing.models import Reservation

        qs = Reservation.objects.filter(
            hotel=self.property,
            guest__isnull=False,
            guest__country__isnull=False,
        ).exclude(guest__country='')

        if year:
            qs = qs.filter(arrival_date__year=year)

        active = qs.filter(status__in=Reservation.ACTIVE_STATUSES).values(
            'guest__country'
        ).annotate(
            revenue=Sum('total_amount'),
            bookings=Count('id'),
            nights=Sum('nights'),
        )

        cancel_data = qs.values('guest__country').annotate(
            total=Count('id'),
            cancelled=Count('id', filter=Q(status='cancelled')),
        )
        cancel_map = {
            r['guest__country']: {
                'total': r['total'],
                'cancelled': r['cancelled'],
                'cancel_rate': round(r['cancelled'] / r['total'] * 100, 1) if r['total'] >= 3 else None,
            }
            for r in cancel_data
        }

        result = {}
        for r in active:
            country = self._normalize_country(r['guest__country'])
            if not country:
                continue
            cancel_info = cancel_map.get(r['guest__country'], {})
            result[country] = {
                'revenue': float(r['revenue'] or 0),
                'bookings': r['bookings'],
                'nights': r['nights'] or 0,
                'cancel_rate': cancel_info.get('cancel_rate'),
                'total_bookings': cancel_info.get('total', 0),
                'cancelled_bookings': cancel_info.get('cancelled', 0),
            }

        return result

    def _get_national_market_mix(self, year=None):
        from platform_data.models import MarketArrivalData

        if not year:
            year = date.today().year

        qs = MarketArrivalData.objects.filter(
            country_code=self.country_code,
            report_period__year=year,
        ).values('origin_country').annotate(
            total=Sum('arrivals'),
        ).order_by('-total')

        grand_total = sum(r['total'] for r in qs)

        prior = {
            r['origin_country']: r['total']
            for r in MarketArrivalData.objects.filter(
                country_code=self.country_code,
                report_period__year=year - 1,
            ).values('origin_country').annotate(total=Sum('arrivals'))
        }

        result = {}
        for r in qs:
            country = r['origin_country']
            arrivals = r['total']
            prev = prior.get(country, 0)
            result[country] = {
                'arrivals': arrivals,
                'share': round(arrivals / grand_total * 100, 1) if grand_total else 0,
                'yoy_pct': round((arrivals - prev) / prev * 100, 1) if prev > 0 else None,
            }

        return result

    def _get_country_completeness(self):
        from pricing.models import Reservation
        total = Reservation.objects.filter(hotel=self.property).count()
        with_country = Reservation.objects.filter(
            hotel=self.property,
            guest__country__isnull=False,
        ).exclude(guest__country='').count()
        return round(with_country / total * 100) if total > 0 else 0

    # ── Section 1: Property Position ─────────────────────────────────────

    def get_property_vs_national_mix(self, year=None):
        if not year:
            year = date.today().year

        prop_mix = self._get_property_market_mix(year)
        national_mix = self._get_national_market_mix(year)

        if not prop_mix:
            return {'has_data': False, 'reason': 'No reservation data with guest country'}

        prop_total_rev = sum(m['revenue'] for m in prop_mix.values())

        markets = []
        for country, prop_data in sorted(prop_mix.items(), key=lambda x: x[1]['revenue'], reverse=True):
            nat_data = national_mix.get(country, {})
            prop_share = round(prop_data['revenue'] / prop_total_rev * 100, 1) if prop_total_rev else 0
            nat_share = nat_data.get('share', 0)

            index = round(prop_share / nat_share, 1) if nat_share > 0 else None
            position = 'neutral'
            if index and index >= 1.5:
                position = 'over_indexed'
            elif index and index <= 0.5:
                position = 'under_indexed'

            markets.append({
                'country': country,
                'prop_share': prop_share,
                'prop_revenue': round(prop_data['revenue']),
                'prop_bookings': prop_data['bookings'],
                'prop_nights': prop_data['nights'],
                'national_share': nat_share,
                'national_arrivals': nat_data.get('arrivals', 0),
                'national_yoy': nat_data.get('yoy_pct'),
                'index': index,
                'position': position,
            })

        return {
            'has_data': True,
            'year': year,
            'property_total_revenue': round(prop_total_rev),
            'national_total_arrivals': sum(m.get('arrivals', 0) for m in national_mix.values()),
            'markets': markets[:15],
            'country_completeness': self._get_country_completeness(),
        }

    def get_concentration_risk(self, year=None):
        position = self.get_property_vs_national_mix(year)
        if not position.get('has_data'):
            return {'has_data': False}

        markets = position['markets']
        prop_shares = sorted([m['prop_share'] for m in markets], reverse=True)
        nat_shares = sorted([m['national_share'] for m in markets if m['national_share'] > 0], reverse=True)

        prop_top3 = sum(prop_shares[:3])
        nat_top3 = sum(nat_shares[:3]) if len(nat_shares) >= 3 else sum(nat_shares)

        prop_hhi = round(sum(s ** 2 for s in prop_shares))
        nat_hhi = round(sum(s ** 2 for s in nat_shares))

        risk = 'high' if prop_top3 > 50 else 'moderate' if prop_top3 > 35 else 'low'
        top3_names = [m['country'] for m in sorted(markets, key=lambda x: x['prop_share'], reverse=True)[:3]]

        return {
            'has_data': True,
            'prop_top3_share': round(prop_top3, 1),
            'national_top3_share': round(nat_top3, 1),
            'prop_top3': top3_names,
            'risk_level': risk,
            'prop_hhi': prop_hhi,
            'national_hhi': nat_hhi,
        }

    def get_diversification_opportunities(self, year=None):
        position = self.get_property_vs_national_mix(year)
        if not position.get('has_data'):
            return []

        opportunities = []
        for m in position['markets']:
            gap = m['national_share'] - m['prop_share']
            if gap > 2 and m['national_share'] >= 1.0:
                growth_factor = max(1, 1 + (m['national_yoy'] or 0) / 100)
                score = round(gap * growth_factor * 10)
                opportunities.append({
                    'country': m['country'],
                    'national_share': m['national_share'],
                    'prop_share': m['prop_share'],
                    'national_yoy': m['national_yoy'],
                    'national_arrivals': m['national_arrivals'],
                    'gap': round(gap, 1),
                    'opportunity_score': score,
                })

        # Markets in national top 20 that property has zero revenue from
        national_mix = self._get_national_market_mix(year)
        prop_countries = {m['country'] for m in position['markets']}

        for country, nat_data in sorted(national_mix.items(), key=lambda x: x[1]['arrivals'], reverse=True)[:20]:
            if country not in prop_countries and nat_data['share'] >= 1.0:
                growth_factor = max(1, 1 + (nat_data['yoy_pct'] or 0) / 100)
                score = round(nat_data['share'] * growth_factor * 10)
                opportunities.append({
                    'country': country,
                    'national_share': nat_data['share'],
                    'prop_share': 0,
                    'national_yoy': nat_data['yoy_pct'],
                    'national_arrivals': nat_data['arrivals'],
                    'gap': nat_data['share'],
                    'opportunity_score': score,
                })

        opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
        return opportunities[:10]

    # ── Section 2: Market-Cancellation Cross ─────────────────────────────

    def get_market_cancel_cross(self, year=None):
        prop_mix = self._get_property_market_mix(year)
        national_mix = self._get_national_market_mix(year)

        if not prop_mix:
            return {'has_data': False}

        markets = []
        for country, prop_data in prop_mix.items():
            if prop_data.get('cancel_rate') is None:
                continue

            nat_data = national_mix.get(country, {})
            nat_yoy = nat_data.get('yoy_pct')
            cancel_rate = prop_data['cancel_rate']

            high_cancel = cancel_rate >= 45
            positive_growth = nat_yoy is not None and nat_yoy > 0

            if high_cancel and positive_growth:
                diagnosis = 'demand_healthy_retention_problem'
                label = 'Demand healthy — retention problem'
                action = f'Review cancellation policy for {country} bookings'
            elif high_cancel and not positive_growth:
                diagnosis = 'demand_and_retention_problem'
                label = 'Demand weakening + retention problem'
                action = f'Reduce dependency on {country} market'
            elif not high_cancel and positive_growth:
                diagnosis = 'strong_position'
                label = 'Strong position'
                action = f'Maintain — consider increasing {country} exposure'
            elif not high_cancel and not positive_growth:
                diagnosis = 'market_shrinking'
                label = 'Market declining — diversify'
                action = 'Reduce dependency, target growing markets instead'
            else:
                diagnosis = 'neutral'
                label = 'Neutral'
                action = 'Monitor'

            markets.append({
                'country': country,
                'cancel_rate': cancel_rate,
                'national_yoy': nat_yoy,
                'diagnosis': diagnosis,
                'diagnosis_label': label,
                'action': action,
                'total_bookings': prop_data['total_bookings'],
                'cancelled': prop_data['cancelled_bookings'],
                'active_bookings': prop_data['bookings'],
                'revenue': round(prop_data['revenue']),
            })

        markets.sort(key=lambda x: (-x['cancel_rate'], -x['total_bookings']))
        return {'has_data': True, 'markets': markets}

    # ── Section 3: Lead Time by Market ───────────────────────────────────

    def get_lead_time_by_market(self, top_n=12):
        from pricing.models import Reservation

        qs = Reservation.objects.filter(
            hotel=self.property,
            status__in=Reservation.ACTIVE_STATUSES,
            booking_date__isnull=False,
            guest__isnull=False,
            guest__country__isnull=False,
        ).exclude(guest__country='')

        lead_by_country = defaultdict(list)
        for r in qs.values('guest__country', 'booking_date', 'arrival_date'):
            if r['booking_date'] and r['arrival_date']:
                days = (r['arrival_date'] - r['booking_date']).days
                if 0 <= days <= 365:
                    country = self._normalize_country(r['guest__country'])
                    if country:
                        lead_by_country[country].append(days)

        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        markets = []
        for country, days_list in sorted(lead_by_country.items(), key=lambda x: len(x[1]), reverse=True)[:top_n]:
            if len(days_list) < 3:
                continue

            avg_lead = round(sum(days_list) / len(days_list))

            if avg_lead >= 180:
                bucket = 'ultra_early'
            elif avg_lead >= 90:
                bucket = 'early'
            elif avg_lead >= 30:
                bucket = 'standard'
            else:
                bucket = 'last_minute'

            # Peak arrival months from property data
            arrival_months = list(
                Reservation.objects.filter(
                    hotel=self.property,
                    status__in=Reservation.ACTIVE_STATUSES,
                    guest__country=country,
                ).values_list('arrival_date__month', flat=True)
            )

            peak_months = []
            watch = None
            if arrival_months:
                month_counts = Counter(arrival_months)
                peak_months = [month_names[m - 1] for m, _ in month_counts.most_common(2)]
                if avg_lead > 30:
                    watch_month_idx = (month_counts.most_common(1)[0][0] - 1 - avg_lead // 30) % 12
                    watch = f"Start watching {country} pickup in {month_names[watch_month_idx]} for {peak_months[0]} arrivals"

            markets.append({
                'country': country,
                'avg_lead_days': avg_lead,
                'median_lead_days': sorted(days_list)[len(days_list) // 2],
                'bookings': len(days_list),
                'lead_bucket': bucket,
                'peak_arrival_months': peak_months,
                'watch_guidance': watch,
            })

        return {'has_data': len(markets) > 0, 'markets': markets}

    def get_lead_time_heatmap(self, top_n=10):
        from pricing.models import Reservation

        qs = Reservation.objects.filter(
            hotel=self.property,
            status__in=Reservation.ACTIVE_STATUSES,
            booking_date__isnull=False,
            guest__isnull=False,
            guest__country__isnull=False,
        ).exclude(guest__country='')

        bucket_ranges = [
            ('0-14d', 0, 14),
            ('15-30d', 15, 30),
            ('31-60d', 31, 60),
            ('61-90d', 61, 90),
            ('91-180d', 91, 180),
            ('180d+', 181, 999),
        ]

        by_country = defaultdict(lambda: defaultdict(int))
        country_totals = defaultdict(int)

        for r in qs.values('guest__country', 'booking_date', 'arrival_date'):
            if r['booking_date'] and r['arrival_date']:
                days = (r['arrival_date'] - r['booking_date']).days
                if days < 0:
                    continue
                country = self._normalize_country(r['guest__country'])
                if not country:
                    continue

                for label, lo, hi in bucket_ranges:
                    if lo <= days <= hi:
                        by_country[country][label] += 1
                        country_totals[country] += 1
                        break

        top_countries = sorted(country_totals.items(), key=lambda x: x[1], reverse=True)[:top_n]
        market_list = [c for c, _ in top_countries]
        matrix = {}
        for country in market_list:
            total = country_totals[country]
            matrix[country] = [
                round(by_country[country][label] / total * 100) if total > 0 else 0
                for label, _, _ in bucket_ranges
            ]

        return {
            'has_data': len(market_list) > 0,
            'markets': market_list,
            'buckets': [label for label, _, _ in bucket_ranges],
            'matrix': matrix,
        }

    # ── Section 4: Growth-Adjusted Forecast ──────────────────────────────

    def get_growth_adjusted_forecast(self, months_ahead=6):
        from pricing.models import Reservation
        from platform_data.models import MarketArrivalData

        today = date.today()
        prop_mix = self._get_property_market_mix()
        national_mix = self._get_national_market_mix()

        prop_total_rev = sum(m['revenue'] for m in prop_mix.values())
        if prop_total_rev == 0:
            return {'has_data': False}

        weights = {country: data['revenue'] / prop_total_rev for country, data in prop_mix.items()}

        months = []
        for i in range(1, months_ahead + 1):
            target_month = today.month + i
            target_year = today.year + (target_month - 1) // 12
            target_month = ((target_month - 1) % 12) + 1
            target_date = date(target_year, target_month, 1)

            # STLY room nights
            stly_start = date(target_year - 1, target_month, 1)
            _, stly_days = cal.monthrange(target_year - 1, target_month)
            stly_end = date(target_year - 1, target_month, stly_days)

            stly_rn = Reservation.objects.filter(
                hotel=self.property,
                arrival_date__gte=stly_start,
                arrival_date__lte=stly_end,
                status__in=Reservation.ACTIVE_STATUSES,
            ).aggregate(t=Sum('nights'))['t'] or 0

            # Per-market YoY for this month
            month_yoy = {}
            current_map = {
                r['origin_country']: r['arrivals']
                for r in MarketArrivalData.objects.filter(
                    country_code=self.country_code,
                    report_period__month=target_month,
                    report_period__year=target_year - 1,
                ).values('origin_country', 'arrivals')
            }
            prior_map = {
                r['origin_country']: r['arrivals']
                for r in MarketArrivalData.objects.filter(
                    country_code=self.country_code,
                    report_period__month=target_month,
                    report_period__year=target_year - 2,
                ).values('origin_country', 'arrivals')
            }

            for country in current_map:
                curr = current_map[country]
                prev = prior_map.get(country, 0)
                if prev > 0:
                    month_yoy[country] = (curr - prev) / prev

            # Blended growth
            blended_growth = 0
            dominant_markets = []
            for country, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
                yoy = month_yoy.get(country)
                if yoy is not None:
                    blended_growth += weight * yoy
                    if weight >= 0.03:
                        dominant_markets.append({
                            'country': country,
                            'prop_share': round(weight * 100, 1),
                            'yoy': round(yoy * 100, 1),
                            'weight': round(weight, 2),
                        })

            adjusted_rn = max(round(stly_rn * (1 + blended_growth)), stly_rn)

            months.append({
                'month': target_date.strftime('%b %Y'),
                'year': target_year,
                'month_num': target_month,
                'stly_rn': stly_rn,
                'adjusted_rn': adjusted_rn,
                'adjustment_pct': round(blended_growth * 100, 1),
                'dominant_markets': dominant_markets[:5],
                'blended_growth': round(blended_growth * 100, 1),
            })

        return {'has_data': True, 'months': months}

    # ── Section 5: Seasonal Rate Guidance ────────────────────────────────

    def get_seasonal_rate_guidance(self, months_ahead=6):
        forecast = self.get_growth_adjusted_forecast(months_ahead)
        if not forecast.get('has_data'):
            return {'has_data': False}

        try:
            from platform_data.services import DestinationReportService
            dest_svc = DestinationReportService(self.country_code)
            heroes = dest_svc.get_offpeak_heroes(date.today().year)
            hero_countries = [h['country'] for h in heroes]
        except Exception:
            hero_countries = []

        months = []
        for m in forecast['months']:
            growth = m['blended_growth']

            if growth >= 15:
                level, direction, label = 'strong', 'increase', 'Consider rate increase'
            elif growth >= 5:
                level, direction, label = 'moderate', 'hold', 'Hold rates'
            elif growth >= -5:
                level, direction, label = 'soft', 'hold', 'Monitor closely'
            else:
                level, direction, label = 'weak', 'reduce', 'Promotional pricing'

            is_offpeak = m['month_num'] in [5, 6, 7, 8, 9]
            offpeak_targets = hero_countries[:3] if is_offpeak and level in ('weak', 'soft') else None

            dominants = m.get('dominant_markets', [])
            if dominants:
                top = dominants[0]
                if growth >= 10:
                    reason = f"{top['country']} +{top['yoy']}% leads strong demand"
                elif growth >= 0:
                    reason = f"Mixed signals — {top['country']} {'+' if top['yoy'] >= 0 else ''}{top['yoy']}%"
                else:
                    reason = f"Key markets declining — {top['country']} {top['yoy']}%"
            else:
                reason = 'Insufficient market data for this month'

            if offpeak_targets:
                reason += f". Target {', '.join(offpeak_targets)} for off-peak demand"

            months.append({
                'month': m['month'],
                'month_num': m['month_num'],
                'stly_rn': m['stly_rn'],
                'adjusted_rn': m['adjusted_rn'],
                'blended_growth': growth,
                'demand_level': level,
                'direction': direction,
                'direction_label': label,
                'reason': reason,
                'dominant_markets': dominants,
                'offpeak_targets': offpeak_targets,
            })

        return {'has_data': True, 'months': months}

    def get_market_momentum_alerts(self, max_alerts=3):
        prop_mix = self._get_property_market_mix()
        national_mix = self._get_national_market_mix()
        prop_total_rev = sum(m['revenue'] for m in prop_mix.values())

        alerts = []
        for country, nat_data in national_mix.items():
            yoy = nat_data.get('yoy_pct')
            if yoy is None:
                continue

            prop_data = prop_mix.get(country)
            prop_share = round(prop_data['revenue'] / prop_total_rev * 100, 1) if prop_data and prop_total_rev else 0

            if abs(yoy) >= 20 and nat_data['share'] >= 1.0:
                if yoy >= 20:
                    if prop_share >= 5:
                        alerts.append({
                            'type': 'growth', 'severity': 'info',
                            'message': f"{country} +{yoy}% YoY — {prop_share}% of your revenue, growing strongly",
                            'priority': nat_data['share'] * abs(yoy),
                        })
                    elif prop_share < 2 and nat_data['share'] >= 5:
                        alerts.append({
                            'type': 'opportunity', 'severity': 'info',
                            'message': f"{country} +{yoy}% YoY — {nat_data['share']}% of national arrivals but only {prop_share}% of your revenue",
                            'priority': nat_data['share'] * abs(yoy) * 0.8,
                        })
                elif yoy <= -15 and prop_share >= 5:
                    alerts.append({
                        'type': 'decline', 'severity': 'warning',
                        'message': f"{country} {yoy}% YoY — {prop_share}% of your revenue, market declining",
                        'priority': prop_share * abs(yoy),
                    })

        alerts.sort(key=lambda x: x.get('priority', 0), reverse=True)
        return [{'type': a['type'], 'severity': a['severity'], 'message': a['message']} for a in alerts[:max_alerts]]
