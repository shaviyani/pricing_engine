"""
Import service for competitive set CSV/Excel uploads.

Expected columns:
    Competitor Name, BB Rate, HB Rate, FB Rate, Rating, Rooms,
    Position, Notes, Source, Date Surveyed, Active

Usage:
    from pricing.services.competitive_import_service import CompetitiveImportService

    svc = CompetitiveImportService(property=prop)
    result = svc.import_file('/path/to/file.csv')
"""

import pandas as pd
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


class CompetitiveImportService:

    # Column name mapping: CSV header -> model field
    COLUMN_MAP = {
        'competitor name': 'competitor_name',
        'competitor':      'competitor_name',
        'name':            'competitor_name',
        'bb rate':         'bb_rate',
        'bb rate ($)':     'bb_rate',
        'bb':              'bb_rate',
        'hb rate':         'hb_rate',
        'hb rate ($)':     'hb_rate',
        'hb':              'hb_rate',
        'fb rate':         'fb_rate',
        'fb rate ($)':     'fb_rate',
        'fb':              'fb_rate',
        'rating':          'rating',
        'rooms':           'total_rooms',
        'total rooms':     'total_rooms',
        'position':        'position',
        'notes':           'notes',
        'notes / differentiator': 'notes',
        'source':          'source',
        'date surveyed':   'surveyed_date',
        'surveyed':        'surveyed_date',
        'active':          'is_active',
    }

    POSITION_MAP = {
        'luxury': 'luxury',
        'premium': 'premium',
        'mid': 'mid',
        'mid-range': 'mid',
        'midrange': 'mid',
        'budget': 'budget',
        'economy': 'budget',
    }

    def __init__(self, property):
        self.property = property

    def import_file(self, file_path):
        """
        Import competitive set from CSV or Excel file.
        Upserts by competitor_name — existing records are updated,
        new ones created.

        Returns dict: {created, updated, skipped, errors}
        """
        from pricing.models import CompetitiveSet, MarketPosition

        path = Path(file_path)
        ext = path.suffix.lower()

        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path)
        elif ext == '.csv':
            df = pd.read_csv(file_path)
        else:
            return {'error': f'Unsupported file type: {ext}'}

        # Normalize column names
        df.columns = [c.strip().lower() for c in df.columns]

        # Map columns
        mapped = {}
        for csv_col in df.columns:
            model_field = self.COLUMN_MAP.get(csv_col)
            if model_field:
                mapped[model_field] = csv_col

        if 'competitor_name' not in mapped:
            return {'error': 'Missing required column: Competitor Name'}

        result = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': []}

        with transaction.atomic():
            for idx, row in df.iterrows():
                try:
                    name = str(row.get(mapped['competitor_name'], '')).strip()
                    if not name or name.lower() == 'nan':
                        result['skipped'] += 1
                        continue

                    defaults = self._parse_row(row, mapped)

                    obj, created = CompetitiveSet.objects.update_or_create(
                        hotel=self.property,
                        competitor_name=name,
                        defaults=defaults,
                    )

                    if created:
                        result['created'] += 1
                    else:
                        result['updated'] += 1

                except Exception as e:
                    result['errors'].append(f"Row {idx + 2}: {str(e)}")
                    result['skipped'] += 1

            # Recalculate market position
            mp, _ = MarketPosition.objects.get_or_create(hotel=self.property)
            stats = mp.recalculate_from_competitors()
            result['market_stats'] = {
                'avg_bb': float(stats['avg_bb'] or 0),
                'median_bb': float(stats['median_bb'] or 0),
                'count': stats['count'],
            }

        return result

    def _parse_row(self, row, mapped):
        """Parse a single CSV row into model field defaults."""
        defaults = {}

        for field, csv_col in mapped.items():
            if field == 'competitor_name':
                continue

            val = row.get(csv_col)

            if field in ('bb_rate', 'hb_rate', 'fb_rate', 'rating'):
                defaults[field] = self._parse_decimal(val)
            elif field == 'total_rooms':
                defaults[field] = self._parse_int(val, 0)
            elif field == 'position':
                defaults[field] = self._parse_position(val)
            elif field == 'surveyed_date':
                defaults[field] = self._parse_date(val)
            elif field == 'is_active':
                defaults[field] = self._parse_bool(val)
            else:
                defaults[field] = str(val).strip() if pd.notna(val) else ''

        return defaults

    def _parse_decimal(self, val):
        if pd.isna(val) or val == '' or val is None:
            return None
        try:
            clean = str(val).replace('$', '').replace(',', '').strip()
            return Decimal(clean)
        except (InvalidOperation, ValueError):
            return None

    def _parse_int(self, val, default=0):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def _parse_position(self, val):
        if pd.isna(val):
            return 'mid'
        return self.POSITION_MAP.get(str(val).strip().lower(), 'mid')

    def _parse_date(self, val):
        if pd.isna(val):
            return date.today()
        if isinstance(val, (date, datetime)):
            return val if isinstance(val, date) else val.date()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(str(val).strip(), fmt).date()
            except ValueError:
                continue
        return date.today()

    def _parse_bool(self, val):
        if pd.isna(val):
            return True
        return str(val).strip().lower() in ('yes', 'true', '1', 'y', 'active')
