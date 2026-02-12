"""
Analytics services: ReservationImportService, BookingAnalysisService.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from collections import defaultdict
import calendar
import re
import csv
import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from django.db.models import Sum, Count, Avg, Min, Max, Q, F

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
        ],
        
        'booking_time': [
            'Booking Time', 'Time', 'Created Time',
        ],
        
        'arrival_date': [
            # SynXis Activity Report
            'ArrivalDate/Time',
            # Standard formats
            'Arrival', 'Arr', 'Check In', 'CheckIn', 'Arrival Date', 'Check-In',
        ],
        
        'departure_date': [
            # SynXis Activity Report
            'DepartureDate/Time',
            # Standard formats
            'Dept', 'Departure', 'Check Out', 'CheckOut', 'Departure Date', 'Check-Out',
        ],
        
        'cancellation_date': [
            'Cancellation Date', 'Cancelled Date', 'Cancel Date',
        ],
        
        # =========================================================================
        # NIGHTS / PAX
        # =========================================================================
        'nights': [
            # SynXis Activity Report
            'Room Nights',
            # Standard formats
            'No Of Nights', 'Nights', 'Night', 'LOS', 'Length of Stay',
            'NoOfNights', 'Number of Nights',
        ],
        
        'pax': ['Pax', 'Guests', 'Occupancy'],
        'adults': [
            # SynXis Activity Report
            'Adult',
            # Standard formats
            'Adults', 'No of Adults',
        ],
        'children': [
            # SynXis Activity Report
            'Child',
            # Standard formats
            'Children', 'Kids', 'No of Children',
        ],
        
        # =========================================================================
        # ROOM TYPE
        # =========================================================================
        'room_no': [
            # SynXis Activity Report
            'Room Type',
            # Standard formats
            'Room', 'Room No', 'Room Number', 'RoomNo', 'RoomType', 'Room Name',
        ],
        
        # =========================================================================
        # SOURCE / CHANNEL
        # =========================================================================
        'source': [
            # SynXis Activity Report
            'CompanyName/TravelAgent',
            # Standard formats
            'Source', 'Business Source', 'Channel', 'Booking Source', 'channel',
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
        ],
        
        # =========================================================================
        # AMOUNTS
        # =========================================================================
        'total_amount': [
            # SynXis Activity Report
            'TotalRoomRate',
            # Standard formats
            'Total', 'Grand Total', 'Total Amount',
            'Revenue($)', 'Balance Due($)', 'Revenue', 'Amount', 'Net Amount',
        ],
        
        'adr': [
            # SynXis Activity Report
            'AvgRoomRate',
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
            # Standard formats
            'Name', 'Guest', 'Customer', 'Customer Name',
        ],
        
        'country': [
            # SynXis Activity Report
            'Nationality',
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
                df['_conf_str'] = df['confirmation_no'].astype(str)
                df = df[df['_conf_str'].str.match(r'^\d+$', na=False)]
                df = df.drop(columns=['_conf_str'])
                
                invalid_filtered = initial_count - len(df)
                if invalid_filtered > 0:
                    self.errors.append({
                        'row': 0,
                        'message': f'Filtered out {invalid_filtered} invalid/footer rows'
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
                # Read first line to check for SynXis header
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        first_line = f.readline()
                    
                    if 'Reservation Activity Report' in first_line or first_line.startswith(',,'):
                        skiprows = 3
                        self._is_synxis_activity = True
                        self.errors.append({
                            'row': 0,
                            'message': 'Detected SynXis Activity Report format - skipped 3 header rows'
                        })
                except:
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
                        errors='replace', 
                        index_col=False,
                        skiprows=skiprows
                    )
            else:
                self.errors.append({
                    'row': 0,
                    'message': f'Unsupported file format: {suffix}'
                })
                return None
            
            # Detect SynXis format by columns
            if df is not None and ('FXRes#' in df.columns or 'Type' in df.columns):
                self._is_synxis_activity = True
            
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
        source_str = str(row.get('source', '')).strip()
        
        if not source_str or source_str == 'nan' or source_str.upper() == 'PMS':
            source_str = 'Direct'
        
        # Map to channel
        channel = self._map_channel(source_str)
        
        # Get or create booking source
        booking_source = BookingSource.find_source(
            source_str,
            str(row.get('user', ''))
        )
        
        if not booking_source:
            booking_source = BookingSource.get_or_create_unknown()
        
        # Update channel on booking source if we mapped one
        if channel and booking_source and not booking_source.channel:
            booking_source.channel = channel
            booking_source.save(update_fields=['channel'])
        
        # =====================================================================
        # GUEST
        # =====================================================================
        guest_name = str(row.get('guest_name', '')).strip()
        country = str(row.get('country', '')).strip()
        email = str(row.get('email', '')).strip()
        
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
            
            defaults = {
                'original_confirmation_no': raw_conf,
                'booking_date': booking_date or arrival_date,
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
                'is_multi_room': is_multi_room,
                'file_import': file_import,
                'raw_data': raw_data,
            }
            
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

        # 5. Fallback: No structured match found
        return None, room_type_name
    
    def _map_channel(self, source_str: str) -> Optional[Any]:
        """Map source string to Channel object."""
        from pricing.models import Channel
        
        if not source_str or source_str == 'nan':
            return None
        
        source_lower = source_str.strip().lower()
        
        # Check mapping
        channel_name = None
        for key, name in self.CHANNEL_MAPPING.items():
            if key and key in source_lower:
                channel_name = name
                break
        
        if not channel_name:
            # Try to determine from content
            if 'booking.com' in source_lower:
                channel_name = 'Booking.com'
            elif 'agoda' in source_lower:
                channel_name = 'Agoda'
            elif 'expedia' in source_lower:
                channel_name = 'Expedia'
            elif 'trip.com' in source_lower:
                channel_name = 'Trip.com'
        
        if channel_name:
            return Channel.objects.filter(name__iexact=channel_name).first()
        
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
    
    def _build_result(self, file_import) -> Dict:
        """Build result dictionary from file import."""
        return {
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
        # Default to current year
        if year is None and start_date is None:
            year = date.today().year
        
        # Build base querysets with property filtering
        base_queryset = self._get_base_queryset()
        
        # ACTIVE bookings (exclude cancelled)
        active_queryset = base_queryset.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
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
        total_rooms = sum(rt.number_of_rooms for rt in room_types) or 20
        
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
        Calculate KPI card values.
        
        Returns:
            Dict with total_revenue, room_nights, avg_adr, avg_occupancy, reservations
        """
        from django.db.models import Sum, Count
        
        # Aggregate basic stats
        stats = queryset.aggregate(
            total_revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            reservation_count=Count('id'),
        )
        
        total_revenue = stats['total_revenue'] or Decimal('0.00')
        room_nights = stats['room_nights'] or 0
        reservation_count = stats['reservation_count'] or 0
        
        # Calculate ADR
        avg_adr = Decimal('0.00')
        if room_nights > 0:
            avg_adr = (total_revenue / room_nights).quantize(Decimal('0.01'))
        
        # Calculate average occupancy for the year
        if year:
            # Total available room nights for the year
            days_in_year = 366 if calendar.isleap(year) else 365
            total_available = total_rooms * days_in_year
            avg_occupancy = Decimal('0.00')
            if total_available > 0:
                avg_occupancy = (
                    Decimal(str(room_nights)) / Decimal(str(total_available)) * 100
                ).quantize(Decimal('0.1'))
        else:
            avg_occupancy = Decimal('0.0')
        
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
        Calculate monthly breakdown.
        
        Returns:
            List of dicts with month, revenue, room_nights, available, occupancy, adr
        """
        from django.db.models import Sum, Count
        
        monthly_data = []
        
        # Initialize all 12 months
        for month_num in range(1, 13):
            if year:
                # Calculate available room nights for this month
                days_in_month = calendar.monthrange(year, month_num)[1]
                available = total_rooms * days_in_month
            else:
                available = 0
            
            monthly_data.append({
                'month': month_num,
                'month_name': calendar.month_abbr[month_num],
                'month_full': calendar.month_name[month_num],
                'revenue': Decimal('0.00'),
                'room_nights': 0,
                'available': available,
                'occupancy': Decimal('0.0'),
                'adr': Decimal('0.00'),
                'bookings': 0,
            })
        
        # Aggregate by arrival month
        monthly_stats = queryset.values('arrival_date__month').annotate(
            revenue=Sum('total_amount'),
            room_nights=Sum('nights'),
            bookings=Count('id'),
        ).order_by('arrival_date__month')
        
        # Fill in actual data
        for stat in monthly_stats:
            month_idx = stat['arrival_date__month'] - 1
            revenue = stat['revenue'] or Decimal('0.00')
            room_nights = stat['room_nights'] or 0
            available = monthly_data[month_idx]['available']
            
            monthly_data[month_idx]['revenue'] = revenue
            monthly_data[month_idx]['room_nights'] = room_nights
            monthly_data[month_idx]['bookings'] = stat['bookings']
            
            # Calculate occupancy
            if available > 0:
                monthly_data[month_idx]['occupancy'] = (
                    Decimal(str(room_nights)) / Decimal(str(available)) * 100
                ).quantize(Decimal('0.1'))
            
            # Calculate ADR
            if room_nights > 0:
                monthly_data[month_idx]['adr'] = (
                    revenue / room_nights
                ).quantize(Decimal('0.01'))
        
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
        
        # Base queryset for this arrival month
        base_qs = self._get_base_queryset().filter(
            arrival_date__year=year,
            arrival_date__month=month
        )
        
        # Active bookings only for summary
        active_qs = base_qs.filter(
            status__in=['confirmed', 'checked_in', 'checked_out']
        )
        
        # Get room types for available calculation
        room_types = self._get_room_types()
        total_rooms = sum(rt.number_of_rooms for rt in room_types) or 1
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
        # COUNTRY DISTRIBUTION
        # ===================
        country_distribution = self._get_country_distribution(active_qs)
        
        return {
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'summary': summary,
            'velocity': velocity,
            'room_distribution': room_distribution,
            'lead_time': lead_time,
            'channel_distribution': channel_distribution,
            'country_distribution': country_distribution,
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
        
        # Active statuses
        active_statuses = ['confirmed', 'checked_in', 'checked_out']
        # Lost statuses (cancelled, void, no_show)
        lost_statuses = ['cancelled', 'void', 'no_show']
        
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
                'net_pickup': new_nights,  # Only active bookings count
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
        """Get distribution by guest country."""
        from django.db.models import Sum, Count
        
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
            bookings=Count('id')
        ).order_by('-room_nights')[:10]  # Top 10 countries
        
        distribution = []
        for row in by_country:
            country = row['guest__country'] or 'Unknown'
            distribution.append({
                'country': country,
                'room_nights': row['room_nights'] or 0,
                'bookings': row['bookings'] or 0,
            })
        
        # If no guest country data, return placeholder
        if not distribution:
            distribution = [{'country': 'Unknown', 'room_nights': 0, 'bookings': 0}]
        return distribution
