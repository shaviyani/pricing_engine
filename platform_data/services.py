"""
Platform Data Services
======================

PlatformImportService: Upload, map, and import market data files.
MarketSignalService: Read API for tenant services to query market intelligence.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

from django.db import transaction
from django.db.models import Sum, Avg, Q
from django.utils import timezone

try:
    import pandas as pd
except ImportError:
    pd = None


# =============================================================================
# PLATFORM IMPORT SERVICE
# =============================================================================

class PlatformImportService:
    """
    Handles file upload, header reading, template matching, and import execution
    for platform-level market data.
    
    Follows the same pattern as pricing.ImportTemplateService.
    """
    
    ARRIVAL_REPORT_FIELDS = {
        'required': [
            {'field': 'origin_country', 'label': 'Country of Origin', 'type': 'text'},
            {'field': 'arrivals', 'label': 'Arrivals', 'type': 'number'},
        ],
        'recommended': [
            {'field': 'report_period', 'label': 'Report Period', 'type': 'date'},
            {'field': 'market_share_pct', 'label': 'Market Share %', 'type': 'number'},
            {'field': 'yoy_change_pct', 'label': 'YoY Change %', 'type': 'number'},
        ],
        'optional': [
            {'field': 'source_report', 'label': 'Source Report Name', 'type': 'text'},
        ],
    }
    
    EVENT_FIELDS = {
        'required': [
            {'field': 'name', 'label': 'Event Name', 'type': 'text'},
            {'field': 'start_date', 'label': 'Start Date', 'type': 'date'},
            {'field': 'end_date', 'label': 'End Date', 'type': 'date'},
        ],
        'recommended': [
            {'field': 'event_type', 'label': 'Event Type', 'type': 'text'},
            {'field': 'impact_level', 'label': 'Impact Level', 'type': 'text'},
            {'field': 'demand_uplift_pct', 'label': 'Demand Uplift %', 'type': 'number'},
        ],
        'optional': [
            {'field': 'source_markets', 'label': 'Source Markets', 'type': 'text'},
            {'field': 'recurring', 'label': 'Recurring (Y/N)', 'type': 'text'},
            {'field': 'notes', 'label': 'Notes', 'type': 'text'},
        ],
    }
    
    FIELD_DEFINITIONS = {
        'arrival_report': ARRIVAL_REPORT_FIELDS,
        'event': EVENT_FIELDS,
    }
    
    def read_headers(self, file_path, max_preview_rows=5):
        """Read CSV/Excel headers and preview rows."""
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()
        
        try:
            if suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path, nrows=max_preview_rows + 1)
            else:
                df = None
                for enc in ['utf-8', 'latin1', 'cp1252']:
                    try:
                        df = pd.read_csv(file_path, encoding=enc, index_col=False,
                                         nrows=max_preview_rows + 1)
                        break
                    except UnicodeDecodeError:
                        continue
                if df is None:
                    df = pd.read_csv(file_path, encoding='utf-8', errors='replace',
                                     index_col=False, nrows=max_preview_rows + 1)
            
            headers = [str(c).strip() for c in df.columns.tolist()]
            preview = []
            for _, row in df.head(max_preview_rows).iterrows():
                preview.append([str(v) if pd.notna(v) else '' for v in row.tolist()])
            
            # Row count
            if suffix in ['.xlsx', '.xls']:
                full_df = pd.read_excel(file_path, usecols=[0])
            else:
                full_df = pd.read_csv(file_path, encoding='utf-8', errors='replace',
                                       index_col=False, usecols=[0])
            
            return {
                'headers': headers,
                'preview': preview,
                'row_count': len(full_df),
                'file_type': suffix.lstrip('.'),
            }
        except Exception as e:
            return {'error': str(e)}
    
    def detect_template(self, headers, import_type):
        """Find best matching saved template for these headers."""
        from .models import PlatformImportTemplate
        
        candidates = []
        for t in PlatformImportTemplate.objects.filter(
            import_type=import_type, is_active=True
        ):
            score = t.matches_headers(headers)
            if score >= 0.7:
                candidates.append((t, score))
        
        if not candidates:
            return None
        
        candidates.sort(key=lambda x: (-x[1], -x[0].use_count))
        best, score = candidates[0]
        
        return {
            'template': {
                'id': best.id,
                'name': best.name,
                'column_map': best.column_map,
                'use_count': best.use_count,
            },
            'score': round(score, 2),
        }
    
    def get_field_definitions(self, import_type):
        """Return field definitions for the mapping UI."""
        return self.FIELD_DEFINITIONS.get(import_type, self.ARRIVAL_REPORT_FIELDS)
    
    def execute_import(self, file_path, column_map, import_type, country_code='MV',
                       report_period=None, template=None, user=None):
        """
        Execute a platform data import.
        
        Dispatches to the appropriate processor based on import_type.
        """
        from .models import PlatformFileImport
        
        file_path = Path(file_path)
        
        file_import = PlatformFileImport.objects.create(
            filename=file_path.name,
            import_type=import_type,
            country_code=country_code,
            template=template,
            column_map_used=column_map,
            uploaded_by=user,
            status='processing',
            started_at=timezone.now(),
        )
        
        if template:
            template.record_usage()
        
        try:
            # Read file
            suffix = file_path.suffix.lower()
            if suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path, encoding='utf-8', errors='replace', index_col=False)
            
            # Rename columns per mapping
            rename_map = {}
            for sys_field, csv_header in column_map.items():
                if csv_header:
                    rename_map[csv_header] = sys_field
            df = df.rename(columns=rename_map)
            
            file_import.rows_total = len(df)
            
            if import_type == 'arrival_report':
                result = self._import_arrivals(df, file_import, country_code, report_period)
            elif import_type == 'event':
                result = self._import_events(df, file_import, country_code)
            else:
                file_import.status = 'failed'
                file_import.errors = [{'row': 0, 'message': f'Unknown import type: {import_type}'}]
                file_import.completed_at = timezone.now()
                file_import.save()
                return {'success': False, 'error': f'Unknown import type: {import_type}'}
            
            file_import.completed_at = timezone.now()
            file_import.save()
            
            return {
                'success': True,
                'file_import_id': file_import.id,
                'rows_total': file_import.rows_total,
                'rows_created': file_import.rows_created,
                'rows_updated': file_import.rows_updated,
                'rows_skipped': file_import.rows_skipped,
                'errors': file_import.errors[:10],
            }
        except Exception as e:
            file_import.status = 'failed'
            file_import.errors = [{'row': 0, 'message': str(e)}]
            file_import.completed_at = timezone.now()
            file_import.save()
            return {'success': False, 'error': str(e)}
    
    def _import_arrivals(self, df, file_import, country_code, report_period=None):
        """Process arrival report rows."""
        from .models import MarketArrivalData
        
        created = updated = skipped = 0
        errors = []
        
        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-indexed + header
            
            try:
                origin = str(row.get('origin_country', '')).strip()
                if not origin or origin == 'nan':
                    skipped += 1
                    continue
                
                # Parse arrivals
                arrivals_raw = row.get('arrivals', 0)
                try:
                    arrivals = int(str(arrivals_raw).replace(',', '').replace(' ', ''))
                except (ValueError, TypeError):
                    arrivals = 0
                
                # Report period: from column, parameter, or default to current month
                period = None
                if 'report_period' in row and pd.notna(row.get('report_period')):
                    try:
                        period = pd.to_datetime(row['report_period']).date()
                        period = period.replace(day=1)
                    except Exception:
                        pass
                
                if period is None and report_period:
                    period = report_period
                
                if period is None:
                    period = date.today().replace(day=1)
                
                # Market share
                share = None
                if 'market_share_pct' in row and pd.notna(row.get('market_share_pct')):
                    try:
                        share = Decimal(str(row['market_share_pct']).replace('%', '').strip())
                    except (InvalidOperation, ValueError):
                        pass
                
                # YoY change
                yoy = None
                if 'yoy_change_pct' in row and pd.notna(row.get('yoy_change_pct')):
                    try:
                        yoy = Decimal(str(row['yoy_change_pct']).replace('%', '').strip())
                    except (InvalidOperation, ValueError):
                        pass
                
                source = str(row.get('source_report', '')).strip()
                if source == 'nan':
                    source = ''
                
                obj, was_created = MarketArrivalData.objects.update_or_create(
                    country_code=country_code,
                    report_period=period,
                    origin_country=origin,
                    defaults={
                        'arrivals': arrivals,
                        'market_share_pct': share,
                        'yoy_change_pct': yoy,
                        'source_report': source,
                        'file_import': file_import,
                    }
                )
                
                if was_created:
                    created += 1
                else:
                    updated += 1
            
            except Exception as e:
                errors.append({'row': row_num, 'message': str(e)})
                skipped += 1
        
        file_import.rows_created = created
        file_import.rows_updated = updated
        file_import.rows_skipped = skipped
        file_import.rows_processed = created + updated + skipped
        file_import.errors = errors
        file_import.status = 'completed' if not errors else 'completed_with_errors'
    
    def _import_events(self, df, file_import, country_code):
        """Process event calendar rows."""
        from .models import MarketEvent
        
        created = updated = skipped = 0
        errors = []
        
        for idx, row in df.iterrows():
            row_num = idx + 2
            
            try:
                name = str(row.get('name', '')).strip()
                if not name or name == 'nan':
                    skipped += 1
                    continue
                
                try:
                    start = pd.to_datetime(row.get('start_date')).date()
                    end = pd.to_datetime(row.get('end_date')).date()
                except Exception:
                    errors.append({'row': row_num, 'message': f'Invalid dates for event "{name}"'})
                    skipped += 1
                    continue
                
                event_type = str(row.get('event_type', 'other')).strip().lower()
                valid_types = dict(MarketEvent.EVENT_TYPE_CHOICES).keys()
                if event_type not in valid_types:
                    event_type = 'other'
                
                impact = str(row.get('impact_level', 'medium')).strip().lower()
                if impact not in ('high', 'medium', 'low'):
                    impact = 'medium'
                
                uplift = Decimal('0.00')
                if 'demand_uplift_pct' in row and pd.notna(row.get('demand_uplift_pct')):
                    try:
                        uplift = Decimal(str(row['demand_uplift_pct']).replace('%', '').strip())
                    except (InvalidOperation, ValueError):
                        pass
                
                sources = str(row.get('source_markets', '')).strip()
                if sources == 'nan':
                    sources = ''
                
                recurring_raw = str(row.get('recurring', '')).strip().lower()
                recurring = recurring_raw in ('y', 'yes', 'true', '1')
                
                notes = str(row.get('notes', '')).strip()
                if notes == 'nan':
                    notes = ''
                
                obj, was_created = MarketEvent.objects.update_or_create(
                    country_code=country_code,
                    name=name,
                    start_date=start,
                    defaults={
                        'end_date': end,
                        'event_type': event_type,
                        'impact_level': impact,
                        'demand_uplift_pct': uplift,
                        'source_markets': sources,
                        'recurring': recurring,
                        'notes': notes,
                    }
                )
                
                if was_created:
                    created += 1
                else:
                    updated += 1
            
            except Exception as e:
                errors.append({'row': row_num, 'message': str(e)})
                skipped += 1
        
        file_import.rows_created = created
        file_import.rows_updated = updated
        file_import.rows_skipped = skipped
        file_import.rows_processed = created + updated + skipped
        file_import.errors = errors
        file_import.status = 'completed' if not errors else 'completed_with_errors'


# =============================================================================
# GUEST COUNTRY NORMALIZATION (PMS → MoT standard names)
# =============================================================================

from platform_data.utils import normalize_country as _normalize_guest_country  # noqa: keep backward-compat alias


# =============================================================================
# MARKET SIGNAL SERVICE (Read API for tenant services)
# =============================================================================

class MarketSignalService:
    """
    Read-only service for tenant apps to query platform market data.
    
    Usage:
        from platform_data.services import MarketSignalService
        
        trends = MarketSignalService.get_arrival_trends('MV', 2026, 1)
        events = MarketSignalService.get_upcoming_events('MV', date.today(), date.today() + timedelta(90))
    """
    
    @staticmethod
    def get_arrival_trends(country_code, year=None, month=None):
        """
        Get arrival trends for a country, optionally filtered by period.
        
        Returns list of dicts: [{origin_country, arrivals, market_share_pct, yoy_change_pct}]
        """
        from .models import MarketArrivalData
        
        qs = MarketArrivalData.objects.filter(country_code=country_code)
        
        if year:
            qs = qs.filter(report_period__year=year)
        if month:
            qs = qs.filter(report_period__month=month)
        
        return list(qs.values(
            'origin_country', 'report_period', 'arrivals',
            'market_share_pct', 'yoy_change_pct'
        ).order_by('-report_period', '-arrivals'))
    
    @staticmethod
    def get_arrival_summary(country_code, report_period):
        """
        Get summary for a specific period.
        
        Returns: {total_arrivals, top_markets: [...], period}
        """
        from .models import MarketArrivalData
        
        qs = MarketArrivalData.objects.filter(
            country_code=country_code, report_period=report_period
        )
        
        total = qs.aggregate(total=Sum('arrivals'))['total'] or 0
        top = list(qs.order_by('-arrivals')[:10].values(
            'origin_country', 'arrivals', 'market_share_pct', 'yoy_change_pct'
        ))
        
        return {
            'total_arrivals': total,
            'top_markets': top,
            'period': report_period.isoformat(),
            'country_code': country_code,
        }
    
    @staticmethod
    def get_upcoming_events(country_code, start_date, end_date):
        """
        Get events in a date range for a country.
        
        Returns list of dicts with event details.
        """
        from .models import MarketEvent
        
        events = MarketEvent.objects.filter(
            Q(country_code=country_code) | Q(country_code='ALL'),
            is_active=True,
            start_date__lte=end_date,
            end_date__gte=start_date,
        ).order_by('start_date')
        
        return [{
            'id': e.id,
            'name': e.name,
            'event_type': e.event_type,
            'start_date': e.start_date.isoformat(),
            'end_date': e.end_date.isoformat(),
            'impact_level': e.impact_level,
            'demand_uplift_pct': float(e.demand_uplift_pct),
            'source_markets': e.get_source_markets_list(),
            'recurring': e.recurring,
            'duration_days': e.duration_days,
        } for e in events]
    
    @staticmethod
    def get_data_freshness(country_code):
        """
        Check how fresh the platform data is for a country.
        
        Returns: {latest_arrival_period, arrival_count, event_count, ...}
        """
        from .models import MarketArrivalData, MarketEvent
        
        latest_arrival = MarketArrivalData.objects.filter(
            country_code=country_code
        ).order_by('-report_period').first()
        
        active_events = MarketEvent.objects.filter(
            Q(country_code=country_code) | Q(country_code='ALL'),
            is_active=True, end_date__gte=date.today(),
        ).count()
        
        total_arrival_records = MarketArrivalData.objects.filter(
            country_code=country_code
        ).count()
        
        return {
            'country_code': country_code,
            'latest_arrival_period': latest_arrival.report_period.isoformat() if latest_arrival else None,
            'latest_arrival_source': latest_arrival.source_report if latest_arrival else None,
            'total_arrival_records': total_arrival_records,
            'upcoming_events': active_events,
        }

    # -----------------------------------------------------------------
    # Market Context (for property dashboard panel)
    # -----------------------------------------------------------------
    @staticmethod
    def get_market_context(country_code):
        """
        Dashboard-ready market context: current month KPIs + YoY change.

        Targets the current month first, falls back to the latest available.
        Returns dict consumed by the Market Context AJAX panel.
        """
        from .models import MarketKeyIndicator, MarketArrivalData

        current_month = date.today().replace(day=1)

        # Try current month first, then fall back to latest available
        latest = MarketKeyIndicator.objects.filter(
            country_code=country_code,
            report_period=current_month,
        ).first()

        if not latest:
            latest = MarketKeyIndicator.objects.filter(
                country_code=country_code
            ).order_by('-report_period').first()

        if not latest:
            # Fallback: derive totals from MarketArrivalData
            latest_arrival = MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=current_month,
            ).first()

            if not latest_arrival:
                latest_arrival = MarketArrivalData.objects.filter(
                    country_code=country_code
                ).order_by('-report_period').first()

            if not latest_arrival:
                return {'has_data': False}

            latest_period = latest_arrival.report_period
            total = MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=latest_period
            ).aggregate(total=Sum('arrivals'))['total'] or 0

            # Check for prior year
            prior_period = date(latest_period.year - 1, latest_period.month, 1)
            prior_total = MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=prior_period
            ).aggregate(total=Sum('arrivals'))['total']

            yoy_arrivals = None
            if prior_total and prior_total > 0:
                yoy_arrivals = round((total - prior_total) / prior_total * 100, 1)

            top_markets = list(
                MarketArrivalData.objects.filter(
                    country_code=country_code,
                    report_period=latest_period,
                ).order_by('-arrivals')[:5].values(
                    'origin_country', 'arrivals', 'market_share_pct', 'yoy_change_pct'
                )
            )
            for m in top_markets:
                if m['market_share_pct'] is not None:
                    m['market_share_pct'] = float(m['market_share_pct'])
                if m['yoy_change_pct'] is not None:
                    m['yoy_change_pct'] = float(m['yoy_change_pct'])

            return {
                'has_data': True,
                'period': latest_period.isoformat(),
                'period_label': latest_period.strftime('%B %Y'),
                'total_arrivals': total,
                'occupancy_rate': None,
                'avg_stay_days': None,
                'total_bed_nights': None,
                'yoy_arrivals_pct': yoy_arrivals,
                'yoy_occupancy_pp': None,
                'source_report': latest_arrival.source_report,
                'top_markets': top_markets,
            }

        # YoY comparison
        prev_period = date(
            latest.report_period.year - 1,
            latest.report_period.month,
            latest.report_period.day,
        )
        prev = MarketKeyIndicator.objects.filter(
            country_code=country_code,
            report_period=prev_period,
        ).first()

        yoy_arrivals = None
        if prev and prev.total_arrivals:
            yoy_arrivals = round(
                (latest.total_arrivals - prev.total_arrivals) / prev.total_arrivals * 100, 1
            )

        yoy_occupancy = None
        if prev and prev.occupancy_rate and latest.occupancy_rate:
            yoy_occupancy = round(float(latest.occupancy_rate - prev.occupancy_rate), 1)

        # Top 5 source markets for the latest period
        top_markets = list(
            MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=latest.report_period,
            ).order_by('-arrivals')[:5].values(
                'origin_country', 'arrivals', 'market_share_pct', 'yoy_change_pct'
            )
        )
        # Convert Decimals to floats for JSON serialization
        for m in top_markets:
            if m['market_share_pct'] is not None:
                m['market_share_pct'] = float(m['market_share_pct'])
            if m['yoy_change_pct'] is not None:
                m['yoy_change_pct'] = float(m['yoy_change_pct'])

        return {
            'has_data': True,
            'period': latest.report_period.isoformat(),
            'period_label': latest.report_period.strftime('%B %Y'),
            'total_arrivals': latest.total_arrivals,
            'occupancy_rate': float(latest.occupancy_rate) if latest.occupancy_rate else None,
            'avg_stay_days': float(latest.avg_stay_days) if latest.avg_stay_days else None,
            'total_bed_nights': latest.total_bed_nights,
            'yoy_arrivals_pct': yoy_arrivals,
            'yoy_occupancy_pp': yoy_occupancy,
            'source_report': latest.source_report,
            'top_markets': top_markets,
        }

    # -----------------------------------------------------------------
    # Market YoY Factor (for forecast formula)
    # -----------------------------------------------------------------
    @staticmethod
    def get_market_yoy_factor(country_code):
        """
        Returns a multiplicative factor for the forecast formula.
        Capped to [0.85, 1.15] to avoid wild swings.
        """
        from .models import MarketKeyIndicator, MarketArrivalData

        # Try MarketKeyIndicator first
        latest = MarketKeyIndicator.objects.filter(
            country_code=country_code
        ).order_by('-report_period').first()

        if latest:
            prev_period = date(latest.report_period.year - 1, latest.report_period.month, 1)
            prev = MarketKeyIndicator.objects.filter(
                country_code=country_code, report_period=prev_period
            ).first()

            if prev and prev.total_arrivals:
                yoy_pct = (latest.total_arrivals - prev.total_arrivals) / prev.total_arrivals * 100
                factor = 1.0 + (yoy_pct / 200)
                return max(0.85, min(1.15, round(factor, 4)))

        # Fallback: aggregate from MarketArrivalData
        latest_arrival = MarketArrivalData.objects.filter(
            country_code=country_code
        ).order_by('-report_period').first()

        if not latest_arrival:
            return 1.0

        latest_period = latest_arrival.report_period
        current_total = MarketArrivalData.objects.filter(
            country_code=country_code, report_period=latest_period
        ).aggregate(total=Sum('arrivals'))['total'] or 0

        prior_period = date(latest_period.year - 1, latest_period.month, 1)
        prior_total = MarketArrivalData.objects.filter(
            country_code=country_code, report_period=prior_period
        ).aggregate(total=Sum('arrivals'))['total']

        if not prior_total or prior_total == 0:
            return 1.0

        yoy_pct = (current_total - prior_total) / prior_total * 100
        factor = 1.0 + (yoy_pct / 200)
        return max(0.85, min(1.15, round(factor, 4)))

    # -----------------------------------------------------------------
    # Property vs Market comparison (guest country mix)
    # -----------------------------------------------------------------
    @staticmethod
    def get_property_market_comparison(country_code, report_period, prop):
        """
        Compare property's guest country mix vs national market share.

        Args:
            country_code: e.g. 'MV'
            report_period: date — the MoT period to compare against
            prop: Property instance

        Returns:
            list of dicts: [{country, national_arrivals, national_share,
                             prop_bookings, prop_share, gap}, ...]
        """
        from .models import MarketArrivalData
        from pricing.models.analytics import Reservation
        from django.db.models import Count

        # National top 10 for this period
        national = list(
            MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=report_period,
            ).order_by('-arrivals')[:10].values_list(
                'origin_country', 'arrivals', 'market_share_pct'
            )
        )

        if not national:
            return []

        # Property guest countries (last 12 months of arrivals)
        year_ago = report_period - timedelta(days=365)
        prop_qs = Reservation.objects.filter(
            hotel=prop,
            status__in=Reservation.ACTIVE_STATUSES,
            arrival_date__gte=year_ago,
            guest__isnull=False,
            guest__country__gt='',
        ).values('guest__country').annotate(
            bookings=Count('id')
        )

        # Build a lookup: normalized_name → bookings
        prop_by_country = {}
        total_prop = 0
        for row in prop_qs:
            raw = (row['guest__country'] or '').strip()
            if not raw:
                continue
            normalized = _normalize_guest_country(raw)
            prop_by_country[normalized] = prop_by_country.get(normalized, 0) + row['bookings']
            total_prop += row['bookings']

        # Build comparison rows
        comparison = []
        for origin_country, arrivals, share_pct in national:
            nat_share = float(share_pct) if share_pct else 0.0

            # Match against property data
            prop_bookings = prop_by_country.get(origin_country, 0)
            prop_share = round(prop_bookings / total_prop * 100, 1) if total_prop > 0 else 0.0
            gap = round(prop_share - nat_share, 1)

            comparison.append({
                'country': origin_country,
                'national_arrivals': arrivals,
                'national_share': nat_share,
                'prop_bookings': prop_bookings,
                'prop_share': prop_share,
                'gap': gap,
            })

        return comparison

    # -----------------------------------------------------------------
    # Property-Specific Demand Index
    # -----------------------------------------------------------------
    @staticmethod
    def get_property_demand_index(prop, country_code='MV', direction='backward'):
        """
        Calculate property-specific demand index weighted by guest country mix.

        Args:
            prop: Property instance
            country_code: destination country (default 'MV')
            direction: 'backward' (last 12 months guest mix) or
                       'forward' (future OTB guest mix)

        Returns dict:
            factor: float, e.g. 1.003 for +0.3% weighted growth
            components: list of {country, prop_share, country_yoy, contribution}
            national_factor: float, the unweighted national factor for comparison
            label: str, human-readable description
            has_data: bool
        """
        from .models import MarketArrivalData
        from pricing.models.analytics import Reservation
        from django.db.models import Sum

        today = date.today()

        # --- Step 1: Get property guest mix ---
        if direction == 'forward':
            res_qs = Reservation.objects.filter(
                hotel=prop,
                arrival_date__gte=today,
                status__in=Reservation.FUTURE_STATUSES
            )
            mix_label = 'future bookings'
        else:
            twelve_months_ago = date(today.year - 1, today.month, today.day)
            res_qs = Reservation.objects.filter(
                hotel=prop,
                arrival_date__gte=twelve_months_ago,
                arrival_date__lt=today,
                status__in=Reservation.ACTIVE_STATUSES
            )
            mix_label = 'last 12 months'

        total_nights = res_qs.aggregate(t=Sum('nights'))['t'] or 0
        if total_nights == 0:
            national_factor = MarketSignalService.get_market_yoy_factor(country_code)
            return {
                'factor': national_factor,
                'components': [],
                'national_factor': national_factor,
                'label': 'National average (no property guest data)',
                'has_data': False,
            }

        by_country = res_qs.exclude(
            guest__country__isnull=True
        ).exclude(
            guest__country__in=['', '-']
        ).values(
            'guest__country'
        ).annotate(
            rn=Sum('nights')
        ).order_by('-rn')

        # Normalize and aggregate
        guest_mix = {}  # normalized_name → room_nights
        for row in by_country:
            normalized = _normalize_guest_country(row['guest__country'])
            guest_mix[normalized] = guest_mix.get(normalized, 0) + row['rn']

        # Unknown/unmapped nights
        known_nights = sum(guest_mix.values())
        unknown_nights = total_nights - known_nights

        # --- Step 2: Get per-country YoY from MoT ---
        country_yoy = MarketSignalService._get_per_country_yoy(country_code)
        national_factor = MarketSignalService.get_market_yoy_factor(country_code)

        # --- Step 3: Calculate weighted index ---
        weighted_sum = 0.0
        components = []

        for country_name, nights in sorted(guest_mix.items(), key=lambda x: x[1], reverse=True):
            share = nights / total_nights

            # Get this country's YoY factor
            if country_name in country_yoy:
                c_yoy_pct = country_yoy[country_name]
                c_factor = 1 + (c_yoy_pct / 100)
                source = 'MoT'
            else:
                # Country not in MoT data — use national average
                c_factor = national_factor
                c_yoy_pct = (national_factor - 1) * 100
                source = 'national avg'

            contribution = share * c_factor
            weighted_sum += contribution

            components.append({
                'country': country_name,
                'nights': nights,
                'prop_share': round(share * 100, 1),
                'country_yoy': round(c_yoy_pct, 1),
                'factor': round(c_factor, 3),
                'contribution': round(contribution, 4),
                'source': source,
            })

        # Unknown countries: apply national average
        if unknown_nights > 0:
            unknown_share = unknown_nights / total_nights
            weighted_sum += unknown_share * national_factor
            components.append({
                'country': 'Other/Unknown',
                'nights': unknown_nights,
                'prop_share': round(unknown_share * 100, 1),
                'country_yoy': round((national_factor - 1) * 100, 1),
                'factor': round(national_factor, 3),
                'contribution': round(unknown_share * national_factor, 4),
                'source': 'national avg',
            })

        # Cap at ±25%
        weighted_sum = max(0.75, min(1.25, weighted_sum))

        prop_pct = round((weighted_sum - 1) * 100, 1)
        nat_pct = round((national_factor - 1) * 100, 1)
        sign = '+' if prop_pct >= 0 else ''
        nat_sign = '+' if nat_pct >= 0 else ''

        return {
            'factor': round(weighted_sum, 4),
            'components': components,
            'national_factor': national_factor,
            'label': 'Property index: {}{:.1f}% (vs national {}{:.1f}%)'.format(
                sign, prop_pct, nat_sign, nat_pct
            ),
            'has_data': True,
            'direction': direction,
            'mix_label': mix_label,
        }

    @staticmethod
    def _get_per_country_yoy(country_code='MV'):
        """
        Get per-country YoY growth rates from the most recent MoT period pair.

        Tries stored yoy_change_pct first. Falls back to computing from
        two periods' arrivals.

        Returns dict: {country_name: yoy_pct, ...}
        e.g. {'Russia': -8.2, 'Italy': 3.1, 'China': 22.3}
        """
        from .models import MarketArrivalData

        # Find latest period
        latest = MarketArrivalData.objects.filter(
            country_code=country_code
        ).order_by('-report_period').first()

        if not latest:
            return {}

        latest_period = latest.report_period
        prior_period = date(latest_period.year - 1, latest_period.month, 1)

        # Try stored yoy_change_pct from latest period
        latest_rows = MarketArrivalData.objects.filter(
            country_code=country_code,
            report_period=latest_period
        ).values('origin_country', 'arrivals', 'yoy_change_pct')

        result = {}
        needs_compute = []

        for row in latest_rows:
            country = row['origin_country']
            if row['yoy_change_pct'] is not None:
                result[country] = float(row['yoy_change_pct'])
            else:
                needs_compute.append((country, row['arrivals']))

        # Compute YoY for countries missing yoy_change_pct
        if needs_compute:
            prior_rows = MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=prior_period
            ).values('origin_country', 'arrivals')

            prior_map = {r['origin_country']: r['arrivals'] for r in prior_rows}

            for country, current_arrivals in needs_compute:
                prior_arrivals = prior_map.get(country)
                if prior_arrivals and prior_arrivals > 0:
                    yoy = (current_arrivals - prior_arrivals) / prior_arrivals * 100
                    result[country] = round(yoy, 1)

        return result

    @staticmethod
    def _get_per_country_yoy_for_month(year, month, country_code='MV'):
        """
        Get per-country YoY for a specific month.

        E.g., for July 2026: compare July 2025 vs July 2024 per country.
        Falls back to latest available period if specific month pair not available.
        """
        from .models import MarketArrivalData

        target = date(year, month, 1)
        prior = date(year - 1, month, 1)

        # Try specific month pair
        target_rows = MarketArrivalData.objects.filter(
            country_code=country_code, report_period=target
        ).values('origin_country', 'arrivals')

        prior_rows = MarketArrivalData.objects.filter(
            country_code=country_code, report_period=prior
        ).values('origin_country', 'arrivals')

        if target_rows.exists() and prior_rows.exists():
            prior_map = {r['origin_country']: r['arrivals'] for r in prior_rows}
            result = {}
            for r in target_rows:
                p = prior_map.get(r['origin_country'])
                if p and p > 0:
                    result[r['origin_country']] = round(
                        (r['arrivals'] - p) / p * 100, 1
                    )
            return result

        # Fall back to latest period's per-country YoY
        return MarketSignalService._get_per_country_yoy(country_code)

    # -----------------------------------------------------------------
    # Backfill helper
    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    # Monthly Demand Index (per-month, per-country weighted)
    # -----------------------------------------------------------------

    @staticmethod
    def _get_per_country_yoy_for_month_tiered(country_code, origin_country, year, month):
        """
        Get YoY arrival change for a specific source market in a specific month.

        3-tier fallback:
          Tier 1: Both month M and M-12 exist in MarketArrivalData -> compute actual YoY
          Tier 2: Only M-12 exists -> use stored yoy_change_pct from latest available period
          Tier 3: Neither -> use latest period's yoy_change_pct for this origin country

        Returns:
            dict: {yoy_pct: float, source: str, tier: int}
        """
        from .models import MarketArrivalData

        target_period = date(year, month, 1)
        prior_period = date(year - 1, month, 1)

        # Tier 1: Both periods exist -> compute actual
        current = MarketArrivalData.objects.filter(
            country_code=country_code,
            origin_country=origin_country,
            report_period=target_period
        ).first()

        prior = MarketArrivalData.objects.filter(
            country_code=country_code,
            origin_country=origin_country,
            report_period=prior_period
        ).first()

        if current and prior and prior.arrivals > 0:
            yoy = (current.arrivals - prior.arrivals) / prior.arrivals * 100
            return {
                'yoy_pct': round(yoy, 1),
                'source': f'Actual {target_period:%b %Y} vs {prior_period:%b %Y}',
                'tier': 1,
            }

        # Tier 2: Only prior period exists -> use stored yoy_change_pct
        if prior and prior.yoy_change_pct is not None:
            return {
                'yoy_pct': float(prior.yoy_change_pct),
                'source': f'Stored YoY from {prior_period:%b %Y}',
                'tier': 2,
            }

        # Tier 3: Latest available record for this origin country
        latest = MarketArrivalData.objects.filter(
            country_code=country_code,
            origin_country=origin_country,
            yoy_change_pct__isnull=False
        ).order_by('-report_period').first()

        if latest:
            return {
                'yoy_pct': float(latest.yoy_change_pct),
                'source': f'Latest available ({latest.report_period:%b %Y})',
                'tier': 3,
            }

        return {'yoy_pct': 0.0, 'source': 'No data', 'tier': 0}

    @staticmethod
    def _get_national_yoy_for_month(country_code, year, month):
        """
        Get national total arrivals YoY for a specific month.

        Returns:
            dict: {yoy_pct: float, source: str} or None if no data
        """
        from .models import MarketKeyIndicator

        target_period = date(year, month, 1)
        prior_period = date(year - 1, month, 1)

        current = MarketKeyIndicator.objects.filter(
            country_code=country_code,
            report_period=target_period
        ).first()

        prior = MarketKeyIndicator.objects.filter(
            country_code=country_code,
            report_period=prior_period
        ).first()

        if current and prior and prior.total_arrivals > 0:
            yoy = (current.total_arrivals - prior.total_arrivals) / prior.total_arrivals * 100
            return {
                'yoy_pct': round(yoy, 1),
                'source': f'MoT {target_period:%b %Y} vs {prior_period:%b %Y}',
            }

        # Fallback: latest available national comparison
        latest = MarketKeyIndicator.objects.filter(
            country_code=country_code,
        ).order_by('-report_period').first()

        if latest:
            prev = MarketKeyIndicator.objects.filter(
                country_code=country_code,
                report_period=date(
                    latest.report_period.year - 1,
                    latest.report_period.month,
                    latest.report_period.day
                )
            ).first()

            if prev and prev.total_arrivals > 0:
                yoy = (latest.total_arrivals - prev.total_arrivals) / prev.total_arrivals * 100
                return {
                    'yoy_pct': round(yoy, 1),
                    'source': f'Latest: {latest.report_period:%b %Y} vs prior year',
                }

        return None

    @staticmethod
    def _get_property_guest_mix_for_month(prop, year, month):
        """
        Get property's guest country distribution for a specific month.
        Combines current year + prior year data for the same calendar month.
        Uses normalized country names for MoT matching.

        Returns:
            list of dict: [{country: str, nights: int, share: float}]
            share is decimal (0.35 = 35%)
        """
        from pricing.models import Reservation
        from platform_data.utils import normalize_country

        periods = [date(year, month, 1)]
        if year > 1:
            periods.append(date(year - 1, month, 1))

        qs = Reservation.objects.filter(
            hotel=prop,
            arrival_date__month=month,
            arrival_date__year__in=[p.year for p in periods],
            status__in=['confirmed', 'checked_in', 'checked_out'],
            guest__country__isnull=False,
        ).exclude(
            guest__country=''
        ).exclude(
            guest__country='-'
        ).values(
            'guest__country'
        ).annotate(
            nights=Sum('nights')
        ).order_by('-nights')

        total_nights = sum(row['nights'] or 0 for row in qs)
        if total_nights == 0:
            return []

        result = []
        for row in qs:
            normalized = normalize_country(row['guest__country'])
            nights = row['nights'] or 0
            result.append({
                'country': normalized,
                'nights': nights,
                'share': round(nights / total_nights, 4),
            })

        # Merge duplicates after normalization
        merged = {}
        for item in result:
            key = item['country']
            if key in merged:
                merged[key]['nights'] += item['nights']
                merged[key]['share'] += item['share']
            else:
                merged[key] = item.copy()

        return sorted(merged.values(), key=lambda x: -x['nights'])

    @staticmethod
    def get_monthly_demand_indices(prop, months):
        """
        Calculate property-weighted demand index for each month.

        Args:
            prop: Property instance
            months: list of date objects (first day of each month)

        Returns:
            dict keyed by date: {
                date(2026,3,1): {
                    'factor': 0.972,
                    'pct': -2.8,
                    'national_pct': 4.6,
                    'top_driver': 'Russia -12.0%',
                    'source': 'T1+T3 blend . 5 markets',
                    'components': [...],
                    'has_data': True,
                },
            }
        """
        country_code = getattr(prop, 'country_code', 'MV') or 'MV'
        result = {}

        for month_date in months:
            year = month_date.year
            month = month_date.month

            guest_mix = MarketSignalService._get_property_guest_mix_for_month(
                prop, year, month
            )

            if not guest_mix:
                national = MarketSignalService._get_national_yoy_for_month(
                    country_code, year, month
                )
                if national:
                    half_pct = national['yoy_pct'] / 2
                    factor = 1.0 + (half_pct / 100)
                    factor = max(0.85, min(1.15, round(factor, 4)))
                    result[month_date] = {
                        'factor': factor,
                        'pct': round(half_pct, 1),
                        'national_pct': national['yoy_pct'],
                        'top_driver': f"National {national['yoy_pct']:+.1f}%",
                        'source': f"National only — {national['source']}",
                        'components': [],
                        'has_data': True,
                    }
                else:
                    result[month_date] = {
                        'factor': 1.0,
                        'pct': 0.0,
                        'national_pct': None,
                        'top_driver': 'No data',
                        'source': 'No MoT data available',
                        'components': [],
                        'has_data': False,
                    }
                continue

            # Calculate weighted index from guest mix
            components = []
            weighted_sum = 0.0
            covered_share = 0.0
            max_tier = 0

            for market in guest_mix:
                country_yoy = MarketSignalService._get_per_country_yoy_for_month_tiered(
                    country_code, market['country'], year, month
                )

                impact = market['share'] * country_yoy['yoy_pct']
                weighted_sum += impact
                covered_share += market['share']
                max_tier = max(max_tier, country_yoy['tier'])

                components.append({
                    'country': market['country'],
                    'share': round(market['share'] * 100, 1),
                    'yoy': country_yoy['yoy_pct'],
                    'impact': round(impact, 2),
                    'tier': country_yoy['tier'],
                    'source': country_yoy['source'],
                })

            # For uncovered share, apply national rate
            national = MarketSignalService._get_national_yoy_for_month(
                country_code, year, month
            )
            national_pct = national['yoy_pct'] if national else 0.0

            uncovered = 1.0 - covered_share
            if uncovered > 0.01 and national:
                weighted_sum += uncovered * national_pct
                components.append({
                    'country': 'Others (national avg)',
                    'share': round(uncovered * 100, 1),
                    'yoy': national_pct,
                    'impact': round(uncovered * national_pct, 2),
                    'tier': 0,
                    'source': national['source'] if national else '',
                })

            # Half-weight damping
            damped_pct = weighted_sum / 2
            factor = 1.0 + (damped_pct / 100)
            factor = max(0.75, min(1.25, round(factor, 4)))

            # Top driver
            top = max(components, key=lambda c: abs(c['impact'])) if components else None
            top_driver = f"{top['country']} {top['yoy']:+.1f}%" if top else 'No data'

            # Source label
            tiers_used = set(c['tier'] for c in components if c['tier'] > 0)
            tier_label = '+'.join(f'T{t}' for t in sorted(tiers_used)) if tiers_used else 'national'

            result[month_date] = {
                'factor': factor,
                'pct': round(damped_pct, 1),
                'national_pct': national_pct,
                'top_driver': top_driver,
                'source': f'{tier_label} blend \u00b7 {len(guest_mix)} markets',
                'components': components,
                'has_data': True,
            }

        return result

    @staticmethod
    def get_monthly_demand_index(prop, target_month):
        """
        Get demand index for a single month.
        Convenience wrapper around get_monthly_demand_indices.

        Args:
            prop: Property instance
            target_month: date (first day of month)

        Returns:
            dict with factor, pct, national_pct, top_driver, source, components, has_data
        """
        month_date = date(target_month.year, target_month.month, 1)
        indices = MarketSignalService.get_monthly_demand_indices(prop, [month_date])
        return indices.get(month_date, {
            'factor': 1.0, 'pct': 0.0, 'national_pct': None,
            'top_driver': 'No data', 'source': '', 'components': [], 'has_data': False,
        })

    # -----------------------------------------------------------------
    # Backfill helper
    # -----------------------------------------------------------------
    @staticmethod
    def backfill_key_indicators(country_code='MV'):
        """
        One-time backfill: create MarketKeyIndicator rows from existing
        MarketArrivalData by summing arrivals per period.

        Run once after fixing the import, then re-import PDFs to get
        occupancy/stay/bed nights populated.

        Usage:
            from platform_data.services import MarketSignalService
            MarketSignalService.backfill_key_indicators('MV')
        """
        from .models import MarketArrivalData, MarketKeyIndicator

        periods = MarketArrivalData.objects.filter(
            country_code=country_code
        ).values('report_period').annotate(
            total=Sum('arrivals')
        ).order_by('report_period')

        created = 0
        for p in periods:
            _, was_created = MarketKeyIndicator.objects.get_or_create(
                country_code=country_code,
                report_period=p['report_period'],
                defaults={
                    'total_arrivals': p['total'],
                    'source_report': 'Backfilled from MarketArrivalData',
                }
            )
            if was_created:
                created += 1

        return created
