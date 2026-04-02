"""
Analytics services: ReservationImportService, BookingAnalysisService.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import date, datetime, timedelta
from collections import defaultdict
import calendar
import hashlib
import re
import csv
import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from django.db import transaction
from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.utils import timezone

try:
    import pandas as pd
except ImportError:
    pd = None

class ReservationImportService:
    """
    Service for importing reservation data from Excel/CSV files.
    
    Supports multiple PMS formats including:
    - ABS PMS: "Res#", "Arr", "Dept", "Revenue($)"
    - Thundi/Biosphere: "Res #", "Arrival", "Dept", "Total"
    - SynXis Activity Report: "FXRes#", "ArrivalDate/Time", "Type"
    
    Column Mapping handles various naming conventions automatically.
    """
    
    # =========================================================================
    # SYNXIS ACTIVITY REPORT ROOM TYPE MAPPING
    # =========================================================================
    SYNXIS_ROOM_TYPE_MAPPING = {
        'STS': 'Standard Room + Family Room',
        'SUB': 'Standard Room + Family Room',
        'SUS': 'Standard Room + Family Room',
        'SBC': 'Standard Room + Family Room',
        'DEF': 'Deluxe (Balcony / Veranda)',
        'GDB': 'Deluxe (Balcony / Veranda)',
        'GIS': 'Premium Deluxe Islandview with Balcony',
        'PDS': 'Premium Deluxe Seaview with Balcony',
        'PM': 'Premium Deluxe Seaview with Balcony',
    }
    
    # =========================================================================
    # CHANNEL MAPPING (CompanyName/TravelAgent -> Channel)
    # =========================================================================
    CHANNEL_MAPPING = {
        'booking.com': 'Booking.com',
        'agoda.com': 'Agoda',
        'agoda': 'Agoda',
        'expedia': 'Expedia',
        'trip.com': 'Trip.com',
        'fit - free individual traveler': 'Direct',
        'fit- free individual traveler': 'Direct',
        'web bookings dir': 'Direct',
        'house use': 'Direct',
        'complimentary': 'Direct',
        'owners package': 'Direct',
        'owners fnf package': 'Direct',
        'fam trip': 'Direct',
    }
    
    DEFAULT_COLUMN_MAPPING = {
        # =========================================================================
        # CONFIRMATION NUMBER
        # =========================================================================
        'confirmation_no': [
            # SynXis Activity Report
            'FXRes#', 'TPRes#', 'BookingSr.No',
            # IDS / SynXis Distribution (monthly export)
            'Confirm #', 'Confirm#',
            # IDS daily report
            'Confirm_No',
            # Standard PMS formats
            'Res #', 'Res#', 'Res. No', 'Res No', 'Res.No',
            'Conf. No', 'Conf No', 'Confirmation', 'Confirmation No', 'ConfNo',
            'Reservation', 'Reservation No', 'Booking No', 'BookingNo',
        ],
        
        # =========================================================================
        # DATES
        # =========================================================================
        'booking_date': [
            # SynXis Activity Report
            'BookedDate',
            # Standard formats
            'Booking Date', 'Res. Date', 'Res Date', 'Booked On',
            'Created', 'Book Date', 'Created Date',
            # IDS monthly — Status Date is when confirmed/cancelled
            'Status Date',
            # IDS daily report
            'Status_Dt',
        ],
        
        'booking_time': [
            'Booking Time', 'Time', 'Created Time',
        ],
        
        'arrival_date': [
            # SynXis Activity Report
            'ArrivalDate/Time',
            # IDS monthly (after newline normalization)
            'Arrive Date', 'Arrive',
            # IDS daily report
            'Arrival_Dt',
            # Standard formats
            'Arrival', 'Arr', 'Check In', 'CheckIn', 'Arrival Date', 'Check-In',
        ],

        'departure_date': [
            # SynXis Activity Report
            'DepartureDate/Time',
            # IDS monthly
            'Depart Date', 'Depart',
            # IDS daily report
            'Depart_Dt',
            # Standard formats
            'Dept', 'Departure', 'Check Out', 'CheckOut', 'Departure Date', 'Check-Out',
        ],

        'cancellation_date': [
            'Cancellation Date', 'Cancelled Date', 'Cancel Date',
        ],

        'cancellation_reason': [
            'CancelReason', 'Cancel Reason', 'Cancellation Reason',
            'CxlReason', 'Reason', 'CancelNote', 'Cancel Note',
        ],
        
        # =========================================================================
        # NIGHTS / PAX
        # =========================================================================
        'nights': [
            # SynXis Activity Report
            'Room Nights',
            # IDS daily report
            'Nights_Qty',
            # Standard formats
            'No Of Nights', 'Nights', 'Night', 'LOS', 'Length of Stay',
            'NoOfNights', 'Number of Nights',
        ],

        'pax': ['Pax', 'Guests', 'Occupancy'],
        'adults': [
            # SynXis Activity Report
            'Adult',
            # IDS monthly
            'Total Adult Occupancy',
            # IDS daily report
            'Total_Adult_Occupancy',
            # Standard formats
            'Adults', 'No of Adults',
        ],
        'children': [
            # SynXis Activity Report
            'Child',
            # IDS monthly
            'Total Child Occupancy For Age Group1',
            # IDS daily report
            'Total_Child_Occupancy_For_Age_Group1',
            # Standard formats
            'Children', 'Kids', 'No of Children',
        ],
        
        # =========================================================================
        # ROOM TYPE
        # =========================================================================
        'room_no': [
            # SynXis Activity Report / IDS monthly
            'Room Type',
            # IDS monthly — human-readable name (often empty)
            'Original Room Type Name',
            # IDS daily report
            'Room_Type_Code', 'Original_Rm_Typ_Nm',
            # Standard formats
            'Room', 'Room No', 'Room Number', 'RoomNo', 'RoomType', 'Room Name',
        ],
        
        # =========================================================================
        # SOURCE / CHANNEL
        # =========================================================================
        'source': [
            # SynXis Activity Report
            'CompanyName/TravelAgent',
            # IDS daily report
            'Channel_Cd',
            # Standard formats
            'Source', 'Business Source', 'Channel', 'Booking Source', 'channel',
        ],

        'secondary_source': [
            # IDS monthly — actual OTA name
            'Secondary Channel', 'Sub Channel', 'OTA Name', 'OTA',
            # IDS daily report
            'Sec_Channel_Desc',
        ],
        
        'user': [
            # SynXis Activity Report
            'User Name',
            # Standard formats
            'User', 'Created By', 'Agent', 'Booked By',
        ],
        
        # =========================================================================
        # RATE PLAN
        # =========================================================================
        'rate_plan': [
            'Rate Type', 'Rate Plan', 'RatePlan', 'Meal Plan', 'Board',
            'Board Type', 'Package',
            # IDS monthly
            'Rate Type Code', 'Rate Category Name',
            # IDS daily report
            'Rate_Category_Name', 'Rate_Type_Code',
        ],
        
        # =========================================================================
        # AMOUNTS
        # =========================================================================
        'total_amount': [
            # SynXis Activity Report
            'TotalRoomRate',
            # IDS monthly
            'Cash Paid(Total)', 'Cash Paid', 'Total Paid',
            # IDS daily report
            'Total_Cash_Pymnt',
            # Standard formats
            'Total', 'Grand Total', 'Total Amount',
            'Revenue($)', 'Balance Due($)', 'Revenue', 'Amount', 'Net Amount',
        ],

        'adr': [
            # SynXis Activity Report
            'AvgRoomRate',
            # IDS monthly
            'Avg Rate', 'Average Rate',
            # IDS daily report
            'Rez_Avg_Rate_Amt',
            # Standard formats
            'ADR', 'Average Daily Rate', 'Daily Rate', 'Rate',
        ],
        
        'deposit': ['Deposit', 'Deposit Amount', 'Advance'],
        
        'total_charges': ['Total Charges', 'Charges', 'Extra Charges'],
        
        # =========================================================================
        # GUEST INFO
        # =========================================================================
        'guest_name': [
            # SynXis Activity Report
            'Guest Name',
            # IDS daily report
            'Guest_Nm',
            # Standard formats
            'Name', 'Guest', 'Customer', 'Customer Name',
        ],

        'country': [
            # SynXis Activity Report
            'Nationality',
            # IDS monthly
            'Guest Location',
            # IDS daily report
            'Location',
            # Standard formats
            'Country', 'Guest Country',
        ],
        
        'city': ['City', 'Guest City'],
        'state': ['State', 'Province', 'Guest State'],
        'zip_code': ['Zip Code', 'Postal Code', 'Zip', 'Postcode'],
        'email': ['Email', 'Guest Email', 'E-mail'],
        
        # =========================================================================
        # STATUS
        # =========================================================================
        'status': [
            'Status', 'Booking Status', 'State', 'Res.Type', 'Reservation Status',
            # IDS daily report
            'Rez_Status_Desc',
        ],
        
        # SynXis Activity Report uses 'Type' column for action type
        'reservation_type': [
            # SynXis Activity Report - CRITICAL for status mapping
            'Type',
            # Standard formats
            'Reservationn Type', 'Reservation Type', 'Res Type', 'Booking Type',
        ],
        
        # =========================================================================
        # OTHER
        # =========================================================================
        'market_code': [
            # SynXis Activity Report
            'Segment',
            # Standard formats
            'Market Code', 'Market',
        ],
        
        'payment_type': ['Payment Type', 'Payment Method', 'Payment'],
        
        'rooms_count': [
            # SynXis Activity Report
            'No Of Rooms',
            # IDS daily report
            'Room_Qty',
            # Standard formats
            'Rooms',
        ],
        
        'hotel_name': ['Hotel Name', 'Property', 'Hotel', 'Property/Code'],
        
        'pms_confirmation': ['PMS Confirmation\nCode', 'PMS Confirmation Code'],
        'promotion': ['Promotion'],
    }
    
    # Status mapping from import values to model choices
    STATUS_MAPPING = {
        'confirmed': [
            'confirmed', 'confirm', 'active', 'booked',
            'confirm booking',
        ],
        'cancelled': [
            'cancelled', 'canceled', 'cancel', 'void',
        ],
        'checked_in': [
            'checked in', 'checkedin', 'in house', 'inhouse', 'arrived',
        ],
        'checked_out': [
            'checked out', 'checkedout', 'departed', 'completed',
        ],
        'no_show': [
            'no show', 'noshow', 'no-show',
        ],
    }
    
    def __init__(self, column_mapping: Dict = None, hotel=None):
        """
        Initialize import service.
        
        Args:
            column_mapping: Custom column mapping (optional)
            hotel: Property instance to import to (optional)
        """
        self.column_mapping = column_mapping or self.DEFAULT_COLUMN_MAPPING
        self.hotel = hotel
        self.errors = []
        self.stats = {
            'rows_total': 0,
            'rows_processed': 0,
            'rows_created': 0,
            'rows_updated': 0,
            'rows_skipped': 0,
        }
        # Track sequence numbers for multi-room bookings
        # Key: (confirmation_no, arrival_date) -> sequence counter
        self._sequence_tracker = defaultdict(int)
        # Flag to indicate SynXis Activity Report format
        self._is_synxis_activity = False
        # Flag to indicate IDS/SynXis Distribution format
        self._is_ids_format = False
    
    def import_file(self, file_path: str, file_import=None, hotel=None) -> Dict:
        """
        Import reservations from a file.
        
        Args:
            file_path: Path to Excel or CSV file
            file_import: Optional FileImport record for tracking
            hotel: Property to import to (optional, overrides __init__ hotel)
        
        Returns:
            Dict with import results
        """
        from pricing.models import FileImport, Property
        
        file_path = Path(file_path)
        
        # Use provided hotel or fall back to instance hotel
        self.hotel = hotel or self.hotel
        
        # Create or get FileImport record
        if file_import is None:
            file_import = FileImport.objects.create(
                hotel=self.hotel,
                filename=file_path.name,
                status='processing',
                started_at=timezone.now(),
            )
        else:
            file_import.status = 'processing'
            file_import.started_at = timezone.now()
            file_import.save()
        
        try:
            # Calculate file hash for duplicate detection
            file_import.file_hash = self._calculate_file_hash(file_path)
            file_import.save()
            
            # Read the file (with SynXis header detection)
            df = self._read_file(file_path)
            
            if df is None or df.empty:
                file_import.status = 'failed'
                file_import.errors = [{'row': 0, 'message': 'File is empty or could not be read'}]
                file_import.completed_at = timezone.now()
                file_import.save()
                return self._build_result(file_import)
            
            self.stats['rows_total'] = len(df)
            file_import.rows_total = len(df)
            file_import.save()
            
            # Clean Excel-escaped values (="314" format)
            df = self._clean_excel_escapes(df)
            
            # Map columns
            df = self._map_columns(df)
            
            # Filter invalid confirmation numbers (footer rows, etc.)
            if 'confirmation_no' in df.columns:
                initial_count = len(df)
                df['_conf_str'] = df['confirmation_no'].astype(str).str.strip()
                # Allow: digits (336), hyphenated multi-room (332-6), and alphanumeric IDS (45232SE002633)
                df = df[df['_conf_str'].str.match(r'^[A-Za-z0-9][\w\-]+$', na=False)]
                df = df.drop(columns=['_conf_str'])
                
                invalid_filtered = initial_count - len(df)
                if invalid_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered out {invalid_filtered} invalid/footer rows'
                    })
            
            # Filter by hotel name if the file has a Hotel column (daily reports)
            if 'hotel_name' in df.columns and self.hotel:
                initial_count = len(df)
                hotel_col = df['hotel_name'].astype(str).str.strip()
                # Match by property name or SynXis hotel code in parentheses
                prop_name = self.hotel.name.lower()
                prop_code = str(getattr(self.hotel, 'synxis_code', '') or '')
                mask = hotel_col.str.lower().str.contains(prop_name, na=False)
                if prop_code:
                    mask = mask | hotel_col.str.contains(prop_code, na=False)
                # Also match by confirmation_no prefix if hotel has IDS bookings
                if 'confirmation_no' in df.columns:
                    # Extract hotel ID from existing reservations
                    from pricing.models import Reservation
                    sample_conf = Reservation.objects.filter(
                        hotel=self.hotel
                    ).values_list('confirmation_no', flat=True).first()
                    if sample_conf and len(sample_conf) >= 5:
                        hotel_prefix = sample_conf[:5]
                        mask = mask | df['confirmation_no'].astype(str).str.startswith(hotel_prefix)
                df = df[mask]
                hotel_filtered = initial_count - len(df)
                if hotel_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered {hotel_filtered} rows for other properties (kept {len(df)} for {self.hotel.name})'
                    })

            # Filter out day-use bookings (Nights == 0)
            if 'nights' in df.columns:
                initial_count = len(df)
                df = df[df['nights'].fillna(0).astype(float).astype(int) > 0]
                day_use_filtered = initial_count - len(df)
                
                if day_use_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered out {day_use_filtered} day-use bookings (Nights=0)'
                    })
            
            # Update rows_total after filtering
            self.stats['rows_total'] = len(df)
            file_import.rows_total = len(df)
            file_import.save()
            
            # Ensure property has channels before processing
            self._ensure_channels_exist()

            # Process rows
            self._process_dataframe(df, file_import)

            # Update file import record
            file_import.rows_processed = self.stats['rows_processed']
            file_import.rows_created = self.stats['rows_created']
            file_import.rows_updated = self.stats['rows_updated']
            file_import.rows_skipped = self.stats['rows_skipped']
            file_import.errors = self.errors[:100]  # Limit stored errors
            file_import.completed_at = timezone.now()
            
            if self.errors and any(e.get('row', 0) > 0 for e in self.errors):
                file_import.status = 'completed_with_errors'
            else:
                file_import.status = 'completed'
            
            file_import.save()
            
            # Link multi-room bookings after all reservations are imported
            self._link_multi_room_bookings(file_import)

            # Clearing stage: match cancelled bookings to their original
            # confirmed bookings and update the originals
            if self.hotel:
                self._clear_cancellations(file_import)
            
            return self._build_result(file_import)
            
        except Exception as e:
            file_import.status = 'failed'
            file_import.errors = [{'row': 0, 'message': str(e)}]
            file_import.completed_at = timezone.now()
            file_import.save()
            raise
    
    def _read_file(self, file_path: Path) -> Optional[pd.DataFrame]:
        """
        Read Excel or CSV file into DataFrame.
        
        Handles SynXis Activity Report format with 3 header rows.
        """
        suffix = file_path.suffix.lower()
        
        try:
            # First, check if this is a SynXis Activity Report
            skiprows = 0
            
            if suffix == '.csv':
                # Detect header rows to skip (SynXis Activity Report or IDS preamble)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        first_lines = [f.readline() for _ in range(20)]

                    if 'Reservation Activity Report' in first_lines[0]:
                        skiprows = 3
                        self._is_synxis_activity = True
                        self.errors.append({
                            'row': 0,
                            'message': 'Detected SynXis Activity Report format - skipped 3 header rows'
                        })
                    else:
                        # Look for the actual data header row (contains known column names)
                        # Read as CSV records (handles multi-line quoted fields)
                        header_markers = ['Confirm #', 'Confirm#', 'Res #', 'Res#',
                                          'Reservation No', 'confirmation_no',
                                          'FXRes#', 'BookingSr.No']
                        try:
                            probe = pd.read_csv(file_path, header=None, nrows=20,
                                                encoding='utf-8', on_bad_lines='skip')
                            for i in range(len(probe)):
                                row_str = ' '.join(str(v) for v in probe.iloc[i] if pd.notna(v))
                                if any(marker in row_str for marker in header_markers):
                                    if i > 0:
                                        skiprows = i
                                        self.errors.append({
                                            'row': 0,
                                            'message': f'Skipped {i} preamble row(s) before header'
                                        })
                                    break
                        except Exception:
                            # Fall back to skipping blank lines
                            for i, line in enumerate(first_lines):
                                if line.strip().replace(',', ''):
                                    if i > 0:
                                        skiprows = i
                                    break
                except Exception:
                    pass
            
            # Read the file
            if suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path, skiprows=skiprows)
            elif suffix == '.csv':
                # Try different encodings
                df = None
                for encoding in ['utf-8', 'latin1', 'cp1252']:
                    try:
                        df = pd.read_csv(
                            file_path, 
                            encoding=encoding, 
                            index_col=False,
                            skiprows=skiprows
                        )
                        break
                    except UnicodeDecodeError:
                        continue
                
                if df is None:
                    df = pd.read_csv(
                        file_path,
                        encoding='utf-8',
                        encoding_errors='replace',
                        index_col=False,
                        skiprows=skiprows
                    )
            else:
                self.errors.append({
                    'row': 0,
                    'message': f'Unsupported file format: {suffix}'
                })
                return None
            
            # Normalize column headers — strip newlines/extra spaces (fixes IDS "Arrive\nDate")
            if df is not None:
                df.columns = [
                    re.sub(r'\s+', ' ', str(c).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')).strip()
                    for c in df.columns
                ]

            # Detect SynXis format by columns
            if df is not None and ('FXRes#' in df.columns or 'Type' in df.columns):
                self._is_synxis_activity = True

            # Detect IDS format by columns
            if df is not None and ('Secondary Channel' in df.columns or 'Rate Category Name' in df.columns):
                self._is_ids_format = True

            return df
            
        except Exception as e:
            self.errors.append({
                'row': 0,
                'message': f'Error reading file: {str(e)}'
            })
            return None
    
    def _clean_excel_escapes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean Excel-escaped values like ="314" to just 314.
        
        This format is common when exporting from some PMS systems.
        """
        def clean_value(val):
            if pd.isna(val):
                return val
            val_str = str(val).strip()
            # Match pattern: ="value" or ='value'
            match = re.match(r'^[=]?["\'](.+)["\']$', val_str)
            if match:
                return match.group(1)
            return val_str
        
        # Apply to all object (string) columns
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].apply(clean_value)
        
        return df
    
    def _map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map source columns to standard column names."""
        # Create mapping from source column names to standard names
        column_map = {}
        
        # Clean column names (remove trailing spaces, etc.)
        df.columns = [col.strip() for col in df.columns]
        
        for standard_name, possible_names in self.column_mapping.items():
            for col in df.columns:
                col_lower = col.strip().lower()
                if col_lower in [name.lower() for name in possible_names]:
                    column_map[col] = standard_name
                    break
        
        # Rename columns
        df = df.rename(columns=column_map)
        
        # Log unmapped columns
        mapped_cols = set(column_map.values())
        required_cols = {'confirmation_no', 'arrival_date', 'departure_date'}
        missing_required = required_cols - mapped_cols
        
        if missing_required:
            missing_list = ', '.join(sorted(missing_required))
            self.errors.append({
                'row': 0,
                'message': 'Missing required columns: ' + missing_list
            })
        
        return df
    
    def _process_dataframe(self, df: pd.DataFrame, file_import) -> None:
        """Process each row of the DataFrame."""
        from pricing.models import Reservation, RoomType, RatePlan
        
        # Pre-fetch reference data for performance
        if self.hotel:
            room_types = {rt.name.lower(): rt for rt in RoomType.objects.filter(hotel=self.hotel)}
        else:
            room_types = {rt.name.lower(): rt for rt in RoomType.objects.all()}
        
        if self.hotel:
            rate_plans = {rp.name.lower(): rp for rp in RatePlan.objects.filter(hotel=self.hotel)}
        else:
            rate_plans = {rp.name.lower(): rp for rp in RatePlan.objects.all()}
        
        # Reset sequence tracker for this import
        self._sequence_tracker = defaultdict(int)
        
        for i, (idx, row) in enumerate(df.iterrows()):
            row_num = i + 2  # Excel row number (1-indexed + header)
            if self._is_synxis_activity:
                row_num += 3  # Account for skipped header rows
            
            try:
                self._process_row(row, row_num, file_import, room_types, rate_plans)
                self.stats['rows_processed'] += 1
            except Exception as e:
                self.errors.append({
                    'row': row_num,
                    'message': str(e)
                })
                self.stats['rows_skipped'] += 1
    
    def _process_row(self, row: pd.Series, row_num: int, file_import,
                     room_types: Dict, rate_plans: Dict) -> None:
        """Process a single row and create/update reservation."""
        from pricing.models import Reservation, BookingSource, Channel, Guest
        
        # =====================================================================
        # CONFIRMATION NUMBER
        # =====================================================================
        raw_conf = str(row.get('confirmation_no', '')).strip()
        if not raw_conf or raw_conf == 'nan':
            self.stats['rows_skipped'] += 1
            return
        
        base_conf, sequence = Reservation.parse_confirmation_no(raw_conf)
        
        # =====================================================================
        # DATES - Parse early (needed for sequence tracking)
        # =====================================================================
        booking_date = self._parse_date(row.get('booking_date'))
        arrival_date = self._parse_date(row.get('arrival_date'))
        departure_date = self._parse_date(row.get('departure_date'))
        cancellation_date = self._parse_date(row.get('cancellation_date'))

        # IDS: Status Date maps to booking_date, but for cancelled bookings it's
        # actually the cancellation date, not when the booking was originally made
        if self._is_ids_format and booking_date:
            status_raw = str(row.get('status', '')).strip().lower()
            if status_raw in ('cancelled', 'canceled', 'cancel'):
                cancellation_date = cancellation_date or booking_date
                booking_date = None  # unknown — will fall back to arrival_date below

        if not arrival_date or not departure_date:
            self.errors.append({
                'row': row_num,
                'message': f'Invalid dates for confirmation {raw_conf}'
            })
            self.stats['rows_skipped'] += 1
            return
        
        # =====================================================================
        # MULTI-ROOM SEQUENCE TRACKING
        # =====================================================================
        # For SynXis Activity Report (and similar), generate sequence based on
        # occurrence within the same confirmation_no + arrival_date
        if self._is_synxis_activity:
            tracker_key = (base_conf, arrival_date)
            self._sequence_tracker[tracker_key] += 1
            sequence = self._sequence_tracker[tracker_key]
        
        # =====================================================================
        # NIGHTS
        # =====================================================================
        nights = self._parse_int(row.get('nights'))
        if not nights:
            nights = (departure_date - arrival_date).days
        
        # =====================================================================
        # PAX
        # =====================================================================
        adults, children = self._parse_pax(row)
        
        # =====================================================================
        # ROOM TYPE
        # =====================================================================
        room_type_raw = str(row.get('room_no', '')).strip()
        room_type, room_type_name = self._extract_room_type(room_type_raw, room_types)
        
        # =====================================================================
        # RATE PLAN
        # =====================================================================
        rate_plan_raw = str(row.get('rate_plan', '')).strip()
        rate_plan, rate_plan_name = self._map_rate_plan(rate_plan_raw, rate_plans)
        
        # =====================================================================
        # BOOKING SOURCE / CHANNEL
        # =====================================================================
        # For IDS: prefer Secondary Channel (has actual OTA name) over Channel (has code)
        secondary_source = str(row.get('secondary_source', '')).strip()
        source_str = str(row.get('source', '')).strip()

        if secondary_source and secondary_source != 'nan':
            channel = self._map_channel(secondary_source)
            effective_source = secondary_source
        elif source_str and source_str != 'nan' and source_str.upper() != 'PMS':
            channel = self._map_channel(source_str)
            effective_source = source_str
        else:
            channel = None
            effective_source = 'Direct'

        # For IDS: also try Rate Category Name if channel still unmapped
        if not channel and self._is_ids_format:
            rate_cat = str(row.get('rate_plan', '')).strip().lower()
            if rate_cat and rate_cat != 'nan':
                if 'ota' in rate_cat:
                    channel = self._map_channel('OTA')
                elif 'booking engine' in rate_cat or 'direct' in rate_cat:
                    channel = self._map_channel('Direct')

        source_str = effective_source
        
        # Get or create booking source
        booking_source = BookingSource.find_source(
            source_str,
            str(row.get('user', ''))
        )
        
        if not booking_source:
            if source_str and source_str not in ('Direct', 'nan', ''):
                booking_source, _ = BookingSource.objects.get_or_create(
                    name=source_str,
                    defaults={'import_values': [source_str.lower()], 'is_direct': False, 'sort_order': 100}
                )
            else:
                booking_source = BookingSource.get_or_create_unknown()
        
        # Update channel on booking source if we mapped one
        if channel and booking_source and booking_source.channel_id != channel.id:
            booking_source.channel = channel
            booking_source.save(update_fields=['channel'])
        
        # =====================================================================
        # GUEST
        # =====================================================================
        guest_name = str(row.get('guest_name', '')).strip()
        country = str(row.get('country', '')).strip()
        email = str(row.get('email', '')).strip()

        # Normalize ISO country codes to full names
        if country and country not in ['nan', '-', '']:
            country = self._normalize_country_name(country)

        if guest_name and guest_name != 'nan':
            guest = Guest.find_or_create(
                name=guest_name,
                country=country if country not in ['nan', '-', ''] else None,
                email=email if email not in ['nan', '-', ''] else None
            )
        else:
            guest = None
        
        # =====================================================================
        # AMOUNTS
        # =====================================================================
        total_amount = self._parse_decimal(row.get('total_amount'))
        adr = self._parse_decimal(row.get('adr'))
        
        # Calculate ADR if not provided
        if adr == Decimal('0.00') and total_amount > 0 and nights > 0:
            adr = (total_amount / Decimal(str(nights))).quantize(Decimal('0.01'))
        
        # =====================================================================
        # STATUS - CRITICAL FOR SYNXIS
        # =====================================================================
        raw_status = str(row.get('status', 'confirmed')).strip()
        status = self._map_status(raw_status)
        
        # SynXis Activity Report: Type column determines actual status
        # Type='Cancel' -> cancelled, Type='New'/'Amend' -> confirmed
        res_type = str(row.get('reservation_type', '')).strip().lower()
        if res_type == 'cancel':
            status = 'cancelled'
        elif res_type in ['new', 'amend']:
            status = 'confirmed'
        
        # Cancellation date also indicates cancelled
        if cancellation_date and status == 'confirmed':
            status = 'cancelled'

        # =====================================================================
        # CANCELLATION ENHANCEMENTS
        # =====================================================================
        is_revenue_estimated = False
        cancellation_reason = str(row.get('cancellation_reason', '')).strip()
        if cancellation_reason in ('nan', '-', ''):
            cancellation_reason = ''
        notes = ''

        if status == 'cancelled':
            # Fallback cancellation date: use import date if missing
            if not cancellation_date:
                cancellation_date = date.today()
                notes += ' [Cancel date estimated from import date]'

            # Estimate revenue for cancelled bookings with $0 amount
            if (total_amount is None or total_amount == Decimal('0.00')) and nights > 0:
                comparable_qs = Reservation.objects.filter(
                    hotel=self.hotel,
                    arrival_date__month=arrival_date.month,
                    status__in=Reservation.ACTIVE_STATUSES,
                    adr__gt=0,
                )
                if room_type:
                    comparable_qs = comparable_qs.filter(room_type=room_type)

                avg_adr = comparable_qs.aggregate(
                    avg=Avg('adr')
                )['avg']

                if avg_adr:
                    total_amount = (avg_adr * Decimal(str(nights))).quantize(Decimal('0.01'))
                    adr = avg_adr.quantize(Decimal('0.01'))
                    is_revenue_estimated = True
                    notes += ' [Revenue estimated from comparable ADR]'

        # =====================================================================
        # CREATE OR UPDATE RESERVATION
        # =====================================================================
        is_multi_room = sequence > 1
        raw_data = {k: str(v) for k, v in row.items() if pd.notna(v)}
        
        with transaction.atomic():
            # IMPORTANT: Lookup includes arrival_date to differentiate
            # same confirmation_no with different stay dates
            lookup = {
                'confirmation_no': base_conf,
                'arrival_date': arrival_date,
                'room_sequence': sequence,
            }
            
            if self.hotel:
                lookup['hotel'] = self.hotel
            
            # For IDS cancelled bookings: preserve existing booking_date if we don't have a real one
            effective_booking_date = booking_date or arrival_date
            if self._is_ids_format and not booking_date:
                existing = Reservation.objects.filter(**lookup).values_list('booking_date', flat=True).first()
                if existing:
                    effective_booking_date = existing

            defaults = {
                'original_confirmation_no': raw_conf,
                'booking_date': effective_booking_date,
                'departure_date': departure_date,
                'nights': nights,
                'adults': adults,
                'children': children,
                'room_type': room_type,
                'room_type_name': room_type_name,
                'rate_plan': rate_plan,
                'rate_plan_name': rate_plan_name,
                'booking_source': booking_source,
                'channel': channel or (booking_source.channel if booking_source else None),
                'guest': guest,
                'total_amount': total_amount,
                'adr': adr,
                'status': status,
                'cancellation_date': cancellation_date,
                'cancellation_reason': cancellation_reason,
                'is_revenue_estimated': is_revenue_estimated,
                'is_multi_room': is_multi_room,
                'file_import': file_import,
                'raw_data': raw_data,
            }

            if notes.strip():
                defaults['notes'] = notes.strip()
            
            if self.hotel:
                defaults['hotel'] = self.hotel
            
            reservation, created = Reservation.objects.update_or_create(
                **lookup,
                defaults=defaults
            )
            
            if created:
                self.stats['rows_created'] += 1
            else:
                self.stats['rows_updated'] += 1
            
            # Update guest stats
            if guest:
                guest.update_stats()
    
    def _parse_pax(self, row: pd.Series) -> Tuple[int, int]:
        """
        Parse pax/adults/children from row.
        
        Handles formats:
        - "2 \\ 0" (backslash separator)
        - "2 / 0" (forward slash separator)
        - " 2 / 0" (with leading space)
        - Separate adults/children columns
        
        Returns:
            Tuple of (adults, children)
        """
        # First check for combined pax field
        pax_value = row.get('pax', '')
        
        if pd.notna(pax_value):
            pax_str = str(pax_value).strip()
            
            # Try backslash separator: "2 \ 0" or "2 \\ 0"
            if '\\' in pax_str:
                parts = pax_str.split('\\')
                if len(parts) >= 2:
                    try:
                        adults = int(float(parts[0].strip()))
                        children = int(float(parts[1].strip()))
                        return (adults, children)
                    except (ValueError, TypeError):
                        pass
            
            # Try forward slash separator: "2 / 0"
            if '/' in pax_str:
                parts = pax_str.split('/')
                if len(parts) >= 2:
                    try:
                        adults = int(float(parts[0].strip()))
                        children = int(float(parts[1].strip()))
                        return (adults, children)
                    except (ValueError, TypeError):
                        pass
            
            # Try single number (just adults)
            try:
                adults = int(float(pax_str))
                return (adults, 0)
            except (ValueError, TypeError):
                pass
        
        # Fall back to separate columns
        adults = self._parse_int(row.get('adults'), default=2)
        children = self._parse_int(row.get('children'), default=0)
        
        return (adults, children)
    
    def _extract_room_type(self, room_input: Any, room_types: Dict[str, Any]) -> Tuple[Optional[Any], str]:
        """
        Extracts room type from a 'Room' column.
        
        Handles:
        - SynXis short codes: "STS", "DEF", "PDS", etc.
        - "116 Standard" -> "Standard"
        - "Room 101 - Deluxe" -> "Deluxe"
        - "Premium Seaview" -> "Premium Seaview"
        
        Args:
            room_input: The raw value from the 'Room' column.
            room_types: Dict mapping lowercase names to RoomType objects.
            
        Returns:
            Tuple of (Matched Object or None, Extracted String Name)
        """
        # 1. Basic Cleaning
        room_str = str(room_input or '').strip()
        if not room_str or room_str.lower() == 'nan':
            return None, ''
        
        # 2. Check SynXis room type codes first
        room_upper = room_str.upper()
        if room_upper in self.SYNXIS_ROOM_TYPE_MAPPING:
            mapped_name = self.SYNXIS_ROOM_TYPE_MAPPING[room_upper]
            if mapped_name.lower() in room_types:
                return room_types[mapped_name.lower()], mapped_name
            return None, mapped_name
        
        # 3. Extract Name (Removing Room Numbers)
        # Handles "116 Standard" or "116 - Standard"
        match = re.match(r'^\d+[\s\-\:]*(.+)$', room_str)
        if match:
            room_type_name = match.group(1).strip()
        else:
            room_type_name = room_str

        room_type_lower = room_type_name.lower()

        # Tier 0: Check explicit admin mapping (RoomTypeMapping) first
        if self.hotel and room_type_name:
            from pricing.models.analytics import RoomTypeMapping
            mapping = RoomTypeMapping.objects.filter(
                hotel=self.hotel,
                import_name__iexact=room_type_name,
            ).select_related('room_type').first()
            if mapping:
                return mapping.room_type, room_type_name

        # 4. Layered Matching Logic (Waterfall)

        # Tier 1: Exact Match
        if room_type_lower in room_types:
            return room_types[room_type_lower], room_type_name
        
        # Tier 2: Substring Matching (Known type inside input OR input inside known type)
        for rt_name, rt_obj in room_types.items():
            if rt_name in room_type_lower or room_type_lower in rt_name:
                return rt_obj, room_type_name
                
        # Tier 3: Keyword Mapping
        keywords_map = {
            'standard': ['standard', 'std'],
            'deluxe': ['deluxe', 'premium', 'dlx'],
            'suite': ['suite', 'family', 'executive'],
            'superior': ['superior', 'sup'],
            'villa': ['villa', 'bungalow'],
            'view': ['sea', 'seaview', 'ocean', 'beach', 'garden', 'pool', 'island']
        }
        
        found_groups = {
            group for group, synonyms in keywords_map.items()
            if any(syn in room_type_lower for syn in synonyms)
        }
        
        if found_groups:
            for rt_name, rt_obj in room_types.items():
                rt_name_lower = rt_name.lower()
                if any(any(syn in rt_name_lower for syn in keywords_map[group]) for group in found_groups):
                    return rt_obj, room_type_name

        # 5. Learn from previous mappings
        # If a past reservation with the same room_type_name was mapped, reuse it
        if self.hotel and room_type_name:
            from pricing.models import Reservation as _Res
            prev_rt_id = _Res.objects.filter(
                hotel=self.hotel,
                room_type_name__iexact=room_type_name,
                room_type__isnull=False
            ).values_list('room_type_id', flat=True).first()
            if prev_rt_id:
                # Find the RoomType in our pre-fetched dict by scanning values
                for rt_obj in room_types.values():
                    if rt_obj.id == prev_rt_id:
                        return rt_obj, room_type_name

        # 6. Fallback: No structured match found
        return None, room_type_name

    # ISO 2-letter code → full country name (shared with MarketIntelligenceService)
    ISO_TO_COUNTRY = {
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
        'HR': 'Croatia', 'RS': 'Serbia', 'BA': 'Bosnia and Herzegovina',
        'ME': 'Montenegro', 'AL': 'Albania', 'MK': 'North Macedonia',
        'LT': 'Lithuania', 'LV': 'Latvia', 'EE': 'Estonia',
        'MT': 'Malta', 'CY': 'Cyprus', 'LU': 'Luxembourg',
        'IS': 'Iceland', 'NZ': 'New Zealand', 'ZW': 'Zimbabwe',
        'KE': 'Kenya', 'NG': 'Nigeria', 'GH': 'Ghana',
        'TN': 'Tunisia', 'MA': 'Morocco', 'DZ': 'Algeria',
        'CL': 'Chile', 'CO': 'Colombia', 'PE': 'Peru',
        'VN': 'Vietnam', 'MM': 'Myanmar', 'KH': 'Cambodia',
        'IR': 'Iran', 'IQ': 'Iraq', 'OM': 'Oman', 'BH': 'Bahrain',
        'AM': 'Armenia', 'AZ': 'Azerbaijan', 'TW': 'Taiwan',
        'HK': 'Hong Kong', 'MO': 'Macau',
    }

    COUNTRY_ALIASES = {
        'United States of America': 'United States',
        'USA': 'United States',
        'UK': 'United Kingdom',
        'UAE': 'United Arab Emirates',
        'S. Korea': 'South Korea',
        'Rep. of Korea': 'South Korea',
    }

    def _normalize_country_name(self, value):
        """Normalize ISO codes and aliases to full country names."""
        if not value or value in ('nan', '-', ''):
            return value
        value = value.strip()
        # ISO 2-letter code
        if len(value) == 2 and value.upper() in self.ISO_TO_COUNTRY:
            return self.ISO_TO_COUNTRY[value.upper()]
        # Known aliases
        if value in self.COUNTRY_ALIASES:
            return self.COUNTRY_ALIASES[value]
        return value

    def _ensure_channels_exist(self):
        """Create default channels for the property if none exist."""
        from pricing.models import Channel

        if not self.hotel:
            return

        existing = Channel.objects.filter(hotel=self.hotel).count()
        if existing > 0:
            return

        defaults = [
            {'name': 'OTA (Booking.com)', 'base_discount_percent': 0, 'commission_percent': 15, 'sort_order': 1},
            {'name': 'Travel Agent', 'base_discount_percent': 22, 'commission_percent': 10, 'sort_order': 2},
            {'name': 'Direct', 'base_discount_percent': 24, 'commission_percent': 0, 'sort_order': 3},
        ]
        for d in defaults:
            Channel.objects.create(hotel=self.hotel, **d)

    def _map_channel(self, source_str: str) -> Optional[Any]:
        """Map source string to Channel object using layered matching."""
        from pricing.models import Channel

        if not source_str or source_str == 'nan':
            return None

        source_lower = source_str.strip().lower()

        # Step 1: Determine canonical channel name from the source string
        channel_name = None
        for key, name in self.CHANNEL_MAPPING.items():
            if key and key in source_lower:
                channel_name = name
                break

        if not channel_name:
            if 'booking.com' in source_lower:
                channel_name = 'Booking.com'
            elif 'agoda' in source_lower:
                channel_name = 'Agoda'
            elif 'expedia' in source_lower:
                channel_name = 'Expedia'
            elif 'trip.com' in source_lower:
                channel_name = 'Trip.com'

        # Step 2: Find matching Channel using layered matching
        qs = Channel.objects.all()
        if self.hotel:
            qs = qs.filter(hotel=self.hotel)

        if channel_name:
            # Tier 1: Exact name match
            match = qs.filter(name__iexact=channel_name).first()
            if match:
                return match

            # Tier 2: Channel name contains the source name (handles "OTA (Booking.com)")
            match = qs.filter(name__icontains=channel_name).first()
            if match:
                return match

            # Tier 3: Cross-check containment
            for ch in qs:
                ch_lower = ch.name.lower()
                if channel_name.lower() in ch_lower or ch_lower in channel_name.lower():
                    return ch

        # Tier 4: Fall back to OTA/Direct/Agent category matching
        category_map = {
            'ota': ['booking.com', 'agoda', 'expedia', 'trip.com', 'hostelworld',
                    'bookmybooking', 'internet booking'],
            'direct': ['direct', 'walk-in', 'walk in', 'website', 'fit',
                       'web booking', 'internet booking', 'house use',
                       'complimentary', 'owner', 'fam trip'],
            'agent': ['travel', 'agent', 'operator', 'tribe', 'tours',
                      'malvi', 'island story', 'awesome'],
        }

        source_category = None
        for cat, keywords in category_map.items():
            if any(kw in source_lower for kw in keywords):
                source_category = cat
                break

        if source_category:
            for ch in qs:
                ch_lower = ch.name.lower()
                if source_category == 'ota' and ('ota' in ch_lower or 'booking' in ch_lower):
                    return ch
                if source_category == 'direct' and 'direct' in ch_lower:
                    return ch
                if source_category == 'agent' and ('agent' in ch_lower or 'travel' in ch_lower):
                    return ch

        return None
    
    def _map_rate_plan(self, rate_plan_str: str, rate_plans: Dict) -> Tuple[Optional[Any], str]:
        """
        Map rate plan string to RatePlan model.
        
        Returns:
            Tuple of (RatePlan or None, original rate plan name)
        """
        rate_plan_str = str(rate_plan_str or '').strip()
        
        if not rate_plan_str or rate_plan_str == 'nan':
            return None, ''
        
        rate_plan_lower = rate_plan_str.lower()
        
        # Exact match
        if rate_plan_lower in rate_plans:
            return rate_plans[rate_plan_lower], rate_plan_str
        
        # Common abbreviation mappings
        abbreviation_map = {
            'ro': 'room only',
            'bb': 'bed & breakfast',
            'b&b': 'bed & breakfast',
            'bed and breakfast': 'bed & breakfast',
            'hb': 'half board',
            'fb': 'full board',
            'ai': 'all inclusive',
        }
        
        expanded = abbreviation_map.get(rate_plan_lower)
        if expanded and expanded in rate_plans:
            return rate_plans[expanded], rate_plan_str
        
        # Also try the expanded form directly
        if rate_plan_lower in abbreviation_map.values():
            for rp_name, rp in rate_plans.items():
                if rate_plan_lower in rp_name or rp_name in rate_plan_lower:
                    return rp, rate_plan_str
        
        # Partial match
        for rp_name, rp in rate_plans.items():
            if rp_name in rate_plan_lower or rate_plan_lower in rp_name:
                return rp, rate_plan_str
        
        return None, rate_plan_str
    
    def _map_status(self, status_str: str) -> str:
        """Map status string to model choice."""
        status_str = str(status_str or '').strip().lower()
        
        for status_choice, variations in self.STATUS_MAPPING.items():
            if status_str in variations:
                return status_choice
        
        return 'confirmed'  # Default
    
    def _parse_date(self, value) -> Optional[date]:
        """Parse date from various formats including SynXis datetime with AM/PM."""
        if pd.isna(value):
            return None
        
        if isinstance(value, (datetime, date)):
            return value.date() if isinstance(value, datetime) else value
        
        value = str(value).strip()
        
        if not value or value == 'nan' or value == '-':
            return None
        
        # Date formats to try - ORDER MATTERS (most specific first)
        formats = [
            # SynXis Activity Report format (MUST BE FIRST)
            '%Y-%m-%d %I:%M %p',       # 2025-06-06 2:30 PM
            '%Y-%m-%d %I:%M:%S %p',    # 2025-06-06 2:30:00 PM
            
            # DateTime formats with AM/PM
            '%d-%m-%Y %I:%M:%S %p',    # 19-01-2026 11:31:00 AM
            '%d-%m-%Y %H:%M:%S',       # 19-01-2026 11:31:00
            '%d/%m/%Y %I:%M:%S %p',    # 19/01/2026 11:31:00 AM
            '%d/%m/%Y %H:%M:%S',       # 19/01/2026 11:31:00
            
            # Date-only formats
            '%Y-%m-%d',    # 2026-01-02
            '%d-%m-%Y',    # 02-01-2026
            '%d/%m/%Y',    # 02/01/2026
            '%m/%d/%Y',    # 01/02/2026
            '%Y/%m/%d',    # 2026/01/02
            '%d.%m.%Y',    # 02.01.2026
            '%d %b %Y',    # 02 Jan 2026
            '%d %B %Y',    # 02 January 2026
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.date()
            except ValueError:
                continue
        
        return None
    
    def _parse_int(self, value, default: int = 0) -> int:
        """Parse integer from value."""
        if pd.isna(value):
            return default
        
        try:
            # Handle string values that might have extra characters
            val_str = str(value).strip()
            if not val_str or val_str == 'nan' or val_str == '-':
                return default
            return int(float(val_str))
        except (ValueError, TypeError):
            return default
    
    def _parse_decimal(self, value, default: Decimal = None) -> Decimal:
        """Parse decimal from value."""
        if default is None:
            default = Decimal('0.00')
        
        if pd.isna(value):
            return default
        
        try:
            # Remove currency symbols, commas, and handle negative with prefix
            value_str = str(value).strip()
            
            if not value_str or value_str == 'nan' or value_str == '-':
                return default
            
            # Handle "-0" format
            if value_str == '-0':
                return Decimal('0.00')
            
            value_str = value_str.replace('$', '').replace(',', '').strip()
            return Decimal(value_str).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            return default
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def _link_multi_room_bookings(self, file_import) -> None:
        """
        Link multi-room bookings after import.
        
        Finds reservations with sequence > 1 and links them to sequence 1.
        """
        from pricing.models import Reservation
        
        # Find all reservations with sequence > 1 from this import
        multi_room_qs = Reservation.objects.filter(
            file_import=file_import,
            room_sequence__gt=1
        )
        
        if self.hotel:
            multi_room_qs = multi_room_qs.filter(hotel=self.hotel)
        
        for res in multi_room_qs:
            # Find the parent (sequence 1) with same confirmation AND arrival date
            parent_lookup = {
                'confirmation_no': res.confirmation_no,
                'arrival_date': res.arrival_date,
                'room_sequence': 1
            }
            if self.hotel:
                parent_lookup['hotel'] = self.hotel
            
            parent = Reservation.objects.filter(**parent_lookup).first()
            
            if parent:
                res.parent_reservation = parent
                res.is_multi_room = True
                res.save(update_fields=['parent_reservation', 'is_multi_room'])
                
                # Also mark the parent as multi-room
                if not parent.is_multi_room:
                    parent.is_multi_room = True
                    parent.save(update_fields=['is_multi_room'])

    def _clear_cancellations(self, file_import):
        """
        Post-import clearing: match cancelled bookings to their original
        confirmed bookings and update the originals.

        For each cancelled booking imported in this batch, search for an
        existing confirmed booking with matching guest + arrival + departure.
        If found, update the original to cancelled and remove the duplicate.

        Matching tiers (stops at first match):
          Tier 1: guest + arrival + departure + room + amount (exact)
          Tier 2: guest + arrival + departure + room (amount differs)
          Tier 3: guest + arrival + departure (room differs)
        """
        from pricing.models import Reservation

        # Only process cancelled bookings from this import
        new_cancelled = Reservation.objects.filter(
            hotel=self.hotel,
            file_import=file_import,
            status='cancelled',
            guest__isnull=False,
        ).select_related('guest')

        cleared = 0
        for cancel_rec in new_cancelled:
            if not cancel_rec.guest or not cancel_rec.guest.name:
                continue

            base_filter = dict(
                hotel=self.hotel,
                status__in=Reservation.ACTIVE_STATUSES,
                guest__name=cancel_rec.guest.name,
                arrival_date=cancel_rec.arrival_date,
                departure_date=cancel_rec.departure_date,
            )

            # Tier 1: exact match
            original = Reservation.objects.filter(
                **base_filter,
                room_type_name=cancel_rec.room_type_name,
                total_amount=cancel_rec.total_amount,
            ).exclude(id=cancel_rec.id).first()

            # Tier 2: guest + arrival + departure + room
            if not original:
                original = Reservation.objects.filter(
                    **base_filter,
                    room_type_name=cancel_rec.room_type_name,
                ).exclude(id=cancel_rec.id).first()

            # Tier 3: guest + arrival + departure
            if not original:
                original = Reservation.objects.filter(
                    **base_filter,
                ).exclude(id=cancel_rec.id).first()

            if original:
                # Update the original confirmed booking to cancelled
                original.status = 'cancelled'
                original.cancellation_date = cancel_rec.cancellation_date
                original.cancellation_reason = cancel_rec.cancellation_reason or original.cancellation_reason
                original.save(update_fields=[
                    'status', 'cancellation_date', 'cancellation_reason',
                ])
                # Remove the duplicate cancelled record
                cancel_rec.delete()
                cleared += 1

        if cleared > 0:
            self.errors.append({
                'row': 0,
                'message': f'Cancellation clearing: matched {cleared} cancelled bookings '
                           f'to their original confirmed bookings'
            })

    def _build_result(self, file_import) -> Dict:
        """Build result dictionary from file import."""
        from pricing.models import Reservation

        result = {
            'success': file_import.status in ['completed', 'completed_with_errors'],
            'file_import_id': file_import.id,
            'filename': file_import.filename,
            'status': file_import.status,
            'rows_total': file_import.rows_total,
            'rows_created': file_import.rows_created,
            'rows_updated': file_import.rows_updated,
            'rows_skipped': file_import.rows_skipped,
            'success_rate': float(file_import.success_rate) if hasattr(file_import, 'success_rate') else 0,
            'errors': file_import.errors,
            'duration_seconds': file_import.duration_seconds if hasattr(file_import, 'duration_seconds') else 0,
        }

        # Data quality summary
        if file_import.status in ['completed', 'completed_with_errors'] and self.hotel:
            import_qs = Reservation.objects.filter(hotel=self.hotel, file_import=file_import)
            total = import_qs.count()
            if total > 0:
                ch_mapped = import_qs.filter(channel__isnull=False).count()
                rt_mapped = import_qs.filter(room_type__isnull=False).count()
                result['data_quality'] = {
                    'channel_mapped': ch_mapped,
                    'channel_unmapped': total - ch_mapped,
                    'room_type_mapped': rt_mapped,
                    'room_type_unmapped': total - rt_mapped,
                    'unmapped_sources': list(
                        import_qs.filter(channel__isnull=True)
                        .values_list('booking_source__name', flat=True)
                        .distinct()[:10]
                    ),
                    'unmapped_room_names': list(
                        import_qs.filter(room_type__isnull=True)
                        .values_list('room_type_name', flat=True)
                        .distinct()[:10]
                    ),
                }

        return result
    
    def validate_file(self, file_path: str) -> Dict:
        """
        Validate a file before importing.
        
        Checks:
        - File can be read
        - Required columns exist
        - Date formats are valid
        - No duplicate confirmation numbers
        
        Returns:
            Dict with validation results
        """
        file_path = Path(file_path)
        issues = []
        warnings = []
        
        # Check file exists
        if not file_path.exists():
            return {
                'valid': False,
                'issues': [{'message': 'File not found'}],
                'warnings': [],
            }
        
        # Read file
        df = self._read_file(file_path)
        
        if df is None or df.empty:
            return {
                'valid': False,
                'issues': [{'message': 'File is empty or could not be read'}],
                'warnings': [],
            }
        
        # Clean Excel escapes
        df = self._clean_excel_escapes(df)
        
        # Map columns
        df = self._map_columns(df)
        
        # Check required columns
        required = {'confirmation_no', 'arrival_date', 'departure_date'}
        present = set(df.columns)
        missing = required - present
        
        if missing:
            issues.append({
                'message': f'Missing required columns: {missing}'
            })
        
        # Filter invalid confirmation numbers for stats
        if 'confirmation_no' in df.columns:
            df['_conf_str'] = df['confirmation_no'].astype(str)
            invalid_conf = len(df[~df['_conf_str'].str.match(r'^\d+$', na=False)])
            if invalid_conf > 0:
                warnings.append({
                    'message': f'{invalid_conf} rows with invalid confirmation numbers will be filtered'
                })
            df = df[df['_conf_str'].str.match(r'^\d+$', na=False)]
            df = df.drop(columns=['_conf_str'])
        
        # Check for day-use bookings
        if 'nights' in df.columns:
            day_use_count = len(df[df['nights'].fillna(0).astype(float).astype(int) == 0])
            if day_use_count > 0:
                warnings.append({
                    'message': f'{day_use_count} day-use bookings will be filtered out'
                })
        
        # Check for cancelled reservations (SynXis Type column)
        if 'reservation_type' in df.columns:
            type_counts = df['reservation_type'].value_counts()
            if 'Cancel' in type_counts.index:
                warnings.append({
                    'message': f'{type_counts["Cancel"]} cancelled reservations (Type=Cancel) - will be imported with status=cancelled'
                })
            if 'New' in type_counts.index:
                warnings.append({
                    'message': f'{type_counts["New"]} new reservations (Type=New) - will be imported with status=confirmed'
                })
            if 'Amend' in type_counts.index:
                warnings.append({
                    'message': f'{type_counts["Amend"]} amended reservations (Type=Amend) - will be imported with status=confirmed'
                })
        elif 'status' in df.columns:
            cancelled_count = len(df[df['status'].str.lower().str.contains('cancel', na=False)])
            if cancelled_count > 0:
                warnings.append({
                    'message': f'{cancelled_count} cancelled reservations found'
                })
        
        # Check date validity
        if 'arrival_date' in df.columns:
            invalid_dates = 0
            for val in df['arrival_date'].dropna():
                if self._parse_date(val) is None:
                    invalid_dates += 1
            
            if invalid_dates > 0:
                issues.append({
                    'message': f'{invalid_dates} rows have invalid arrival dates'
                })
        
        # Summary stats
        stats = {
            'total_rows': len(df),
            'columns_found': list(df.columns),
            'date_range': None,
            'is_synxis_activity': self._is_synxis_activity,
        }
        
        if 'arrival_date' in df.columns:
            dates = [self._parse_date(d) for d in df['arrival_date'].dropna()]
            valid_dates = [d for d in dates if d]
            if valid_dates:
                stats['date_range'] = {
                    'start': min(valid_dates).isoformat(),
                    'end': max(valid_dates).isoformat(),
                }
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'stats': stats,
        }
        

"""
Booking Analysis Service.

Calculates dashboard metrics from Reservation data:
- KPIs (Total Revenue, Room Nights, ADR, Occupancy, Reservations)
- Cancellation Metrics (Count, Rate, Lost Revenue, by Channel)
- Monthly breakdown (Revenue, Room Nights, Available, Occupancy, ADR)
- Channel mix
- Meal plan mix
- Room type performance

Usage:
    from pricing.services.booking_analysis import BookingAnalysisService
    
    # For specific property
    service = BookingAnalysisService(property=prop)
    data = service.get_dashboard_data(year=2026)
    
    # For all properties (legacy)
    service = BookingAnalysisService()
    data = service.get_dashboard_data(year=2026)
"""

from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from django.db.models import Sum, Count, Avg, Min, Max, Q, F
from django.db.models.functions import TruncMonth
import calendar


class BookingAnalysisService:
    """
    Service for analyzing booking/reservation data.
    
    Generates metrics for the Booking Analysis Dashboard including
    cancellation analysis.
    
    Supports multi-property filtering via the property parameter.
    """
    
    def __init__(self, property=None):
        """
        Initialize the service.
        
        Args:
            property: Optional Property instance to filter reservations.
                     If None, analyzes all reservations (legacy behavior).
        """
        self.property = property
    
    def _get_base_queryset(self):
        """Get base Reservation queryset with optional property filtering."""
        from pricing.models import Reservation
        
        queryset = Reservation.objects.all()
        
        if self.property:
            queryset = queryset.filter(hotel=self.property)
        
        return queryset
    
    def _get_room_types(self):
        """Get RoomType queryset with optional property filtering."""
        from pricing.models import RoomType
        
        queryset = RoomType.objects.all()
        
        if self.property:
            # FIX: RoomType uses 'hotel' field, not 'property'
            queryset = queryset.filter(hotel=self.property)
        
        return queryset
    
    def get_dashboard_data(self, year=None, start_date=None, end_date=None, include_cancelled=False):
        """
        Get all dashboard data for a given period.

        Args:
            year: Optional year to filter by arrival date (default: current year)
            start_date: Optional start date for custom range
            end_date: Optional end date for custom range
            include_cancelled: If True, include cancelled bookings in main metrics

        Returns:
            Dict with all dashboard data
        """
        from pricing.models import Reservation
        # Default to current year
        if year is None and start_date is None:
            year = date.today().year
        
        # Build base querysets with property filtering
        base_queryset = self._get_base_queryset()
        
        # ACTIVE bookings (exclude cancelled)
        active_queryset = base_queryset.filter(
            status__in=Reservation.ACTIVE_STATUSES
        )
        
        # CANCELLED bookings
        cancelled_queryset = base_queryset.filter(
            status='cancelled'
        )
        
        # ALL bookings
        all_queryset = base_queryset
        
        # Apply date filters
        if start_date and end_date:
            active_queryset = active_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
            cancelled_queryset = cancelled_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
            all_queryset = all_queryset.filter(
                arrival_date__gte=start_date,
                arrival_date__lte=end_date
            )
        elif year:
            active_queryset = active_queryset.filter(arrival_date__year=year)
            cancelled_queryset = cancelled_queryset.filter(arrival_date__year=year)
            all_queryset = all_queryset.filter(arrival_date__year=year)
        
        # Get total rooms for occupancy calculation (with property filtering)
        room_types = self._get_room_types()
        total_rooms = self.property.get_total_rooms() if self.property else (sum(rt.number_of_rooms for rt in room_types) or 1)
        
        # Calculate all metrics
        kpis = self._calculate_kpis(active_queryset, total_rooms, year)
        cancellation_metrics = self._calculate_cancellation_metrics(
            cancelled_queryset, all_queryset, year
        )
        monthly_data = self._calculate_monthly_data(active_queryset, total_rooms, year)
        monthly_cancellations = self._calculate_monthly_cancellations(cancelled_queryset, year)
        channel_mix = self._calculate_channel_mix(active_queryset)
        cancellation_by_channel = self._calculate_cancellation_by_channel(
            cancelled_queryset, all_queryset
        )
        meal_plan_mix = self._calculate_meal_plan_mix(active_queryset)
        room_type_performance = self._calculate_room_type_performance(active_queryset)
        
        return {
            'year': year,
            'start_date': start_date,
            'end_date': end_date,
            'total_rooms': total_rooms,
            'kpis': kpis,
            'cancellation_metrics': cancellation_metrics,
            'monthly_data': monthly_data,
            'monthly_cancellations': monthly_cancellations,
            'channel_mix': channel_mix,
            'cancellation_by_channel': cancellation_by_channel,
            'meal_plan_mix': meal_plan_mix,
            'room_type_performance': room_type_performance,
        }
    
    def _calculate_kpis(self, queryset, total_rooms, year):
        """
        Calculate KPI card values from confirmed bookings, prorated to year.
        """
        from pricing.models import Reservation

        if year:
            period_start = date(year, 1, 1)
            period_end = date(year, 12, 31)
        else:
            period_start = date.today().replace(month=1, day=1)
            period_end = date.today().replace(month=12, day=31)

        period_next = period_end + timedelta(days=1)

        base_qs = Reservation.objects.all()
        if self.property:
            base_qs = base_qs.filter(hotel=self.property)

        overlapping = base_qs.filter(
            status__in=Reservation.ACTIVE_STATUSES,
            arrival_date__lt=period_next,
            departure_date__gt=period_start,
        ).values('arrival_date', 'departure_date', 'nights', 'total_amount')

        room_nights = 0
        total_revenue = Decimal('0.00')
        reservation_count = 0

        for r in overlapping:
            stay_start = max(r['arrival_date'], period_start)
            stay_end = min(r['departure_date'], period_next)
            period_nights = (stay_end - stay_start).days
            if period_nights <= 0:
                continue
            total_nights = r['nights'] or (r['departure_date'] - r['arrival_date']).days
            fraction = period_nights / total_nights if total_nights > 0 else 0
            room_nights += period_nights
            total_revenue += Decimal(str(float(r['total_amount'] or 0) * fraction))
            reservation_count += 1

        avg_adr = Decimal('0.00')
        if room_nights > 0:
            avg_adr = (total_revenue / room_nights).quantize(Decimal('0.01'))

        avg_occupancy = Decimal('0.0')
        if year:
            days_in_year = 366 if calendar.isleap(year) else 365
            total_available = total_rooms * days_in_year
            if total_available > 0:
                avg_occupancy = (
                    Decimal(str(room_nights)) / Decimal(str(total_available)) * 100
                ).quantize(Decimal('0.1'))

        return {
            'total_revenue': total_revenue,
            'room_nights': room_nights,
            'avg_adr': avg_adr,
            'avg_occupancy': avg_occupancy,
            'reservations': reservation_count,
        }
    
    def _calculate_cancellation_metrics(self, cancelled_queryset, all_queryset, year):
        """
        Calculate cancellation-specific metrics.
        
        Returns:
            Dict with cancellation count, rate, lost revenue, avg lead time
        """
        from django.db.models import Sum, Count, F
        
        # Count cancelled bookings
        cancelled_stats = cancelled_queryset.aggregate(
            count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        )
        
        # Total bookings (all statuses)
        total_bookings = all_queryset.count()
        
        cancelled_count = cancelled_stats['count'] or 0
        lost_revenue = cancelled_stats['lost_revenue'] or Decimal('0.00')
        lost_room_nights = cancelled_stats['lost_room_nights'] or 0
        
        # Calculate cancellation rate
        cancellation_rate = Decimal('0.0')
        if total_bookings > 0:
            cancellation_rate = (
                Decimal(str(cancelled_count)) / Decimal(str(total_bookings)) * 100
            ).quantize(Decimal('0.1'))
        
        # Calculate average cancellation lead time
        # (days between booking_date and cancellation_date)
        cancellations_with_dates = cancelled_queryset.filter(
            cancellation_date__isnull=False,
            booking_date__isnull=False
        ).annotate(
            lead_time=F('cancellation_date') - F('booking_date')
        )
        
        avg_cancel_lead_time = 0
        if cancellations_with_dates.exists():
            # Calculate average days
            total_days = 0
            count = 0
            for res in cancellations_with_dates:
                if res.lead_time:
                    total_days += res.lead_time.days
                    count += 1
            if count > 0:
                avg_cancel_lead_time = round(total_days / count, 1)
        
        # Calculate average days before arrival when cancelled
        # (days between cancellation_date and arrival_date)
        avg_days_before_arrival = 0
        cancellations_with_arrival = cancelled_queryset.filter(
            cancellation_date__isnull=False,
            arrival_date__isnull=False
        )
        
        if cancellations_with_arrival.exists():
            total_days = 0
            count = 0
            for res in cancellations_with_arrival:
                days_before = (res.arrival_date - res.cancellation_date).days
                if days_before >= 0:  # Only count if cancelled before arrival
                    total_days += days_before
                    count += 1
            if count > 0:
                avg_days_before_arrival = round(total_days / count, 1)
        
        return {
            'count': cancelled_count,
            'rate': cancellation_rate,
            'lost_revenue': lost_revenue,
            'lost_room_nights': lost_room_nights,
            'total_bookings': total_bookings,
            'avg_cancel_lead_time': avg_cancel_lead_time,  # Days after booking
            'avg_days_before_arrival': avg_days_before_arrival,  # Days before arrival
        }
    
    def _calculate_monthly_data(self, queryset, total_rooms, year):
        """
        Calculate monthly breakdown. Confirmed bookings only, prorated.
        """
        from pricing.models import Reservation

        monthly_data = []
        if not year:
            year = date.today().year

        base_qs = Reservation.objects.all()
        if self.property:
            base_qs = base_qs.filter(hotel=self.property)

        year_start = date(year, 1, 1)
        year_end = date(year + 1, 1, 1)

        all_res = list(base_qs.filter(
            status__in=Reservation.ACTIVE_STATUSES,
            arrival_date__lt=year_end,
            departure_date__gt=year_start,
        ).values('arrival_date', 'departure_date', 'nights', 'total_amount'))

        for month_num in range(1, 13):
            days_in_month = calendar.monthrange(year, month_num)[1]
            available = total_rooms * days_in_month
            month_start = date(year, month_num, 1)
            month_next = date(year + (1 if month_num == 12 else 0),
                              (month_num % 12) + 1, 1)

            rn = 0
            rev = 0.0
            bk = 0
            for r in all_res:
                stay_start = max(r['arrival_date'], month_start)
                stay_end = min(r['departure_date'], month_next)
                month_nights = (stay_end - stay_start).days
                if month_nights <= 0:
                    continue
                total_nights = r['nights'] or (r['departure_date'] - r['arrival_date']).days
                fraction = month_nights / total_nights if total_nights > 0 else 0
                rn += month_nights
                rev += float(r['total_amount'] or 0) * fraction
                bk += 1
            revenue = Decimal(str(round(rev, 2)))
            occupancy = Decimal('0.0')
            if available > 0:
                occupancy = (Decimal(str(rn)) / Decimal(str(available)) * 100).quantize(Decimal('0.1'))
            adr = Decimal('0.00')
            if rn > 0:
                adr = (revenue / rn).quantize(Decimal('0.01'))

            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'month_full': calendar.month_name[month_num],
                'revenue': revenue,
                'room_nights': rn,
                'available': available,
                'occupancy': occupancy,
                'adr': adr,
                'bookings': bk,
            })

        return monthly_data
    
    def _calculate_monthly_cancellations(self, cancelled_queryset, year):
        """
        Calculate monthly cancellation breakdown.
        
        Returns:
            List of dicts with month, cancelled_count, lost_revenue, lost_room_nights
        """
        from django.db.models import Sum, Count
        
        monthly_data = []
        
        # Initialize all 12 months
        for month_num in range(1, 13):
            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'cancelled_count': 0,
                'lost_revenue': Decimal('0.00'),
                'lost_room_nights': 0,
            })
        
        # Aggregate cancellations by arrival month
        monthly_stats = cancelled_queryset.values('arrival_date__month').annotate(
            cancelled_count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        ).order_by('arrival_date__month')
        
        # Fill in actual data
        for stat in monthly_stats:
            month_idx = stat['arrival_date__month'] - 1
            monthly_data[month_idx]['cancelled_count'] = stat['cancelled_count'] or 0
            monthly_data[month_idx]['lost_revenue'] = stat['lost_revenue'] or Decimal('0.00')
            monthly_data[month_idx]['lost_room_nights'] = stat['lost_room_nights'] or 0
        
        return monthly_data

    def get_bookings_and_arrivals(self, year=None):
        """
        Bookings & Arrivals split for a year.

        Bookings (activity by booking_date / cancellation_date):
          Per month: new confirmed bookings made, cancellations that happened,
          net bookings, and arrival-month distribution of those bookings.

        Arrivals (position by arrival_date):
          Per month: all confirmed minus all cancelled = net room nights.
          Prorated for stays spanning month boundaries.

        Returns dict with 'bookings_by_month' and 'arrivals_by_month'.
        """
        from pricing.models import Reservation

        if not year:
            year = date.today().year

        base_qs = Reservation.objects.all()
        if self.property:
            base_qs = base_qs.filter(hotel=self.property)

        total_rooms = (self.property.get_total_rooms()
                       if self.property else 1)

        # ── Bookings: activity during each month ─────────────────────────
        bookings_by_month = []
        for month_num in range(1, 13):
            days_in_month = calendar.monthrange(year, month_num)[1]
            m_start = date(year, month_num, 1)
            m_end = date(year, month_num, days_in_month)

            # New confirmed bookings made during this month
            confirmed = base_qs.filter(
                status__in=Reservation.ACTIVE_STATUSES,
                booking_date__gte=m_start,
                booking_date__lte=m_end,
            )
            conf_count = confirmed.count()
            conf_rn = confirmed.aggregate(t=Sum('nights'))['t'] or 0
            conf_rev = float(confirmed.aggregate(t=Sum('total_amount'))['t'] or 0)

            # Cancellations during this month
            cancelled = base_qs.filter(
                status='cancelled',
                cancellation_date__gte=m_start,
                cancellation_date__lte=m_end,
            )
            canc_count = cancelled.count()
            canc_rn = cancelled.aggregate(t=Sum('nights'))['t'] or 0
            canc_rev = float(cancelled.aggregate(t=Sum('total_amount'))['t'] or 0)

            net_count = conf_count - canc_count
            net_rn = conf_rn - canc_rn
            net_rev = conf_rev - canc_rev

            # Arrival-month distribution of bookings made this month
            arrival_dist = list(
                confirmed.values('arrival_date__month').annotate(
                    rn=Sum('nights'), cnt=Count('id'),
                ).order_by('arrival_date__month')
            )

            # Arrival-month distribution of cancellations this month
            cancel_dist = list(
                cancelled.values('arrival_date__month').annotate(
                    rn=Sum('nights'), cnt=Count('id'),
                ).order_by('arrival_date__month')
            )

            bookings_by_month.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'confirmed': conf_count,
                'confirmed_rn': conf_rn,
                'confirmed_rev': conf_rev,
                'cancelled': canc_count,
                'cancelled_rn': canc_rn,
                'cancelled_rev': canc_rev,
                'net': net_count,
                'net_rn': net_rn,
                'net_rev': net_rev,
                'arrival_distribution': [
                    {'arrival_month': d['arrival_date__month'],
                     'rn': d['rn'] or 0, 'count': d['cnt']}
                    for d in arrival_dist
                ],
                'cancel_distribution': [
                    {'arrival_month': d['arrival_date__month'],
                     'rn': d['rn'] or 0, 'count': d['cnt']}
                    for d in cancel_dist
                ],
            })

        # ── Arrivals: position for each month ────────────────────────────
        year_start = date(year, 1, 1)
        year_end = date(year + 1, 1, 1)

        all_res = list(base_qs.filter(
            arrival_date__lt=year_end,
            departure_date__gt=year_start,
        ).exclude(status='no_show').values(
            'arrival_date', 'departure_date', 'nights', 'total_amount', 'status',
        ))

        arrivals_by_month = []
        for month_num in range(1, 13):
            days_in_month = calendar.monthrange(year, month_num)[1]
            available = total_rooms * days_in_month
            m_start = date(year, month_num, 1)
            m_next = date(year + (1 if month_num == 12 else 0),
                          (month_num % 12) + 1, 1)

            gross_rn = 0
            gross_rev = 0.0
            gross_bk = 0
            cancel_rn = 0
            cancel_rev = 0.0
            cancel_bk = 0

            for r in all_res:
                stay_start = max(r['arrival_date'], m_start)
                stay_end = min(r['departure_date'], m_next)
                month_nights = (stay_end - stay_start).days
                if month_nights <= 0:
                    continue

                total_nights = (r['nights']
                                or (r['departure_date'] - r['arrival_date']).days)
                fraction = (month_nights / total_nights
                            if total_nights > 0 else 0)
                prorated_rev = float(r['total_amount'] or 0) * fraction

                if r['status'] in Reservation.ACTIVE_STATUSES:
                    gross_rn += month_nights
                    gross_rev += prorated_rev
                    gross_bk += 1
                elif r['status'] == 'cancelled':
                    cancel_rn += month_nights
                    cancel_rev += prorated_rev
                    cancel_bk += 1

            net_rn = max(gross_rn - cancel_rn, 0)
            net_rev = max(gross_rev - cancel_rev, 0)
            occ = round(net_rn / available * 100, 1) if available > 0 else 0
            adr = round(net_rev / net_rn, 2) if net_rn > 0 else 0

            arrivals_by_month.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'gross_rn': gross_rn,
                'gross_rev': round(gross_rev, 2),
                'gross_bookings': gross_bk,
                'cancel_rn': cancel_rn,
                'cancel_rev': round(cancel_rev, 2),
                'cancel_bookings': cancel_bk,
                'net_rn': net_rn,
                'net_rev': round(net_rev, 2),
                'net_bookings': gross_bk - cancel_bk,
                'available': available,
                'occupancy': occ,
                'adr': adr,
            })

        return {
            'year': year,
            'total_rooms': total_rooms,
            'bookings_by_month': bookings_by_month,
            'arrivals_by_month': arrivals_by_month,
        }

    def _calculate_channel_mix(self, queryset):
        """
        Calculate channel/source breakdown.
        
        Returns:
            List of dicts with channel, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        channel_data = []
        
        # Try to group by channel first
        channel_stats = queryset.values(
            'channel__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # If no channel data, try booking_source
        if not channel_stats.exists() or all(s['channel__name'] is None for s in channel_stats):
            channel_stats = queryset.values(
                'booking_source__name'
            ).annotate(
                bookings=Count('id'),
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
            ).order_by('-revenue')
            
            name_field = 'booking_source__name'
        else:
            name_field = 'channel__name'
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        for stat in channel_stats:
            name = stat.get(name_field) or 'Unknown'
            revenue = stat['revenue'] or Decimal('0.00')
            
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            channel_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        return channel_data
    
    def _calculate_cancellation_by_channel(self, cancelled_queryset, all_queryset):
        """
        Calculate cancellation rate by channel.
        
        Returns:
            List of dicts with channel, cancelled_count, total_count, rate, lost_revenue
        """
        from django.db.models import Sum, Count
        
        channel_data = []
        
        # Get cancelled by channel
        cancelled_by_channel = cancelled_queryset.values(
            'channel__name'
        ).annotate(
            cancelled_count=Count('id'),
            lost_revenue=Sum('total_amount'),
            lost_room_nights=Sum('nights'),
        ).order_by('-cancelled_count')
        
        # Get total by channel
        total_by_channel = all_queryset.values(
            'channel__name'
        ).annotate(
            total_count=Count('id'),
        )
        
        # Build lookup for totals
        total_lookup = {
            stat['channel__name']: stat['total_count'] 
            for stat in total_by_channel
        }
        
        for stat in cancelled_by_channel:
            name = stat.get('channel__name') or 'Unknown'
            cancelled_count = stat['cancelled_count'] or 0
            total_count = total_lookup.get(name, cancelled_count)
            
            # Calculate cancellation rate for this channel
            rate = Decimal('0.0')
            if total_count > 0:
                rate = (
                    Decimal(str(cancelled_count)) / Decimal(str(total_count)) * 100
                ).quantize(Decimal('0.1'))
            
            channel_data.append({
                'name': name,
                'cancelled_count': cancelled_count,
                'total_count': total_count,
                'rate': rate,
                'lost_revenue': stat['lost_revenue'] or Decimal('0.00'),
                'lost_room_nights': stat['lost_room_nights'] or 0,
            })
        
        # Sort by cancellation rate (highest first)
        channel_data.sort(key=lambda x: x['rate'], reverse=True)
        
        return channel_data
    
    def _calculate_meal_plan_mix(self, queryset):
        """
        Calculate meal plan/rate plan breakdown.
        
        Returns:
            List of dicts with meal_plan, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        meal_plan_data = []
        
        # Group by rate_plan
        plan_stats = queryset.values(
            'rate_plan__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # If no rate_plan data, try rate_plan_name
        if not plan_stats.exists() or all(s['rate_plan__name'] is None for s in plan_stats):
            plan_stats = queryset.values(
                'rate_plan_name'
            ).annotate(
                bookings=Count('id'),
                revenue=Sum('total_amount'),
                room_nights=Sum('nights'),
            ).order_by('-revenue')
            
            name_field = 'rate_plan_name'
        else:
            name_field = 'rate_plan__name'
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        for stat in plan_stats:
            name = stat.get(name_field) or 'Unknown'
            revenue = stat['revenue'] or Decimal('0.00')
            
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            meal_plan_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        return meal_plan_data
    
    def _calculate_room_type_performance(self, queryset):
        """
        Calculate room type breakdown.
        
        Groups by room_type FK if available, otherwise by room_type_name.
        
        Returns:
            List of dicts with room_type, bookings, revenue, percent
        """
        from django.db.models import Sum, Count
        
        room_type_data = []
        
        # First, try to get stats for reservations WITH room_type FK
        rt_stats_fk = queryset.filter(
            room_type__isnull=False
        ).values(
            'room_type__name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        # Then, get stats for reservations WITHOUT room_type FK (use room_type_name)
        rt_stats_name = queryset.filter(
            room_type__isnull=True
        ).values(
            'room_type_name'
        ).annotate(
            bookings=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        ).order_by('-revenue')
        
        total_revenue = queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('1.00')
        
        # Combine results - first from FK, then from name
        seen_names = set()
        
        for stat in rt_stats_fk:
            name = stat.get('room_type__name') or 'Unknown'
            if name in seen_names:
                continue
            seen_names.add(name.lower())
            
            revenue = stat['revenue'] or Decimal('0.00')
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            room_type_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        for stat in rt_stats_name:
            name = stat.get('room_type_name') or 'Unknown'
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            
            revenue = stat['revenue'] or Decimal('0.00')
            percent = Decimal('0')
            if total_revenue > 0:
                percent = (revenue / total_revenue * 100).quantize(Decimal('0.1'))
            
            room_type_data.append({
                'name': name,
                'bookings': stat['bookings'],
                'revenue': revenue,
                'room_nights': stat['room_nights'] or 0,
                'percent': percent,
            })
        
        # Sort by revenue descending
        room_type_data.sort(key=lambda x: x['revenue'], reverse=True)
        
        return room_type_data
    
    def get_chart_data(self, year=None):
        """
        Get data formatted for Chart.js charts.
        
        Returns:
            Dict with chart-ready data (lists for labels, values, etc.)
            All Decimal values are converted to float for JSON serialization.
        """
        dashboard_data = self.get_dashboard_data(year=year)
        monthly = dashboard_data['monthly_data']
        monthly_cancel = dashboard_data['monthly_cancellations']
        
        # Helper to convert Decimal to float
        def to_float(val):
            if isinstance(val, Decimal):
                return float(val)
            return val
        
        # Convert KPIs to JSON-safe format
        kpis_safe = {
            'total_revenue': to_float(dashboard_data['kpis']['total_revenue']),
            'room_nights': dashboard_data['kpis']['room_nights'],
            'avg_adr': to_float(dashboard_data['kpis']['avg_adr']),
            'avg_occupancy': to_float(dashboard_data['kpis']['avg_occupancy']),
            'reservations': dashboard_data['kpis']['reservations'],
        }
        
        # Convert cancellation metrics to JSON-safe format
        cancel_metrics_safe = {
            'count': dashboard_data['cancellation_metrics']['count'],
            'rate': to_float(dashboard_data['cancellation_metrics']['rate']),
            'lost_revenue': to_float(dashboard_data['cancellation_metrics']['lost_revenue']),
            'lost_room_nights': dashboard_data['cancellation_metrics']['lost_room_nights'],
            'total_bookings': dashboard_data['cancellation_metrics']['total_bookings'],
            'avg_cancel_lead_time': dashboard_data['cancellation_metrics']['avg_cancel_lead_time'],
            'avg_days_before_arrival': dashboard_data['cancellation_metrics']['avg_days_before_arrival'],
        }
        
        return {
            # Monthly metrics
            'months': [m['month_name'] for m in monthly],
            'revenue': [float(m['revenue']) for m in monthly],
            'room_nights': [m['room_nights'] for m in monthly],
            'available': [m['available'] for m in monthly],
            'occupancy': [float(m['occupancy']) for m in monthly],
            'adr': [float(m['adr']) for m in monthly],
            'bookings': [m['bookings'] for m in monthly],
            
            # Cancellation metrics
            'cancelled_count': [m['cancelled_count'] for m in monthly_cancel],
            'lost_revenue': [float(m['lost_revenue']) for m in monthly_cancel],
            'lost_room_nights': [m['lost_room_nights'] for m in monthly_cancel],
            
            # Channel mix
            'channel_labels': [c['name'] for c in dashboard_data['channel_mix']],
            'channel_values': [float(c['revenue']) for c in dashboard_data['channel_mix']],
            'channel_percents': [float(c['percent']) for c in dashboard_data['channel_mix']],
            
            # Cancellation by channel
            'cancel_channel_labels': [c['name'] for c in dashboard_data['cancellation_by_channel']],
            'cancel_channel_counts': [c['cancelled_count'] for c in dashboard_data['cancellation_by_channel']],
            'cancel_channel_rates': [float(c['rate']) for c in dashboard_data['cancellation_by_channel']],
            
            # Meal plan mix
            'meal_plan_labels': [m['name'] for m in dashboard_data['meal_plan_mix']],
            'meal_plan_values': [float(m['revenue']) for m in dashboard_data['meal_plan_mix']],
            'meal_plan_percents': [float(m['percent']) for m in dashboard_data['meal_plan_mix']],
            
            # KPIs for display (JSON-safe)
            'kpis': kpis_safe,
            'cancellation_metrics': cancel_metrics_safe,
        }
    
    def get_net_pickup(self, start_date=None, end_date=None, days=30):
        """
        Calculate net pickup (new bookings - cancellations) for a period.
        
        Args:
            start_date: Start of period (default: days ago)
            end_date: End of period (default: today)
            days: Number of days to look back (default: 30)
        
        Returns:
            Dict with gross_bookings, cancellations, net_bookings, net_revenue
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=days)
        
        # Use property-filtered base queryset
        base_queryset = self._get_base_queryset()
        
        # New bookings created in this period
        new_bookings = base_queryset.filter(
            booking_date__gte=start_date,
            booking_date__lte=end_date
        ).exclude(status='cancelled')
        
        from django.db.models import Sum, Count
        
        new_stats = new_bookings.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        )
        
        # Cancellations in this period
        cancellations = base_queryset.filter(
            cancellation_date__gte=start_date,
            cancellation_date__lte=end_date,
            status='cancelled'
        )
        
        cancel_stats = cancellations.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
        )
        
        gross_bookings = new_stats['count'] or 0
        gross_revenue = new_stats['revenue'] or Decimal('0.00')
        gross_room_nights = new_stats['room_nights'] or 0
        
        cancelled_count = cancel_stats['count'] or 0
        cancelled_revenue = cancel_stats['revenue'] or Decimal('0.00')
        cancelled_room_nights = cancel_stats['room_nights'] or 0
        
        return {
            'period_start': start_date,
            'period_end': end_date,
            'gross_bookings': gross_bookings,
            'gross_revenue': gross_revenue,
            'gross_room_nights': gross_room_nights,
            'cancellations': cancelled_count,
            'cancelled_revenue': cancelled_revenue,
            'cancelled_room_nights': cancelled_room_nights,
            'net_bookings': gross_bookings - cancelled_count,
            'net_revenue': gross_revenue - cancelled_revenue,
            'net_room_nights': gross_room_nights - cancelled_room_nights,
        }
        
    def get_month_detail(self, year, month):
        """
        Get detailed analysis for a specific arrival month.
        
        Args:
            year: Arrival year
            month: Arrival month (1-12)
        
        Returns:
            Dict with summary, velocity, room_distribution, lead_time, 
            channel_distribution, country_distribution
        """
        from django.db.models import Sum, Count, Avg, F
        from django.db.models.functions import TruncMonth
        from pricing.models import Reservation

        # Base queryset for this arrival month
        base_qs = self._get_base_queryset().filter(
            arrival_date__year=year,
            arrival_date__month=month
        )

        # Active bookings only for summary
        active_qs = base_qs.filter(
            status__in=Reservation.ACTIVE_STATUSES
        )
        
        # Get room types for available calculation
        room_types = self._get_room_types()
        total_rooms = self.property.get_total_rooms() if self.property else (sum(rt.number_of_rooms for rt in room_types) or 1)
        days_in_month = calendar.monthrange(year, month)[1]
        available = total_rooms * days_in_month
        
        # ===================
        # SUMMARY
        # ===================
        summary_stats = active_qs.aggregate(
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            bookings=Count('id')
        )
        
        revenue = float(summary_stats['revenue'] or 0)
        room_nights = summary_stats['room_nights'] or 0
        adr = revenue / room_nights if room_nights > 0 else 0
        occupancy = (room_nights / available * 100) if available > 0 else 0
        
        summary = {
            'revenue': revenue,
            'room_nights': room_nights,
            'occupancy': occupancy,
            'adr': adr,
            'bookings': summary_stats['bookings'] or 0,
            'available': available,
        }
        
        # ===================
        # BOOKING VELOCITY
        # ===================
        velocity = self._get_velocity_for_month(base_qs, year, month)
        
        # ===================
        # ROOM DISTRIBUTION
        # ===================
        room_distribution = self._get_room_distribution_detail(active_qs)
        
        # ===================
        # LEAD TIME DISTRIBUTION
        # ===================
        lead_time = self._get_lead_time_distribution_detail(active_qs)
        
        # ===================
        # CHANNEL DISTRIBUTION
        # ===================
        channel_distribution = self._get_channel_distribution_detail(active_qs)
        
        # ===================
        # COUNTRY DISTRIBUTION (enriched with market data)
        # ===================
        country_distribution = self._get_country_distribution(active_qs)
        country_data = self._enrich_country_with_market_data(country_distribution, year, month)

        return {
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'summary': summary,
            'velocity': velocity,
            'room_distribution': room_distribution,
            'lead_time': lead_time,
            'channel_distribution': channel_distribution,
            'country_distribution': country_data,
        }

    def _get_velocity_for_month(self, base_qs, year, month):
        """
        Get booking velocity for a specific arrival month.
        
        IMPORTANT: This now calculates properly so cumulative matches final OTB:
        - New RN: Only counts ACTIVE bookings created in that month
        - Lost RN: Cancelled/Void/NoShow bookings created in that month
        - Net Pickup: New - Lost
        - Cumulative: Running total = Final Active OTB
        """
        from django.db.models import Sum, Count
        from django.db.models.functions import TruncMonth
        
        from pricing.models import Reservation
        active_statuses = Reservation.ACTIVE_STATUSES
        lost_statuses = Reservation.LOST_STATUSES
        
        # Get ACTIVE bookings grouped by booking month
        active_bookings = base_qs.filter(
            booking_date__isnull=False,
            status__in=active_statuses
        ).annotate(
            bm=TruncMonth('booking_date')
        ).values('bm').annotate(
            new_bookings=Count('id'),
            new_nights=Sum('nights'),
        ).order_by('bm')
        
        # Get LOST bookings (cancelled/void/no_show) grouped by booking month
        lost_bookings = base_qs.filter(
            booking_date__isnull=False,
            status__in=lost_statuses
        ).annotate(
            bm=TruncMonth('booking_date')
        ).values('bm').annotate(
            lost_bookings=Count('id'),
            lost_nights=Sum('nights'),
        ).order_by('bm')
        
        # Build lookups
        active_lookup = {a['bm']: a for a in active_bookings}
        lost_lookup = {l['bm']: l for l in lost_bookings}
        
        # Get all booking months
        all_months = sorted(set(
            list(active_lookup.keys()) + list(lost_lookup.keys())
        ))
        
        # Build velocity data
        velocity = []
        for bm in all_months:
            active_data = active_lookup.get(bm, {})
            lost_data = lost_lookup.get(bm, {})
            
            new_nights = active_data.get('new_nights', 0) or 0
            lost_nights = lost_data.get('lost_nights', 0) or 0
            
            velocity.append({
                'booking_month': bm.strftime('%b %Y') if bm else 'Unknown',
                'new_bookings': active_data.get('new_bookings', 0) or 0,
                'new_nights': new_nights,
                'cancellations': lost_data.get('lost_bookings', 0) or 0,
                'cancelled_nights': lost_nights,
                'net_pickup': new_nights - lost_nights,
            })
        
        return velocity

    def _get_room_distribution_detail(self, queryset):
        """Get room night distribution by room type for month detail."""
        from django.db.models import Sum, Count
        
        # Try room_type FK first
        by_fk = queryset.filter(
            room_type__isnull=False
        ).values(
            'room_type__name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        # Then try room_type_name
        by_name = queryset.filter(
            room_type__isnull=True
        ).values(
            'room_type_name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        distribution = []
        seen = set()
        
        for row in by_fk:
            name = row['room_type__name'] or 'Unknown'
            if name.lower() not in seen:
                seen.add(name.lower())
                distribution.append({
                    'room_type': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        for row in by_name:
            name = row['room_type_name'] or 'Unknown'
            if name and name.lower() not in seen:
                seen.add(name.lower())
                distribution.append({
                    'room_type': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        return distribution

    def _get_lead_time_distribution_detail(self, queryset):
        """Get lead time distribution (days between booking and arrival)."""
        from django.db.models import F
        
        # Get bookings with lead time calculated
        bookings_with_lead = queryset.filter(
            booking_date__isnull=False,
            arrival_date__isnull=False
        )
        
        # Define buckets
        buckets = [
            ('0-7 days', 0, 7),
            ('8-14 days', 8, 14),
            ('15-30 days', 15, 30),
            ('31-60 days', 31, 60),
            ('61-90 days', 61, 90),
            ('90+ days', 91, 9999),
        ]
        
        distribution = []
        
        for label, min_days, max_days in buckets:
            bucket_data = {
                'bookings': 0,
                'room_nights': 0,
                'revenue': Decimal('0.00'),
            }
            
            for booking in bookings_with_lead:
                if booking.booking_date and booking.arrival_date:
                    days = (booking.arrival_date - booking.booking_date).days
                    if min_days <= days <= max_days:
                        bucket_data['bookings'] += 1
                        bucket_data['room_nights'] += booking.nights or 0
                        bucket_data['revenue'] += booking.total_amount or Decimal('0.00')
            
            avg_adr = 0
            if bucket_data['room_nights'] > 0:
                avg_adr = float(bucket_data['revenue']) / bucket_data['room_nights']
            
            distribution.append({
                'bucket': label,
                'bookings': bucket_data['bookings'],
                'room_nights': bucket_data['room_nights'],
                'revenue': float(bucket_data['revenue']),
                'avg_adr': avg_adr,
            })
        
        return distribution

    def _get_channel_distribution_detail(self, queryset):
        """Get distribution by booking channel for month detail."""
        from django.db.models import Sum, Count
        
        # Try channel FK first
        by_channel = queryset.values(
            'channel__name'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id')
        ).order_by('-room_nights')
        
        distribution = []
        for row in by_channel:
            name = row['channel__name'] or 'Direct/Unknown'
            distribution.append({
                'channel': name,
                'room_nights': row['room_nights'] or 0,
                'revenue': float(row['revenue'] or 0),
                'bookings': row['bookings'] or 0,
            })
        
        # If no channel data, try booking_source
        if not distribution or all(d['channel'] == 'Direct/Unknown' for d in distribution):
            by_source = queryset.values(
                'booking_source__name'
            ).annotate(
                room_nights=Sum('nights'),
                revenue=Sum('total_amount'),
                bookings=Count('id')
            ).order_by('-room_nights')
            
            distribution = []
            for row in by_source:
                name = row['booking_source__name'] or 'Unknown'
                distribution.append({
                    'channel': name,
                    'room_nights': row['room_nights'] or 0,
                    'revenue': float(row['revenue'] or 0),
                    'bookings': row['bookings'] or 0,
                })
        
        return distribution

    def _get_country_distribution(self, queryset):
        """Get distribution by guest country with revenue, ADR, and rev_share."""
        from django.db.models import Sum, Count, Avg

        by_country = queryset.exclude(
            guest__country__isnull=True
        ).exclude(
            guest__country=''
        ).exclude(
            guest__country='-'
        ).values(
            'guest__country'
        ).annotate(
            room_nights=Sum('nights'),
            bookings=Count('id'),
            revenue=Sum('total_amount'),
        ).order_by('-room_nights')[:10]  # Top 10 countries

        # Compute total revenue across all returned countries for rev_share
        total_revenue = sum(
            float(row['revenue'] or 0) for row in by_country
        )

        distribution = []
        for row in by_country:
            country = row['guest__country'] or 'Unknown'
            rev = float(row['revenue'] or 0)
            rn = row['room_nights'] or 0
            adr = round(rev / rn, 2) if rn > 0 else 0
            rev_share = round(rev / total_revenue * 100, 1) if total_revenue > 0 else 0
            distribution.append({
                'country': country,
                'room_nights': rn,
                'bookings': row['bookings'] or 0,
                'revenue': round(rev, 2),
                'adr': adr,
                'rev_share': rev_share,
            })

        # If no guest country data, return placeholder
        if not distribution:
            distribution = [{'country': 'Unknown', 'room_nights': 0, 'bookings': 0,
                             'revenue': 0, 'adr': 0, 'rev_share': 0}]
        return distribution

    def _enrich_country_with_market_data(self, country_distribution, year, month):
        """
        Enrich property country distribution with national market context.

        For past months: uses actual MoT data.
        For future months: projects from historical data + YoY trend.

        Returns dict with 'countries', 'has_national', 'national_period', 'is_projected'.
        """
        try:
            from platform_data.models import MarketArrivalData
            from platform_data.services import _normalize_guest_country
            from django.db.models import Sum
        except ImportError:
            return {'countries': country_distribution, 'has_national': False, 'national_period': None, 'is_projected': False}

        target_period = date(year, month, 1)
        country_code = self.property.country_code if self.property else 'MV'

        # --- TIER 1: Exact match ---
        national_qs = MarketArrivalData.objects.filter(
            country_code=country_code,
            report_period=target_period
        )
        if national_qs.exists():
            return self._build_enriched_result(
                country_distribution, national_qs, target_period,
                label=target_period.strftime('%B %Y'),
                is_projected=False,
            )

        # --- TIER 2: Same month prior year + YoY trend ---
        prior_year_period = date(year - 1, month, 1)
        prior_qs = MarketArrivalData.objects.filter(
            country_code=country_code,
            report_period=prior_year_period
        )

        if prior_qs.exists():
            yoy_factor = self._get_latest_yoy_factor(country_code)

            projected = []
            for row in prior_qs.values('origin_country', 'arrivals', 'market_share_pct'):
                proj_arrivals = int(row['arrivals'] * yoy_factor)
                projected.append({
                    'origin_country': row['origin_country'],
                    'arrivals': proj_arrivals,
                    'market_share_pct': float(row['market_share_pct']) if row['market_share_pct'] else 0,
                })

            proj_total = sum(p['arrivals'] for p in projected)
            if proj_total > 0:
                for p in projected:
                    p['market_share_pct'] = round(p['arrivals'] / proj_total * 100, 1)

            yoy_pct = round((yoy_factor - 1) * 100, 1)
            sign = '+' if yoy_pct >= 0 else ''
            label = 'Projected from {} ({}{}% trend)'.format(
                prior_year_period.strftime('%b %Y'), sign, yoy_pct
            )

            return self._build_enriched_result_from_list(
                country_distribution, projected, target_period,
                label=label,
                is_projected=True,
            )

        # --- TIER 3: Latest available shares as proxy ---
        latest_record = MarketArrivalData.objects.filter(
            country_code=country_code
        ).order_by('-report_period').first()

        if not latest_record:
            return {'countries': country_distribution, 'has_national': False, 'national_period': None, 'is_projected': False}

        latest_period = latest_record.report_period
        latest_qs = MarketArrivalData.objects.filter(
            country_code=country_code,
            report_period=latest_period
        )

        label = 'Based on {} market shares'.format(latest_period.strftime('%b %Y'))

        return self._build_enriched_result(
            country_distribution, latest_qs, latest_period,
            label=label,
            is_projected=True,
        )

    def _get_latest_yoy_factor(self, country_code='MV'):
        """
        Calculate YoY growth factor from the most recent period pair.
        Returns float (e.g., 1.046 for +4.6% growth). Default 1.0.
        """
        from platform_data.models import MarketArrivalData
        from django.db.models import Sum

        periods = MarketArrivalData.objects.filter(
            country_code=country_code
        ).values_list(
            'report_period', flat=True
        ).distinct().order_by('-report_period')

        for period in periods[:12]:
            prior = date(period.year - 1, period.month, 1)

            current_total = MarketArrivalData.objects.filter(
                country_code=country_code, report_period=period
            ).aggregate(t=Sum('arrivals'))['t']

            prior_total = MarketArrivalData.objects.filter(
                country_code=country_code, report_period=prior
            ).aggregate(t=Sum('arrivals'))['t']

            if current_total and prior_total and prior_total > 0:
                factor = current_total / prior_total
                return max(0.75, min(1.25, factor))

        return 1.0

    def _build_enriched_result(self, country_distribution, national_qs, period, label, is_projected):
        """Build enriched result from a queryset of MarketArrivalData."""
        national_map = {}
        for row in national_qs.values('origin_country', 'arrivals', 'market_share_pct'):
            national_map[row['origin_country']] = {
                'arrivals': row['arrivals'],
                'share': float(row['market_share_pct']) if row['market_share_pct'] else 0,
            }

        return self._merge_property_and_national(
            country_distribution, national_map, label, is_projected
        )

    def _build_enriched_result_from_list(self, country_distribution, projected_list, period, label, is_projected):
        """Build enriched result from a projected list of dicts."""
        national_map = {}
        for row in projected_list:
            national_map[row['origin_country']] = {
                'arrivals': row['arrivals'],
                'share': row['market_share_pct'],
            }

        return self._merge_property_and_national(
            country_distribution, national_map, label, is_projected
        )

    def _merge_property_and_national(self, country_distribution, national_map, label, is_projected):
        """
        Core merge logic: match property countries to national data,
        calculate index, append gap markets.
        """
        from platform_data.services import _normalize_guest_country

        prop_total_nights = sum(c['room_nights'] for c in country_distribution)

        matched_national = set()
        for row in country_distribution:
            normalized = _normalize_guest_country(row['country'])
            nat = national_map.get(normalized)

            prop_share = round(row['room_nights'] / prop_total_nights * 100, 1) if prop_total_nights > 0 else 0

            if nat:
                matched_national.add(normalized)
                row['national_share'] = nat['share']
                row['index'] = round(prop_share / nat['share'], 1) if nat['share'] > 0 else None
            else:
                row['national_share'] = None
                row['index'] = None

            row['prop_share'] = prop_share

        # Append significant national markets missing from property data
        missing = []
        for country_name, nat in sorted(national_map.items(), key=lambda x: x[1]['share'], reverse=True):
            if country_name not in matched_national and len(missing) < 5:
                if nat['share'] >= 2.0:
                    missing.append({
                        'country': country_name,
                        'room_nights': 0,
                        'bookings': 0,
                        'revenue': 0,
                        'adr': 0,
                        'rev_share': 0,
                        'prop_share': 0.0,
                        'national_share': nat['share'],
                        'index': 0.0,
                        'is_gap': True,
                    })

        country_distribution.extend(missing)

        return {
            'countries': country_distribution,
            'has_national': True,
            'national_period': label,
            'is_projected': is_projected,
        }

    # =========================================================================
    # SOURCE MARKET TRENDS
    # =========================================================================

    def get_source_market_trends(self, year):
        """
        Build source-market summary and monthly trend data for the given year.

        Returns:
            {
              'summary': [
                {country, room_nights, revenue, adr, share, yoy_change},
                ...  (top 10 countries)
              ],
              'monthly': {
                'months': ['Jan', 'Feb', ...],
                'series': [
                  {country, data: [nights_jan, nights_feb, ...]},
                  ...  (top 5 countries)
                ]
              }
            }
        """
        from django.db.models import Sum, Count
        from pricing.models import Reservation

        base_qs = self._get_base_queryset().filter(
            arrival_date__year=year,
            status__in=Reservation.ACTIVE_STATUSES,
        )

        # ---------- Year-level summary by country ----------
        by_country = base_qs.exclude(
            guest__country__isnull=True
        ).exclude(
            guest__country=''
        ).exclude(
            guest__country='-'
        ).values(
            'guest__country'
        ).annotate(
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            bookings=Count('id'),
        ).order_by('-room_nights')[:10]

        total_nights = sum(r['room_nights'] or 0 for r in by_country)

        # Prior year totals for YoY
        prior_qs = self._get_base_queryset().filter(
            arrival_date__year=year - 1,
            status__in=Reservation.ACTIVE_STATUSES,
        ).exclude(
            guest__country__isnull=True
        ).exclude(guest__country='').exclude(guest__country='-')

        prior_by_country = {}
        for row in prior_qs.values('guest__country').annotate(rn=Sum('nights')):
            prior_by_country[row['guest__country']] = row['rn'] or 0

        summary = []
        for row in by_country:
            country = row['guest__country'] or 'Unknown'
            rn = row['room_nights'] or 0
            rev = float(row['revenue'] or 0)
            adr = round(rev / rn, 2) if rn > 0 else 0
            share = round(rn / total_nights * 100, 1) if total_nights > 0 else 0

            prior_rn = prior_by_country.get(country, 0)
            if prior_rn > 0:
                yoy_change = round((rn - prior_rn) / prior_rn * 100, 1)
            else:
                yoy_change = None

            summary.append({
                'country': country,
                'room_nights': rn,
                'revenue': round(rev, 2),
                'adr': adr,
                'share': share,
                'yoy_change': yoy_change,
            })

        # ---------- Monthly trend for top 5 ----------
        top5 = [s['country'] for s in summary[:5]]
        months_label = []
        series_map = {c: [] for c in top5}

        for m in range(1, 13):
            months_label.append(calendar.month_abbr[m])
            month_qs = base_qs.filter(
                arrival_date__month=m,
            ).exclude(
                guest__country__isnull=True
            ).exclude(guest__country='').exclude(guest__country='-')

            month_by_country = {}
            for row in month_qs.values('guest__country').annotate(rn=Sum('nights')):
                month_by_country[row['guest__country']] = row['rn'] or 0

            for c in top5:
                series_map[c].append(month_by_country.get(c, 0))

        series = [{'country': c, 'data': series_map[c]} for c in top5]

        return {
            'summary': summary,
            'monthly': {
                'months': months_label,
                'series': series,
            },
        }

    # -----------------------------------------------------------------
    # Booking Trends (last N days)
    # -----------------------------------------------------------------

    def get_booking_trends(self, days=30):
        """
        30-day booking trend analysis.

        All metrics based on booking_date window (when booked),
        with breakdowns by arrival month, source market, room type, channel.
        Includes STLY comparison and national market context.

        Returns:
            dict with kpis, daily_pace, arrival_mix, country_mix,
            room_mix, channel_mix, booking_log, stly_comparison
        """
        from django.db.models import Sum, Count, Avg, F, Q
        from django.db.models.functions import TruncMonth
        from platform_data.utils import normalize_country
        from pricing.models import Reservation

        today = date.today()
        window_start = today - timedelta(days=days)

        prop = self.property

        # ── Core queryset: bookings CREATED in window ──
        recent = Reservation.objects.filter(
            hotel=prop,
            booking_date__gte=window_start,
            booking_date__lte=today,
            status__in=Reservation.ACTIVE_STATUSES,
        )

        # ── STLY queryset ──
        stly_start = date(window_start.year - 1, window_start.month, window_start.day)
        stly_end = date(today.year - 1, today.month, today.day)
        stly = Reservation.objects.filter(
            hotel=prop,
            booking_date__gte=stly_start,
            booking_date__lte=stly_end,
            status__in=Reservation.ACTIVE_STATUSES,
        )

        # ── Cancellations in same window ──
        cancellations = Reservation.objects.filter(
            hotel=prop,
            cancellation_date__gte=window_start,
            cancellation_date__lte=today,
            status='cancelled',
        )
        cancel_stats = cancellations.aggregate(
            count=Count('id'),
            nights=Sum('nights'),
            revenue=Sum('total_amount'),
        )

        # ═══════════════════════════════════════════
        # 1. KPI CARDS
        # ═══════════════════════════════════════════
        current_stats = recent.aggregate(
            bookings=Count('id'),
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            avg_adr=Avg('adr'),
            avg_lead_time=Avg('lead_time_days'),
        )

        stly_stats = stly.aggregate(
            bookings=Count('id'),
            room_nights=Sum('nights'),
            revenue=Sum('total_amount'),
            avg_adr=Avg('adr'),
        )

        def yoy_pct(current_val, stly_val):
            if stly_val and stly_val > 0:
                return round((current_val - stly_val) / stly_val * 100, 1)
            return None

        c = current_stats
        s = stly_stats
        kpis = {
            'bookings': c['bookings'] or 0,
            'room_nights': c['room_nights'] or 0,
            'revenue': float(c['revenue'] or 0),
            'avg_adr': float(c['avg_adr'] or 0),
            'avg_lead_time': round(c['avg_lead_time'] or 0, 0),
            'cancellations': cancel_stats['count'] or 0,
            'cancelled_nights': cancel_stats['nights'] or 0,
            'net_bookings': (c['bookings'] or 0) - (cancel_stats['count'] or 0),
            'net_room_nights': (c['room_nights'] or 0) - (cancel_stats['nights'] or 0),
            # STLY
            'stly_bookings': s['bookings'] or 0,
            'stly_room_nights': s['room_nights'] or 0,
            'stly_revenue': float(s['revenue'] or 0),
            'stly_avg_adr': float(s['avg_adr'] or 0),
            # YoY
            'yoy_bookings': yoy_pct(c['bookings'] or 0, s['bookings']),
            'yoy_room_nights': yoy_pct(c['room_nights'] or 0, s['room_nights']),
            'yoy_revenue': yoy_pct(float(c['revenue'] or 0), float(s['revenue'] or 0)),
            'yoy_adr': yoy_pct(float(c['avg_adr'] or 0), float(s['avg_adr'] or 0)),
        }

        # ═══════════════════════════════════════════
        # 2. DAILY BOOKING PACE (line chart)
        # ═══════════════════════════════════════════
        daily_current = dict(
            recent.values('booking_date')
            .annotate(
                count=Count('id'),
                nights=Sum('nights'),
                revenue=Sum('total_amount'),
            )
            .values_list('booking_date', 'count')
        )

        daily_stly_raw = dict(
            stly.values('booking_date')
            .annotate(count=Count('id'))
            .values_list('booking_date', 'count')
        )

        # Build aligned arrays: day 1..N
        daily_pace = {
            'labels': [],
            'current': [],
            'stly': [],
            'cum_current': [],
            'cum_stly': [],
        }
        cum_c = 0
        cum_s = 0
        for i in range(days):
            d = window_start + timedelta(days=i)
            d_stly = date(d.year - 1, d.month, d.day)

            c_val = daily_current.get(d, 0)
            s_val = daily_stly_raw.get(d_stly, 0)
            cum_c += c_val
            cum_s += s_val

            daily_pace['labels'].append(d.strftime('%b %d'))
            daily_pace['current'].append(c_val)
            daily_pace['stly'].append(s_val)
            daily_pace['cum_current'].append(cum_c)
            daily_pace['cum_stly'].append(cum_s)

        # ═══════════════════════════════════════════
        # 3. ARRIVAL MONTH MIX (horizontal bar)
        # ═══════════════════════════════════════════
        arrival_by_month = (
            recent.annotate(arr_month=TruncMonth('arrival_date'))
            .values('arr_month')
            .annotate(
                bookings=Count('id'),
                nights=Sum('nights'),
                revenue=Sum('total_amount'),
            )
            .order_by('arr_month')
        )

        # STLY arrival month mix for comparison
        stly_arrival_by_month = dict(
            stly.annotate(arr_month=TruncMonth('arrival_date'))
            .values('arr_month')
            .annotate(nights=Sum('nights'))
            .values_list('arr_month', 'nights')
        )

        total_nights = sum(r['nights'] or 0 for r in arrival_by_month)
        arrival_mix = []
        for row in arrival_by_month:
            nights = row['nights'] or 0
            month_dt = row['arr_month']
            # STLY: same month but one year prior
            stly_month = month_dt.replace(year=month_dt.year - 1)
            stly_nights = stly_arrival_by_month.get(stly_month, 0)

            arrival_mix.append({
                'month': month_dt.strftime('%Y-%m-%d'),
                'month_label': month_dt.strftime('%b %Y'),
                'month_short': month_dt.strftime('%b'),
                'bookings': row['bookings'] or 0,
                'nights': nights,
                'revenue': float(row['revenue'] or 0),
                'share': round(nights / total_nights * 100, 1) if total_nights > 0 else 0,
                'stly_nights': stly_nights or 0,
                'yoy_nights': yoy_pct(nights, stly_nights) if stly_nights else None,
            })

        # ═══════════════════════════════════════════
        # 4. SOURCE MARKET MIX (table + chart)
        # ═══════════════════════════════════════════
        country_raw = (
            recent.filter(
                guest__country__isnull=False,
            ).exclude(
                guest__country__in=['', '-'],
            ).values(
                'guest__country',
            ).annotate(
                bookings=Count('id'),
                nights=Sum('nights'),
                revenue=Sum('total_amount'),
                avg_adr=Avg('adr'),
            ).order_by('-nights')
        )

        # STLY country mix
        stly_country = dict(
            stly.filter(
                guest__country__isnull=False,
            ).exclude(
                guest__country__in=['', '-'],
            ).values(
                'guest__country',
            ).annotate(nights=Sum('nights'))
            .values_list('guest__country', 'nights')
        )
        stly_total_nights = sum(stly_country.values()) if stly_country else 0

        # National market shares (latest MoT period, weighted toward arrival months)
        national_shares = self._get_national_shares_for_comparison(
            prop, arrival_mix
        )

        country_mix = []
        for row in country_raw[:12]:  # Top 12 markets
            raw_name = row['guest__country']
            normalized = normalize_country(raw_name)
            nights = row['nights'] or 0
            share = round(nights / total_nights * 100, 1) if total_nights > 0 else 0

            # STLY comparison for this country
            s_nights = stly_country.get(raw_name, 0)
            s_share = round(s_nights / stly_total_nights * 100, 1) if stly_total_nights > 0 else 0

            # National share from MoT
            nat = national_shares.get(normalized, {})
            nat_share = nat.get('share', None)

            # Penetration index: property share / national share
            index = None
            if nat_share and nat_share > 0 and share > 0:
                index = round(share / nat_share, 2)

            country_mix.append({
                'country': normalized,
                'bookings': row['bookings'] or 0,
                'nights': nights,
                'revenue': float(row['revenue'] or 0),
                'adr': float(row['avg_adr'] or 0),
                'share': share,
                'stly_nights': s_nights,
                'stly_share': s_share,
                'yoy_nights': yoy_pct(nights, s_nights) if s_nights else None,
                'national_share': nat_share,
                'national_yoy': nat.get('yoy', None),
                'index': index,
            })

        # Gap markets: significant national share but zero property bookings
        gap_markets = []
        booked_countries = {c['country'] for c in country_mix}
        for country, nat in national_shares.items():
            if country not in booked_countries and nat.get('share', 0) >= 2.0:
                gap_markets.append({
                    'country': country,
                    'national_share': nat['share'],
                    'national_yoy': nat.get('yoy'),
                    'note': 'No bookings in last 30 days',
                })
        gap_markets.sort(key=lambda x: -(x['national_share'] or 0))

        # ═══════════════════════════════════════════
        # 5. ROOM TYPE MIX
        # ═══════════════════════════════════════════
        room_raw = (
            recent.values('room_type__name')
            .annotate(
                bookings=Count('id'),
                nights=Sum('nights'),
                revenue=Sum('total_amount'),
                avg_adr=Avg('adr'),
            )
            .order_by('-nights')
        )

        stly_room = dict(
            stly.values('room_type__name')
            .annotate(nights=Sum('nights'))
            .values_list('room_type__name', 'nights')
        )

        room_mix = []
        for row in room_raw:
            name = row['room_type__name'] or 'Unassigned'
            nights = row['nights'] or 0
            s_nights = stly_room.get(name, 0)
            room_mix.append({
                'room_type': name,
                'bookings': row['bookings'] or 0,
                'nights': nights,
                'revenue': float(row['revenue'] or 0),
                'adr': float(row['avg_adr'] or 0),
                'share': round(nights / total_nights * 100, 1) if total_nights > 0 else 0,
                'stly_nights': s_nights or 0,
                'yoy_nights': yoy_pct(nights, s_nights) if s_nights else None,
            })

        # ═══════════════════════════════════════════
        # 6. CHANNEL MIX
        # ═══════════════════════════════════════════
        channel_raw = (
            recent.values('channel__name')
            .annotate(
                bookings=Count('id'),
                nights=Sum('nights'),
                revenue=Sum('total_amount'),
            )
            .order_by('-nights')
        )

        stly_channel = dict(
            stly.values('channel__name')
            .annotate(nights=Sum('nights'))
            .values_list('channel__name', 'nights')
        )

        channel_mix = []
        for row in channel_raw:
            name = row['channel__name'] or 'Unknown'
            nights = row['nights'] or 0
            s_nights = stly_channel.get(name, 0)
            channel_mix.append({
                'channel': name,
                'bookings': row['bookings'] or 0,
                'nights': nights,
                'revenue': float(row['revenue'] or 0),
                'share': round(nights / total_nights * 100, 1) if total_nights > 0 else 0,
                'stly_nights': s_nights or 0,
                'yoy_nights': yoy_pct(nights, s_nights) if s_nights else None,
            })

        # ═══════════════════════════════════════════
        # 7. BOOKING LOG (last 30 entries)
        # ═══════════════════════════════════════════
        booking_log = list(
            recent.select_related('guest', 'room_type', 'channel')
            .order_by('-booking_date', '-created_at')[:30]
            .values(
                'booking_date', 'confirmation_no',
                'guest__name', 'guest__country',
                'arrival_date', 'departure_date', 'nights',
                'room_type__name', 'channel__name',
                'total_amount', 'adr', 'status',
            )
        )

        # Serialize dates
        for b in booking_log:
            b['booking_date'] = b['booking_date'].isoformat() if b['booking_date'] else ''
            b['arrival_date'] = b['arrival_date'].isoformat() if b['arrival_date'] else ''
            b['departure_date'] = b['departure_date'].isoformat() if b['departure_date'] else ''
            b['total_amount'] = float(b['total_amount'] or 0)
            b['adr'] = float(b['adr'] or 0)

        return {
            'period_start': window_start.isoformat(),
            'period_end': today.isoformat(),
            'days': days,
            'kpis': kpis,
            'daily_pace': daily_pace,
            'arrival_mix': arrival_mix,
            'country_mix': country_mix,
            'gap_markets': gap_markets,
            'room_mix': room_mix,
            'channel_mix': channel_mix,
            'booking_log': booking_log,
            'has_national_data': bool(national_shares),
        }

    def _get_national_shares_for_comparison(self, prop, arrival_mix):
        """
        Get national market shares weighted by which arrival months
        recent bookings target.

        If 60% of 30-day bookings arrive in March and 40% in April,
        weight March MoT shares 60% and April shares 40%.

        Returns:
            dict: {country_name: {share: float, yoy: float}}
            share is percentage (e.g., 8.2 = 8.2%)
        """
        from platform_data.models import MarketArrivalData

        country_code = getattr(prop, 'country_code', 'MV') or 'MV'

        if not arrival_mix:
            return {}

        # Calculate weights by arrival month
        total_nights = sum(m['nights'] for m in arrival_mix)
        if total_nights == 0:
            return {}

        month_weights = {}
        for m in arrival_mix:
            month_dt = date.fromisoformat(m['month'])
            weight = m['nights'] / total_nights
            month_weights[(month_dt.year, month_dt.month)] = weight

        # For each weighted month, get MoT country shares
        blended = {}  # country -> {weighted_share, weighted_yoy, weight_sum}

        for (year, month), weight in month_weights.items():
            period = date(year, month, 1)

            # Try exact period first, then same month last year
            mot_data = list(MarketArrivalData.objects.filter(
                country_code=country_code,
                report_period=period,
            ).values('origin_country', 'market_share_pct', 'yoy_change_pct'))

            if not mot_data:
                # Fallback: same month last year
                mot_data = list(MarketArrivalData.objects.filter(
                    country_code=country_code,
                    report_period=date(year - 1, month, 1),
                ).values('origin_country', 'market_share_pct', 'yoy_change_pct'))

            if not mot_data:
                # Fallback: latest available period
                latest_period = MarketArrivalData.objects.filter(
                    country_code=country_code,
                ).order_by('-report_period').values_list(
                    'report_period', flat=True,
                ).first()

                if latest_period:
                    mot_data = list(MarketArrivalData.objects.filter(
                        country_code=country_code,
                        report_period=latest_period,
                    ).values('origin_country', 'market_share_pct', 'yoy_change_pct'))

            for row in mot_data:
                country = row['origin_country']
                share = float(row['market_share_pct'] or 0)
                yoy = float(row['yoy_change_pct']) if row['yoy_change_pct'] is not None else None

                if country not in blended:
                    blended[country] = {
                        'weighted_share': 0,
                        'weighted_yoy': 0,
                        'yoy_weight': 0,
                    }

                blended[country]['weighted_share'] += share * weight
                if yoy is not None:
                    blended[country]['weighted_yoy'] += yoy * weight
                    blended[country]['yoy_weight'] += weight

        # Finalize
        result = {}
        for country, data in blended.items():
            result[country] = {
                'share': round(data['weighted_share'], 1),
                'yoy': round(data['weighted_yoy'] / data['yoy_weight'], 1) if data['yoy_weight'] > 0 else None,
            }

        return result


# =============================================================================
# IMPORT TEMPLATE SERVICE
# =============================================================================

class ImportTemplateService:
    """
    Manages the template-based import workflow:
    
    1. read_headers(file_path) → Read CSV/Excel headers + preview rows
    2. detect_template(headers, hotel) → Match against saved templates
    3. auto_map(headers) → Use DEFAULT_COLUMN_MAPPING as hints for unmapped columns
    4. execute_import(file_path, column_map, hotel, template) → Run import with explicit mapping
    
    The column_map dict format: {system_field: csv_header}
    e.g., {"confirmation_no": "Res #", "arrival_date": "Arr"}
    """
    
    # System fields grouped by importance and type
    RESERVATION_FIELDS = {
        'required': [
            {'field': 'confirmation_no', 'label': 'Confirmation No', 'type': 'text'},
            {'field': 'arrival_date', 'label': 'Arrival Date', 'type': 'date'},
            {'field': 'departure_date', 'label': 'Departure Date', 'type': 'date'},
        ],
        'recommended': [
            {'field': 'booking_date', 'label': 'Booking Date', 'type': 'date'},
            {'field': 'nights', 'label': 'Nights', 'type': 'number'},
            {'field': 'total_amount', 'label': 'Total Amount', 'type': 'currency'},
            {'field': 'adr', 'label': 'ADR / Daily Rate', 'type': 'currency'},
            {'field': 'status', 'label': 'Status', 'type': 'text'},
            {'field': 'room_no', 'label': 'Room Type', 'type': 'text'},
            {'field': 'source', 'label': 'Booking Source / Channel', 'type': 'text'},
        ],
        'optional': [
            {'field': 'guest_name', 'label': 'Guest Name', 'type': 'text'},
            {'field': 'country', 'label': 'Country', 'type': 'text'},
            {'field': 'adults', 'label': 'Adults', 'type': 'number'},
            {'field': 'children', 'label': 'Children', 'type': 'number'},
            {'field': 'rate_plan', 'label': 'Rate Plan', 'type': 'text'},
            {'field': 'email', 'label': 'Email', 'type': 'text'},
            {'field': 'cancellation_date', 'label': 'Cancellation Date', 'type': 'date'},
            {'field': 'reservation_type', 'label': 'Reservation Type', 'type': 'text'},
            {'field': 'market_code', 'label': 'Market Segment', 'type': 'text'},
            {'field': 'payment_type', 'label': 'Payment Type', 'type': 'text'},
            {'field': 'user', 'label': 'User / Agent', 'type': 'text'},
            {'field': 'pax', 'label': 'Pax', 'type': 'number'},
            {'field': 'rooms_count', 'label': 'Rooms Count', 'type': 'number'},
            {'field': 'deposit', 'label': 'Deposit', 'type': 'currency'},
            {'field': 'total_charges', 'label': 'Total Charges', 'type': 'currency'},
            {'field': 'hotel_name', 'label': 'Hotel Name', 'type': 'text'},
            {'field': 'promotion', 'label': 'Promotion', 'type': 'text'},
        ],
    }
    
    # Maps import_type to its field definitions
    FIELD_DEFINITIONS = {
        'reservation': RESERVATION_FIELDS,
        # Future: arrival_report, review, competitor_rates
    }
    
    def __init__(self, hotel=None):
        self.hotel = hotel
    
    def read_headers(self, file_path, max_preview_rows=5):
        """
        Read headers and preview rows from a CSV/Excel file.
        
        Returns:
            {
                'headers': ['Col A', 'Col B', ...],
                'preview': [[row1_val1, row1_val2], ...],
                'row_count': 150,
                'file_type': 'csv',
                'skip_rows': 0,
            }
        """
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()
        skip_rows = 0
        
        # Header row detection (SynXis Activity Report or IDS preamble)
        if suffix == '.csv':
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    first_lines = [f.readline() for _ in range(20)]
                if 'Reservation Activity Report' in first_lines[0]:
                    skip_rows = 3
                else:
                    header_markers = ['Confirm #', 'Confirm#', 'Res #', 'Res#', 'Reservation',
                                      'confirmation_no', 'FXRes#', 'BookingSr.No']
                    for i, line in enumerate(first_lines):
                        if any(marker in line for marker in header_markers):
                            if i > 0:
                                skip_rows = i
                            break
                    else:
                        for i, line in enumerate(first_lines):
                            if line.strip().replace(',', ''):
                                if i > 0:
                                    skip_rows = i
                                break
            except Exception:
                pass
        
        try:
            if suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path, skiprows=skip_rows, nrows=max_preview_rows + 1)
            else:
                df = None
                for encoding in ['utf-8', 'latin1', 'cp1252']:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding, index_col=False,
                                         skiprows=skip_rows, nrows=max_preview_rows + 1)
                        break
                    except UnicodeDecodeError:
                        continue
                if df is None:
                    df = pd.read_csv(file_path, encoding='utf-8', encoding_errors='replace',
                                     index_col=False, skiprows=skip_rows, nrows=max_preview_rows + 1)
            
            # Normalize headers — strip newlines, extra spaces (fixes IDS "Arrive\nDate")
            headers = [
                re.sub(r'\s+', ' ', str(c).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')).strip()
                for c in df.columns.tolist()
            ]
            df.columns = headers

            # Preview rows as lists of strings
            preview = []
            for _, row in df.head(max_preview_rows).iterrows():
                preview.append([str(v) if pd.notna(v) else '' for v in row.tolist()])
            
            # Get total row count (read minimal data for large files)
            if suffix in ['.xlsx', '.xls']:
                full_df = pd.read_excel(file_path, skiprows=skip_rows, usecols=[0])
            else:
                full_df = pd.read_csv(file_path, encoding='utf-8', encoding_errors='replace',
                                       index_col=False, skiprows=skip_rows, usecols=[0])
            row_count = len(full_df)
            
            return {
                'headers': headers,
                'preview': preview,
                'row_count': row_count,
                'file_type': suffix.lstrip('.'),
                'skip_rows': skip_rows,
            }
        except Exception as e:
            return {'error': str(e)}
    
    def detect_template(self, headers, hotel=None, import_type='reservation'):
        """
        Find the best matching saved template for these CSV headers.
        
        Search order:
        1. Property-specific templates
        2. Organization-level templates
        3. Any active template matching these headers
        
        Returns:
            {'template': {...}, 'score': 0.95} or None
        """
        from pricing.models import ImportTemplate
        
        hotel = hotel or self.hotel
        
        candidates = []
        
        # Property-specific
        if hotel:
            for t in ImportTemplate.objects.filter(
                hotel=hotel, import_type=import_type, is_active=True
            ):
                score = t.matches_headers(headers)
                if score >= 0.7:
                    candidates.append((t, score))
            
            # Organization-level
            if hotel.organization:
                for t in ImportTemplate.objects.filter(
                    organization=hotel.organization, hotel__isnull=True,
                    import_type=import_type, is_active=True
                ):
                    score = t.matches_headers(headers)
                    if score >= 0.7:
                        candidates.append((t, score))
        
        if not candidates:
            return None
        
        # Best match
        candidates.sort(key=lambda x: (-x[1], -x[0].use_count))
        best_template, best_score = candidates[0]
        
        return {
            'template': {
                'id': best_template.id,
                'name': best_template.name,
                'import_type': best_template.import_type,
                'column_map': best_template.column_map,
                'value_transforms': best_template.value_transforms,
                'settings': best_template.settings,
                'use_count': best_template.use_count,
                'last_used_at': best_template.last_used_at.isoformat() if best_template.last_used_at else None,
            },
            'score': round(best_score, 2),
        }
    
    def auto_map(self, headers, import_type='reservation'):
        """
        Auto-detect column mapping using DEFAULT_COLUMN_MAPPING from ReservationImportService.
        
        Returns:
            {system_field: csv_header} for each detected match, plus unmatched headers
        """
        detected = {}
        unmatched = list(headers)
        
        # Use the existing auto-detect logic
        mapping_source = ReservationImportService.DEFAULT_COLUMN_MAPPING
        
        for system_field, possible_names in mapping_source.items():
            possible_lower = [n.lower() for n in possible_names]
            for header in headers:
                if header.strip().lower() in possible_lower:
                    detected[system_field] = header
                    if header in unmatched:
                        unmatched.remove(header)
                    break
        
        return {
            'detected': detected,
            'unmatched': unmatched,
        }
    
    def get_field_definitions(self, import_type='reservation'):
        """Return field definitions for the mapping UI."""
        return self.FIELD_DEFINITIONS.get(import_type, self.RESERVATION_FIELDS)
    
    def execute_import(self, file_path, column_map, hotel=None, template=None,
                        value_transforms=None, import_type='reservation', settings=None):
        """
        Run import using an explicit column mapping.
        
        This wraps ReservationImportService with the template-provided mapping
        instead of relying on auto-detect.
        
        Args:
            file_path: Path to the file
            column_map: {system_field: csv_header} mapping
            hotel: Property to import to
            template: ImportTemplate instance (optional, for tracking)
            value_transforms: {field: {source_val: target_val}} (optional)
            import_type: Type of import
            settings: Additional settings (header_row, date_format, etc.)
        
        Returns:
            Dict with import results
        """
        from pricing.models import FileImport, ImportTemplate as TemplateModel
        
        hotel = hotel or self.hotel
        file_path = Path(file_path)
        settings = settings or {}
        
        # Invert the column_map for the existing service:
        # ReservationImportService expects {system_field: [possible_csv_names]}
        # We give it {system_field: [exact_csv_header]}
        inverted_mapping = {}
        for system_field, csv_header in column_map.items():
            if csv_header:  # Skip unmapped fields
                inverted_mapping[system_field] = [csv_header]
        
        # Create FileImport record
        file_import = FileImport.objects.create(
            hotel=hotel,
            template=template,
            filename=file_path.name,
            import_type=import_type,
            column_map_used=column_map,
            status='pending',
        )
        
        # Track template usage
        if template:
            template.record_usage()
        
        if import_type == 'reservation':
            service = ReservationImportService(
                column_mapping=inverted_mapping,
                hotel=hotel,
            )
            
            # If value_transforms provided, inject them
            if value_transforms:
                service._value_transforms = value_transforms
            
            result = service.import_file(str(file_path), file_import=file_import, hotel=hotel)
            return result
        else:
            # Future: dispatch to other processors
            file_import.status = 'failed'
            file_import.errors = [{'row': 0, 'message': f'Import type "{import_type}" not yet implemented'}]
            file_import.save()
            return {
                'success': False,
                'file_import_id': file_import.id,
                'status': 'failed',
                'error': f'Import type "{import_type}" not yet implemented',
            }
