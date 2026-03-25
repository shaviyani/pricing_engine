"""
MoT PDF Parser Service
======================

Parses Maldives Ministry of Tourism PDF reports into structured data
for import into MarketArrivalData.

Handles two report formats:
1. Monthly Report (e.g., "January 2025") — Full country breakdown from Table 1
2. Daily Update (e.g., "Daily Updates | 16 February 2026") — Top 10 markets + totals

Usage:
    from platform_data.mot_parser import MoTReportParser

    parser = MoTReportParser()
    result = parser.parse_pdf('/path/to/report.pdf')
    # result = {
    #     'report_type': 'monthly' | 'daily',
    #     'report_month': 'January',
    #     'report_year': 2025,
    #     'report_period': date(2025, 1, 1),
    #     'total_arrivals': 214863,
    #     'countries': [
    #         {'country': 'China', 'arrivals': 35948, 'pct_change': 80.7, 'market_share': 16.7, 'ranking': 1},
    #         ...
    #     ],
    #     'key_indicators': {...},  # monthly only
    #     'source': 'Ministry of Tourism & Environment',
    # }
"""

import re
from datetime import date
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9,
    'oct': 10, 'nov': 11, 'dec': 12,
}

# Regions and sub-regions to skip (not individual countries)
REGION_HEADERS = {
    'europe', 'central / eastern europe', 'central/eastern europe',
    'northern europe', 'southern europe', 'western europe',
    'east mediterranean europe',
    'asia & the pacific', 'asia and the pacific',
    'north east asia', 'south east asia', 'south asia', 'oceania',
    'americas', 'middle east', 'africa', 'others',
    'total tourist arrivals', 'total',
}

# Known "Other" aggregates to skip
OTHER_PATTERNS = re.compile(
    r'^other\s|^others$|^un passport|^other / not stated|^not stated|'
    r'^total tourist|^total$|^average for',
    re.IGNORECASE
)


def parse_number(s):
    """Parse a number string like '35,948' or '80.7' or '-4.6'."""
    if not s or s.strip() in ('', '-', 'N/A', 'nan'):
        return None
    s = s.strip().replace(',', '').replace(' ', '')
    try:
        if '.' in s:
            return float(s)
        return int(s)
    except ValueError:
        return None


class MoTReportParser:
    """
    Parses Maldives Ministry of Tourism PDF reports.
    """

    def parse_pdf(self, file_path):
        """
        Main entry point. Detects report type and dispatches to appropriate parser.

        Returns dict with parsed data or {'error': '...'} on failure.
        """
        if pdfplumber is None:
            return {'error': 'pdfplumber not installed. Run: pip install pdfplumber'}

        file_path = Path(file_path)
        if not file_path.exists():
            return {'error': f'File not found: {file_path}'}

        try:
            pdf = pdfplumber.open(str(file_path))
        except Exception as e:
            return {'error': f'Cannot open PDF: {e}'}

        num_pages = len(pdf.pages)

        # Read first page text to detect type
        first_text = pdf.pages[0].extract_text() or ''

        if 'Daily Updates' in first_text or 'Daily Update' in first_text:
            return self._parse_daily_update(pdf, first_text, file_path.name)

        # Monthly report detection — scan up to first 7 pages
        scan_text = '\n'.join(p.extract_text() or '' for p in pdf.pages[:7])
        scan_lower = scan_text.lower()

        if 'arrivals by nationality' in scan_lower:
            return self._parse_monthly_report(pdf, file_path.name)
        elif 'top 10 markets' in scan_lower:
            return self._parse_daily_update(pdf, scan_text, file_path.name)
        else:
            return {'error': 'Unrecognized MoT report format'}

    # =========================================================================
    # MONTHLY REPORT PARSER
    # =========================================================================

    def _parse_monthly_report(self, pdf, filename):
        """
        Parse the full monthly report (Table 1: Tourist Arrivals by Nationality).

        Pages 2-3 contain the nationality table.
        Page 6 has key indicators.
        """
        # Detect report period from page 1 or 2
        page1_text = pdf.pages[0].extract_text() or ''
        page2_text = pdf.pages[1].extract_text() or ''

        report_month, report_year = self._detect_period(page1_text + '\n' + page2_text)

        if not report_month or not report_year:
            return {'error': 'Could not detect report period from PDF'}

        month_num = MONTH_MAP.get(report_month.lower())
        if not month_num:
            return {'error': f'Unknown month: {report_month}'}

        report_period = date(report_year, month_num, 1)

        # Parse Table 1 from pages 2 and 3 (and possibly more)
        countries = []
        total_arrivals = 0

        for page_idx in range(1, min(len(pdf.pages), 9)):
            page_text = pdf.pages[page_idx].extract_text() or ''

            # Skip pages that don't contain nationality data
            if 'Enhanced Data Coverage' in page_text:
                continue
            if 'Key Indicators' in page_text and 'Nationality' not in page_text:
                continue

            # Stop if we've passed the nationality table entirely
            if any(t in page_text for t in ['Table 3', 'Table 4', 'Table 5', 'Country of Residence', 'Age Groups']):
                break

            parsed = self._parse_nationality_table(page_text, report_year)
            countries.extend(parsed)

            # Check for total — always use the monthly figure (first pair)
            total_match = re.search(
                r'TOTAL\s+TOURIST\s+ARRIVALS\s+(.+)',
                page_text
            )
            if total_match:
                # Extract integer-like tokens (skip decimals like 7.4, 100.0)
                tokens = re.findall(r'-?[\d,]+\.?\d*', total_match.group(1))
                int_vals = []
                for t in tokens:
                    try:
                        v = int(t.replace(',', ''))
                        int_vals.append(v)
                    except ValueError:
                        pass

                # First pair is always the monthly figures: prior, current
                if len(int_vals) >= 2:
                    total_arrivals = int_vals[1]
                elif int_vals:
                    total_arrivals = int_vals[0]

        # Parse key indicators from Table 5 (usually page 6)
        key_indicators = {}
        for page_idx in range(1, min(len(pdf.pages), 13)):
            page_text = pdf.pages[page_idx].extract_text() or ''
            if 'KEY INDICATORS' in page_text.upper() or 'Key Indicators' in page_text:
                key_indicators = self._parse_key_indicators(page_text, report_year)
                break

        # If we didn't find total from the table, sum countries
        if total_arrivals == 0 and countries:
            total_arrivals = sum(c['arrivals'] for c in countries if c['arrivals'])

        return {
            'report_type': 'monthly',
            'report_month': report_month,
            'report_year': report_year,
            'report_period': report_period,
            'total_arrivals': total_arrivals,
            'countries': countries,
            'country_count': len(countries),
            'key_indicators': key_indicators,
            'source': f'MoT Monthly Report {report_month} {report_year}',
            'filename': filename,
        }

    def _parse_nationality_table(self, text, report_year):
        """
        Parse country rows from Table 1/2 text.

        Handles two column layouts but ALWAYS extracts the monthly columns:

        Single-month format (e.g., January report):
            Country prior_yr current_yr %change %share [ranking]
            China 19,895 35,948 80.7 16.7 1

        Cumulative format (e.g., December report with Jan-Dec totals):
            Country dec_2024 dec_2025 %chg %share jan_dec_2024 jan_dec_2025 %chg %share ranking
            China 12,063 16,950 40.5 7.6 263,340 329,110 25.0 14.6 1
            → We extract dec_2025 (16,950), not the YTD figure.
        """
        countries = []

        # Normalize Unicode dashes to ASCII (some PDFs use U+2010, U+2011, U+2012, U+2013, U+2212)
        text = re.sub(r'[\u2010\u2011\u2012\u2013\u2014\u2212\u00AD]', '-', text)

        lines = text.split('\n')

        # Detect if this is cumulative format by checking the header
        is_cumulative = bool(re.search(
            r'January\s*-\s*(?:December|November|October|September|August|July|June|May|April|March|February)',
            text
        ))

        # Regex for cumulative format: match all 9+ number groups, extract monthly (first set)
        # Country [*] month_prior month_current %chg %share ytd_prior ytd_current %chg %share [ranking]
        cumulative_pattern = re.compile(
            r'^([A-Za-z\s/&\'\.\-\(\)]+?)(?:\s*\*)?\s+'
            r'([\d,]+)\s+'             # monthly prior year arrivals
            r'([\d,]+)\s+'             # monthly current year arrivals
            r'(-?[\d,.]+)\s+'          # monthly % change
            r'([\d,.]+)\s+'            # monthly % share
            r'[\d,]+\s+'              # YTD prior year (skip)
            r'[\d,]+\s+'              # YTD current year (skip)
            r'-?[\d,.]+\s+'           # YTD % change (skip)
            r'[\d,.]+'               # YTD % share (skip)
            r'(?:\s+(\d+))?'          # ranking (optional)
        )

        # Regex for single-month format: 5 number groups
        single_pattern = re.compile(
            r'^([A-Za-z\s/&\'\.\-\(\)]+?)(?:\s*\*)?\s+'
            r'([\d,]+)\s+'             # prior year arrivals
            r'([\d,]+)\s+'             # current year arrivals
            r'(-?[\d,.]+)\s+'          # % change
            r'([\d,.]+)'              # % share
            r'(?:\s+(\d+))?'          # ranking (optional)
        )

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip headers and metadata lines
            if line.startswith(('Table', 'REGION', 'Note:', 'Source:', 'Date:', 'Data ', 'Market')):
                continue
            if line.strip() == '% Change':
                continue
            # Skip standalone column header lines (month names, labels)
            if re.match(r'^(January|February|March|April|May|June|July|August|September|October|November|December)(\s*-\s*(January|February|March|April|May|June|July|August|September|October|November|December))?$', line.strip(), re.IGNORECASE):
                continue
            # Skip lines that are purely header fragments
            if re.match(r'^(2024|2025|2026|Change|Share|Ranking|%)\s*', line.strip()):
                continue

            # Try cumulative format first if detected
            match = None

            if is_cumulative:
                match = cumulative_pattern.match(line)

            # Fall back to single-month format
            if not match:
                match = single_pattern.match(line)

            if not match:
                continue

            country_name = match.group(1).strip()

            # Skip region headers
            if country_name.lower() in REGION_HEADERS:
                continue

            # Skip "Other" aggregates
            if OTHER_PATTERNS.match(country_name):
                continue

            # Both patterns put monthly data in same group positions
            prior_arrivals = parse_number(match.group(2))
            current_arrivals = parse_number(match.group(3))
            pct_change = parse_number(match.group(4))
            market_share = parse_number(match.group(5))
            ranking = parse_number(match.group(6)) if match.group(6) else None

            if current_arrivals is not None and current_arrivals > 0:
                countries.append({
                    'country': self._normalize_country(country_name),
                    'arrivals': current_arrivals,
                    'prior_year_arrivals': prior_arrivals,
                    'pct_change': pct_change,
                    'market_share': market_share,
                    'ranking': ranking,
                })

        return countries

    def _parse_key_indicators(self, text, report_year):
        """
        Extract key indicators. Handles both:
        - Old format (Table 5): Single-line pairs like "Total 216265 224788"
        - New format (Table 1): Year-prefixed lines like "2025 Total 216,265"
        """
        indicators = {}
        prior_year = report_year - 1

        # Normalize Unicode dashes to ASCII
        text = re.sub(r'[\u2010\u2011\u2012\u2013\u2014\u2212\u00AD]', '-', text)

        # --- NEW FORMAT: Key Indicators with year-prefixed lines (2024+) ---
        if 'key indicators' in text.lower():
            # Tourist arrivals — two patterns:
            # 2026: "Tourists 214,863 214,863" (under year section headers)
            # 2024: "2023 Total 172,499 172,499" under "TOURIST ARRIVALS" section
            tourist_matches = re.findall(r'^\s*Tourists\s+([\d,]+)', text, re.MULTILINE)
            if len(tourist_matches) >= 2:
                indicators['prior_year_total'] = parse_number(tourist_matches[0])
                indicators['current_year_total'] = parse_number(tourist_matches[1])
            elif len(tourist_matches) == 1:
                indicators['current_year_total'] = parse_number(tourist_matches[0])
            else:
                # Fallback: extract from "TOURIST ARRIVALS" section using year-Total lines
                arrivals_section = re.search(
                    r'TOURIST ARRIVALS.*?(?=TOURIST ARRIVALS \(by Sea\)|TOURISTS BY GENDER|TOTAL BEDS|BED NIGHTS|VISITOR ARRIVALS|$)',
                    text, re.DOTALL
                )
                if arrivals_section:
                    section_text = arrivals_section.group(0)
                    prior_total = re.search(rf'{prior_year}\s*Total\s+([\d,]+)', section_text)
                    current_total = re.search(rf'{report_year}\s*Total\s+([\d,]+)', section_text)
                    if prior_total:
                        indicators['prior_year_total'] = parse_number(prior_total.group(1))
                    if current_total:
                        indicators['current_year_total'] = parse_number(current_total.group(1))

            # Occupancy rate — section-based extraction
            occ_section = re.search(
                r'OCCUPANCY RATE.*?(?=AVAER|AVERAGE|Notes|Source|$)',
                text, re.DOTALL
            )
            if occ_section:
                occ_text = occ_section.group(0)
                prior_occ = re.search(rf'{prior_year}\s+([\d.]+)\s+', occ_text)
                current_occ = re.search(rf'{report_year}\s+([\d.]+)\s+', occ_text)
                if prior_occ:
                    indicators['prior_year_occupancy'] = parse_number(prior_occ.group(1))
                if current_occ:
                    indicators['current_year_occupancy'] = parse_number(current_occ.group(1))

            # Average duration of stay (note: "AVAERAGE" typo in actual report)
            stay_section = re.search(
                r'(?:AVAER|AVER)AGE DURATION.*?(?=Notes|Source|$)',
                text, re.DOTALL
            )
            if stay_section:
                stay_text = stay_section.group(0)
                prior_stay = re.search(rf'{prior_year}\s+([\d.]+)\s+', stay_text)
                current_stay = re.search(rf'{report_year}\s+([\d.]+)\s+', stay_text)
                if prior_stay:
                    indicators['prior_year_avg_stay'] = parse_number(prior_stay.group(1))
                if current_stay:
                    indicators['current_year_avg_stay'] = parse_number(current_stay.group(1))

            # Bed nights
            beds_section = re.search(
                r'BED NIGHTS.*?(?=OCCUPANCY|Notes|Source|$)',
                text, re.DOTALL
            )
            if beds_section:
                beds_text = beds_section.group(0)
                prior_beds = re.search(rf'{prior_year}\s+([\d,]+)\s+', beds_text)
                current_beds = re.search(rf'{report_year}\s+([\d,]+)\s+', beds_text)
                if prior_beds:
                    indicators['prior_year_bed_nights'] = parse_number(prior_beds.group(1))
                if current_beds:
                    indicators['current_year_bed_nights'] = parse_number(current_beds.group(1))

            # Beds in operation
            beds_op_section = re.search(
                r'TOTAL BEDS IN OPERATION.*?(?=BED NIGHTS|Notes|Source|$)',
                text, re.DOTALL
            )
            if beds_op_section:
                beds_op_text = beds_op_section.group(0)
                prior_beds_op = re.search(rf'{prior_year}\s+([\d,]+)\s+', beds_op_text)
                current_beds_op = re.search(rf'{report_year}\s+([\d,]+)\s+', beds_op_text)
                if prior_beds_op:
                    indicators['prior_year_beds'] = parse_number(prior_beds_op.group(1))
                if current_beds_op:
                    indicators['current_year_beds'] = parse_number(current_beds_op.group(1))

            return indicators

        # --- OLD FORMAT: Table 5 Key Indicators (pre-2026) ---
        match = re.search(r'Total\s+([\d,]+)\s+([\d,]+)', text)
        if match:
            indicators['prior_year_total'] = parse_number(match.group(1))
            indicators['current_year_total'] = parse_number(match.group(2))

        occ_match = re.search(r'OCCUPANCY RATE.*?(\d+\.?\d*)\s+(\d+\.?\d*)', text, re.DOTALL)
        if occ_match:
            indicators['prior_year_occupancy'] = parse_number(occ_match.group(1))
            indicators['current_year_occupancy'] = parse_number(occ_match.group(2))

        stay_match = re.search(r'DURATION OF STAY.*?(\d+\.?\d*)\s+(\d+\.?\d*)', text, re.DOTALL)
        if stay_match:
            indicators['prior_year_avg_stay'] = parse_number(stay_match.group(1))
            indicators['current_year_avg_stay'] = parse_number(stay_match.group(2))

        beds_match = re.search(r'BED NIGHTS.*?([\d,]+)\s+([\d,]+)', text, re.DOTALL)
        if beds_match:
            indicators['prior_year_bed_nights'] = parse_number(beds_match.group(1))
            indicators['current_year_bed_nights'] = parse_number(beds_match.group(2))

        beds_op_match = re.search(r'BEDS IN OPERATION.*?([\d,]+)\s+([\d,]+)', text, re.DOTALL)
        if beds_op_match:
            indicators['prior_year_beds'] = parse_number(beds_op_match.group(1))
            indicators['current_year_beds'] = parse_number(beds_op_match.group(2))

        return indicators

    # =========================================================================
    # DAILY UPDATE PARSER
    # =========================================================================

    def _parse_daily_update(self, pdf, text, filename):
        """
        Parse daily update report (single page).

        Extracts:
        - Top 10 markets with arrivals and market share
        - Monthly arrival totals
        - Facility distribution
        - Bed capacity
        """
        # Detect period
        date_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', text)
        if date_match:
            day = int(date_match.group(1))
            month_name = date_match.group(2).lower()
            year = int(date_match.group(3))
            month_num = MONTH_MAP.get(month_name)
        else:
            return {'error': 'Could not detect date from daily update'}

        if not month_num:
            return {'error': f'Unknown month in daily update: {month_name}'}

        # Report period = first of the month
        report_period = date(year, month_num, 1)

        # Parse Top 10 Markets
        # In the daily PDF, three tables are side by side on the same lines:
        # "1 China 52,112 14.4 1 Velana International 356,410 98.8 Resorts 246,127 68.2"
        # We need to extract rank + country + arrivals + share from the LEFT portion
        countries = []

        lines = text.split('\n')
        for line in lines:
            # Match the start of a top-10 line: rank country arrivals share
            m = re.match(
                r'^\s*(\d{1,2})\s+'                  # rank
                r'([A-Za-z][A-Za-z\s\.]{1,20}?)\s+'   # country (2-20 chars, starts with letter)
                r'([\d,]{3,8})\s+'                     # arrivals
                r'(\d{1,2}\.\d)\s+'                    # market share (e.g., 14.4)
                r'(\d{1,2})',                          # prior year rank (no trailing \s needed)
                line
            )
            if m:
                rank = int(m.group(1))
                market = m.group(2).strip()
                arrivals = parse_number(m.group(3))
                share = parse_number(m.group(4))

                if 1 <= rank <= 10 and arrivals and arrivals >= 500:
                    countries.append({
                        'country': self._normalize_country(market),
                        'arrivals': arrivals,
                        'market_share': share,
                        'ranking': rank,
                        'pct_change': None,
                        'prior_year_arrivals': None,
                    })

        # Parse monthly totals
        monthly_totals = {}
        # Pattern: "January 192,385 214,863 224,788 4.6 7,251"
        month_pattern = re.compile(
            r'(January|February|March|April|May|June|July|August|September|October|November|December)'
            r'(?:\s*\([^)]*\))?\s+'       # optional "(1 - 15)" etc.
            r'([\d,]+)\s+'                 # year-2
            r'([\d,]+)\s+'                 # year-1
            r'([\d,]+)\s+'                 # current year
            r'(-?[\d.]+)\s+'              # growth %
            r'([\d,]+)',                   # daily average
        )
        for m in month_pattern.finditer(text):
            month = m.group(1)
            monthly_totals[month] = {
                'year_minus_2': parse_number(m.group(2)),
                'year_minus_1': parse_number(m.group(3)),
                'current_year': parse_number(m.group(4)),
                'growth_pct': parse_number(m.group(5)),
                'daily_avg': parse_number(m.group(6)),
            }

        # Total arrivals
        total_match = re.search(r'TOTAL\s*\(as of.*?\)\s*([\d,]+)\s+([\d,]+)\s+([\d,]+)', text)
        total_arrivals = 0
        if total_match:
            total_arrivals = parse_number(total_match.group(3)) or 0

        # Facility distribution
        facility_dist = {}
        for ftype in ['Resorts', 'Hotels', 'Guesthouses', 'Safari Vessels']:
            fmatch = re.search(
                rf'{ftype}\s+([\d,]+)\s+([\d.]+)',
                text
            )
            if fmatch:
                facility_dist[ftype] = {
                    'arrivals': parse_number(fmatch.group(1)),
                    'share_pct': parse_number(fmatch.group(2)),
                }

        return {
            'report_type': 'daily',
            'report_date': date(year, month_num, day),
            'report_month': month_name.capitalize(),
            'report_year': year,
            'report_period': report_period,
            'total_arrivals': total_arrivals,
            'countries': countries,
            'country_count': len(countries),
            'monthly_totals': monthly_totals,
            'facility_distribution': facility_dist,
            'key_indicators': {},
            'source': f'MoT Daily Update {day} {month_name.capitalize()} {year}',
            'filename': filename,
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _detect_period(self, text):
        """Detect month and year from report text."""
        # Try "January 2025" pattern
        match = re.search(
            r'(January|February|March|April|May|June|July|August|'
            r'September|October|November|December)\s+(\d{4})',
            text
        )
        if match:
            return match.group(1), int(match.group(2))
        return None, None

    def _normalize_country(self, name):
        """Normalize country names to consistent format."""
        from platform_data.utils import normalize_country
        return normalize_country(name)


def import_mot_report(file_path, country_code='MV', user=None):
    """
    Convenience function: parse a MoT PDF and import into MarketArrivalData.

    Returns import result dict.
    """
    from platform_data.models import MarketArrivalData, MarketKeyIndicator, PlatformFileImport
    from django.utils import timezone as tz
    from decimal import Decimal

    parser = MoTReportParser()
    result = parser.parse_pdf(file_path)

    if 'error' in result:
        return result

    # Create file import record
    file_import = PlatformFileImport.objects.create(
        filename=result.get('filename', Path(file_path).name),
        import_type='arrival_report',
        country_code=country_code,
        status='processing',
        started_at=tz.now(),
        uploaded_by=user,
        rows_total=result['country_count'],
        notes=f"{result['report_type']} report: {result['source']}",
    )

    created = updated = skipped = 0
    errors = []

    report_period = result['report_period']
    source = result['source']

    for c in result['countries']:
        try:
            obj, was_created = MarketArrivalData.objects.update_or_create(
                country_code=country_code,
                report_period=report_period,
                origin_country=c['country'],
                defaults={
                    'arrivals': c['arrivals'] or 0,
                    'market_share_pct': Decimal(str(c['market_share'])) if c.get('market_share') else None,
                    'yoy_change_pct': Decimal(str(c['pct_change'])) if c.get('pct_change') else None,
                    'source_report': source,
                    'file_import': file_import,
                }
            )
            if was_created:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append({'country': c['country'], 'message': str(e)})
            skipped += 1

    # Save key indicators (if parsed)
    ki = result.get('key_indicators', {})
    if ki.get('current_year_total'):
        try:
            MarketKeyIndicator.objects.update_or_create(
                country_code=country_code,
                report_period=report_period,
                defaults={
                    'total_arrivals': ki['current_year_total'],
                    'occupancy_rate': Decimal(str(ki['current_year_occupancy'])) if ki.get('current_year_occupancy') else None,
                    'avg_stay_days': Decimal(str(ki['current_year_avg_stay'])) if ki.get('current_year_avg_stay') else None,
                    'total_bed_nights': ki.get('current_year_bed_nights'),
                    'total_beds_operational': ki.get('current_year_beds'),
                    'source_report': source,
                    'file_import': file_import,
                }
            )
        except Exception as e:
            errors.append({'key_indicators': True, 'message': str(e)})

    # Save facility distribution (from daily reports)
    facility_dist = result.get('facility_distribution', {})
    if facility_dist:
        from platform_data.models import FacilityDistribution

        type_map = {
            'Resorts': 'resorts',
            'Hotels': 'hotels',
            'Guesthouses': 'guesthouses',
            'Safari Vessels': 'safari',
        }

        for ftype_label, data in facility_dist.items():
            ftype = type_map.get(ftype_label)
            if ftype and data.get('arrivals'):
                try:
                    FacilityDistribution.objects.update_or_create(
                        country_code=country_code,
                        report_period=report_period,
                        facility_type=ftype,
                        defaults={
                            'arrivals': data['arrivals'],
                            'share_pct': Decimal(str(data['share_pct'])) if data.get('share_pct') else None,
                            'source_report': source,
                        }
                    )
                except Exception as e:
                    errors.append({'facility': ftype_label, 'message': str(e)})

    file_import.rows_created = created
    file_import.rows_updated = updated
    file_import.rows_skipped = skipped
    file_import.rows_processed = created + updated + skipped
    file_import.errors = errors
    file_import.status = 'completed' if not errors else 'completed_with_errors'
    file_import.completed_at = tz.now()
    file_import.save()

    return {
        'success': True,
        'report_type': result['report_type'],
        'report_period': report_period.isoformat(),
        'source': source,
        'total_arrivals': result['total_arrivals'],
        'countries_parsed': result['country_count'],
        'rows_created': created,
        'rows_updated': updated,
        'rows_skipped': skipped,
        'errors': errors[:10],
        'key_indicators': result.get('key_indicators', {}),
        'file_import_id': file_import.id,
    }
