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
