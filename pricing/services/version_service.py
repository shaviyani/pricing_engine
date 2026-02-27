"""
Pricing Version Service & Dynamic Pricing Service
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone


class PricingVersionService:
    """Manages pricing matrix versions: create draft, publish, discard, revert."""
    
    def __init__(self, hotel):
        self.hotel = hotel
    
    def create_initial_version(self, name="Initial Rates", created_by="system"):
        """Create v1 from existing unversioned data."""
        from pricing.models import (
            PricingMatrixVersion, Season, RoomType, RatePlan, Channel,
            RateModifier, DynamicPricingRule
        )
        
        existing = PricingMatrixVersion.get_published(self.hotel)
        if existing:
            return existing
        
        with transaction.atomic():
            version = PricingMatrixVersion.objects.create(
                hotel=self.hotel, version_number=1, name=name,
                status='published', created_by=created_by,
                published_at=timezone.now(),
            )
            
            Season.objects.filter(hotel=self.hotel, version__isnull=True).update(version=version)
            RoomType.objects.filter(hotel=self.hotel, version__isnull=True).update(version=version)
            RatePlan.objects.filter(hotel=self.hotel, version__isnull=True).update(version=version)
            Channel.objects.filter(hotel=self.hotel, version__isnull=True).update(version=version)
            
            for channel in Channel.objects.filter(hotel=self.hotel, version=version):
                RateModifier.objects.filter(channel=channel, version__isnull=True).update(version=version)
            
            DynamicPricingRule.objects.filter(hotel=self.hotel, version__isnull=True).update(version=version)
            
            return version
    
    def create_draft(self, name, notes="", created_by=""):
        """Create a new draft by deep-copying published version records."""
        from pricing.models import PricingMatrixVersion
        
        existing_draft = PricingMatrixVersion.get_draft(self.hotel)
        if existing_draft:
            raise ValueError(f"A draft already exists: v{existing_draft.version_number} '{existing_draft.name}'")
        
        published = PricingMatrixVersion.get_published(self.hotel)
        if not published:
            raise ValueError("No published version exists. Create an initial version first.")
        
        with transaction.atomic():
            new_version = PricingMatrixVersion.objects.create(
                hotel=self.hotel,
                version_number=PricingMatrixVersion.get_next_version_number(self.hotel),
                name=name, status='draft', notes=notes, created_by=created_by,
            )
            self._deep_copy_records(published, new_version)
            return new_version
    
    def publish_draft(self):
        """Publish the current draft, archive the current published."""
        from pricing.models import PricingMatrixVersion
        
        draft = PricingMatrixVersion.get_draft(self.hotel)
        if not draft:
            raise ValueError("No draft exists to publish.")
        
        with transaction.atomic():
            published = PricingMatrixVersion.get_published(self.hotel)
            if published:
                published.status = 'archived'
                published.save()
            
            draft.status = 'published'
            draft.published_at = timezone.now()
            draft.save()
            return draft
    
    def discard_draft(self):
        """Delete the current draft and all its records."""
        from pricing.models import PricingMatrixVersion
        
        draft = PricingMatrixVersion.get_draft(self.hotel)
        if not draft:
            raise ValueError("No draft exists to discard.")
        
        with transaction.atomic():
            draft.delete()
    
    def revert_to_version(self, version_number, created_by=""):
        """Create a new draft from a historical version's records."""
        from pricing.models import PricingMatrixVersion
        
        source = PricingMatrixVersion.objects.filter(
            hotel=self.hotel, version_number=version_number
        ).first()
        if not source:
            raise ValueError(f"Version {version_number} not found.")
        
        existing_draft = PricingMatrixVersion.get_draft(self.hotel)
        if existing_draft:
            raise ValueError(f"Discard existing draft v{existing_draft.version_number} first.")
        
        with transaction.atomic():
            new_version = PricingMatrixVersion.objects.create(
                hotel=self.hotel,
                version_number=PricingMatrixVersion.get_next_version_number(self.hotel),
                name=f"Revert to v{version_number}: {source.name}",
                status='draft',
                notes=f"Reverted from v{version_number}",
                created_by=created_by,
            )
            self._deep_copy_records(source, new_version)
            return new_version
    
    def _deep_copy_records(self, source_version, target_version):
        """
        Deep-copy all versioned records from source to target.
        Collects all source data FIRST, then creates copies with remapped FKs.
        """
        from pricing.models import (
            Season, RoomType, RatePlan, Channel, RateModifier,
            SeasonModifierOverride, RoomTypeSeasonModifier,
            DynamicPricingRule, DynamicPricingBand, DynamicPricingMultiplier,
        )
        
        # ID maps: old_id -> new_object
        season_map = {}
        room_map = {}
        channel_map = {}
        modifier_map = {}
        rule_map = {}
        band_map = {}
        
        # Collect source data for junction tables BEFORE copying
        smo_data = list(SeasonModifierOverride.objects.filter(
            modifier__version=source_version
        ).values('modifier_id', 'season_id', 'discount_percent', 'is_customized', 'notes'))
        
        rtsm_data = list(RoomTypeSeasonModifier.objects.filter(
            room_type__version=source_version
        ).values('room_type_id', 'season_id', 'modifier', 'notes'))
        
        dp_mult_data = []
        for mult in DynamicPricingMultiplier.objects.filter(
            band__rule__version=source_version
        ).select_related('band', 'window_band'):
            dp_mult_data.append({
                'band_id': mult.band_id,
                'window_band_id': mult.window_band_id,
                'multiplier': mult.multiplier,
            })
        
        dp_band_data = []
        for band in DynamicPricingBand.objects.filter(rule__version=source_version):
            dp_band_data.append({
                'old_id': band.id,
                'rule_id': band.rule_id,
                'min_occupancy': band.min_occupancy,
                'max_occupancy': band.max_occupancy,
                'rationale': band.rationale,
                'sort_order': band.sort_order,
            })
        
        # 1. Seasons
        for old in Season.objects.filter(version=source_version):
            old_id = old.pk
            old.pk = None
            old.version = target_version
            old.save()
            season_map[old_id] = old
        
        # 2. RoomTypes
        for old in RoomType.objects.filter(version=source_version):
            old_id = old.pk
            old.pk = None
            old.version = target_version
            old.save()
            room_map[old_id] = old
        
        # 3. RatePlans
        for old in RatePlan.objects.filter(version=source_version):
            old.pk = None
            old.version = target_version
            old.save()
        
        # 4. Channels
        for old in Channel.objects.filter(version=source_version):
            old_id = old.pk
            old.pk = None
            old.version = target_version
            old.save()
            channel_map[old_id] = old
        
        # 5. RateModifiers (need channel remap)
        for old in RateModifier.objects.filter(version=source_version):
            old_id = old.pk
            old_channel_id = old.channel_id
            old.pk = None
            old.version = target_version
            old.channel = channel_map.get(old_channel_id, old.channel)
            old.save()
            modifier_map[old_id] = old
        
        # 6. SeasonModifierOverrides (from collected data, remap modifier + season)
        for data in smo_data:
            new_modifier = modifier_map.get(data['modifier_id'])
            new_season = season_map.get(data['season_id'])
            if new_modifier and new_season:
                SeasonModifierOverride.objects.update_or_create(
                    modifier=new_modifier,
                    season=new_season,
                    defaults={
                        'discount_percent': data['discount_percent'],
                        'is_customized': data['is_customized'],
                        'notes': data['notes'],
                    }
                )
        
        # 7. RoomTypeSeasonModifiers (from collected data, remap room + season)
        for data in rtsm_data:
            new_room = room_map.get(data['room_type_id'])
            new_season = season_map.get(data['season_id'])
            if new_room and new_season:
                RoomTypeSeasonModifier.objects.update_or_create(
                    room_type=new_room, season=new_season,
                    defaults={
                        'modifier': data['modifier'],
                        'notes': data['notes'],
                    }
                )
        
        # 8. DynamicPricingRules (need season remap)
        for old in DynamicPricingRule.objects.filter(version=source_version):
            old_id = old.pk
            old_season_id = old.season_id
            old.pk = None
            old.version = target_version
            old.season = season_map.get(old_season_id, old.season)
            old.save()
            rule_map[old_id] = old
        
        # 9. DynamicPricingBands (from collected data, remap rule)
        for data in dp_band_data:
            new_rule = rule_map.get(data['rule_id'])
            if new_rule:
                new_band = DynamicPricingBand.objects.create(
                    rule=new_rule,
                    min_occupancy=data['min_occupancy'],
                    max_occupancy=data['max_occupancy'],
                    rationale=data['rationale'],
                    sort_order=data['sort_order'],
                )
                band_map[data['old_id']] = new_band
        
        # 10. DynamicPricingMultipliers (from collected data, remap band)
        for data in dp_mult_data:
            new_band = band_map.get(data['band_id'])
            if new_band:
                DynamicPricingMultiplier.objects.create(
                    band=new_band,
                    window_band_id=data['window_band_id'],  # window bands are shared, not copied
                    multiplier=data['multiplier'],
                )
    
    def get_version_summary(self, version):
        """Get a summary of what's in a version."""
        from pricing.models import (
            Season, RoomType, RatePlan, Channel, RateModifier, DynamicPricingRule
        )
        
        return {
            'version': version,
            'seasons': Season.objects.filter(version=version).count(),
            'room_types': RoomType.objects.filter(version=version).count(),
            'rate_plans': RatePlan.objects.filter(version=version).count(),
            'channels': Channel.objects.filter(version=version).count(),
            'modifiers': RateModifier.objects.filter(version=version).count(),
            'dynamic_rules': DynamicPricingRule.objects.filter(version=version).count(),
        }
    
    def get_all_versions(self):
        """Get all versions for this property with summaries."""
        from pricing.models import PricingMatrixVersion
        versions = PricingMatrixVersion.objects.filter(hotel=self.hotel)
        return [self.get_version_summary(v) for v in versions]


class DynamicPricingService:
    """
    Looks up dynamic pricing multipliers based on:
    - Season type (peak, shoulder, low)
    - Current OTB occupancy %
    - Days until arrival
    
    Also handles event uplift lookups.
    """
    
    # Default multiplier matrices per season type
    # Format: (min_occ, max_occ, rationale, [90+, 60-89, 30-59, 7-29])
    PEAK_BANDS = [
        (90, 999, 'Maximum demand - ceiling', [1.20, 1.20, 1.20, 1.25]),
        (80, 90, 'Very strong demand', [1.15, 1.15, 1.15, 1.20]),
        (70, 80, 'Strong demand', [1.10, 1.10, 1.10, 1.10]),
        (60, 70, 'Good pace', [1.00, 1.05, 1.05, 1.05]),
        (50, 60, 'Below target', [0.95, 1.00, 0.95, 0.90]),
        (0, 50, 'Need volume - floor', [0.90, 0.90, 0.85, 0.80]),
    ]
    
    SHOULDER_BANDS = [
        (85, 999, 'Exceptional demand', [1.15, 1.15, 1.15, 1.20]),
        (70, 85, 'Strong demand', [1.10, 1.10, 1.10, 1.15]),
        (55, 70, 'Good pace', [1.05, 1.05, 1.05, 1.10]),
        (40, 55, 'On target', [1.00, 1.00, 1.00, 1.00]),
        (0, 40, 'Need volume', [0.85, 0.85, 0.85, 0.80]),
    ]
    
    LOW_BANDS = [
        (70, 999, 'Exceptional for monsoon', [1.15, 1.15, 1.15, 1.20]),
        (55, 70, 'Strong for low season', [1.10, 1.10, 1.10, 1.15]),
        (40, 55, 'Good pace', [1.05, 1.05, 1.05, 1.10]),
        (25, 40, 'Acceptable', [1.00, 1.00, 1.00, 1.00]),
        (0, 25, 'Emergency pricing', [0.80, 0.80, 0.70, 0.70]),
    ]
    
    SEASON_BAND_MAP = {
        'peak': PEAK_BANDS,
        'shoulder': SHOULDER_BANDS,
        'low': LOW_BANDS,
    }
    
    def __init__(self, hotel):
        self.hotel = hotel
    
    def get_multiplier(self, target_date, version=None):
        """
        Get the dynamic pricing multiplier for a specific date.
        
        Returns dict:
            occupancy_multiplier: from lookup table
            event_multiplier: from event uplifts
            combined_multiplier: occupancy * event
            occupancy_pct: current OTB occupancy
            days_out: days until arrival
            band_label: which occupancy band matched
            window_label: which booking window matched
            season_name: which season
        """
        from pricing.models import (
            PricingMatrixVersion, Season, RoomType, DynamicPricingRule,
            EventUplift
        )
        from pricing.models.analytics import Reservation
        
        if version is None:
            version = PricingMatrixVersion.get_published(self.hotel)
        
        if not version:
            return self._default_result(target_date)
        
        # 1. Find season for this date
        season = Season.objects.filter(
            hotel=self.hotel, version=version,
            start_date__lte=target_date, end_date__gte=target_date
        ).first()
        
        if not season:
            return self._default_result(target_date)
        
        # 2. Calculate property-wide OTB occupancy
        total_rooms = RoomType.objects.filter(
            hotel=self.hotel, version=version
        ).aggregate(total=Sum('number_of_rooms'))['total'] or 0
        
        if total_rooms == 0:
            return self._default_result(target_date, season=season)
        
        booked = Reservation.objects.filter(
            hotel=self.hotel,
            arrival_date__lte=target_date,
            departure_date__gt=target_date,
            status__in=Reservation.FUTURE_STATUSES
        ).count()

        occupancy_pct = Decimal(str(booked)) / Decimal(str(total_rooms)) * Decimal('100')
        
        # 3. Days until arrival
        days_out = (target_date - date.today()).days
        if days_out < 0:
            days_out = 0
        
        # 4. Look up dynamic pricing rule for this season
        rule = DynamicPricingRule.objects.filter(
            hotel=self.hotel, version=version,
            season=season, is_active=True
        ).first()
        
        occ_multiplier = Decimal('1.00')
        band_label = "No rule"
        window_label = "N/A"
        
        if rule:
            # Find matching occupancy band
            occ_band = rule.bands.filter(
                min_occupancy__lte=occupancy_pct,
                max_occupancy__gt=occupancy_pct
            ).first()
            
            if occ_band:
                band_label = str(occ_band)
                
                # Find matching window band
                window_band = rule.booking_window_config.bands.all()
                matched_window = None
                for wb in window_band:
                    if wb.contains_days(days_out):
                        matched_window = wb
                        break
                
                if matched_window:
                    window_label = matched_window.label
                    # Get the multiplier cell
                    from pricing.models import DynamicPricingMultiplier
                    cell = DynamicPricingMultiplier.objects.filter(
                        band=occ_band, window_band=matched_window
                    ).first()
                    if cell:
                        occ_multiplier = cell.multiplier
        
        # 5. Event uplift
        event = EventUplift.objects.filter(
            hotel=self.hotel, is_active=True,
            start_date__lte=target_date, end_date__gte=target_date
        ).order_by('-uplift_percent').first()
        
        event_multiplier = Decimal('1.00')
        event_name = None
        if event:
            event_multiplier = Decimal('1.00') + (event.uplift_percent / Decimal('100'))
            event_name = event.name
        
        combined = (occ_multiplier * event_multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        return {
            'occupancy_multiplier': occ_multiplier,
            'event_multiplier': event_multiplier,
            'combined_multiplier': combined,
            'occupancy_pct': occupancy_pct.quantize(Decimal('0.1')),
            'total_rooms': total_rooms,
            'booked_rooms': booked,
            'days_out': days_out,
            'band_label': band_label,
            'window_label': window_label,
            'season_name': season.name if season else 'N/A',
            'season_type': season.season_type if season else 'N/A',
            'event_name': event_name,
        }
    
    def get_bulk_multipliers(self, date_range_start, date_range_end, version=None):
        """
        Get multipliers for a date range. Returns dict of {date: result}.
        More efficient than calling get_multiplier per date.
        """
        results = {}
        current = date_range_start
        while current <= date_range_end:
            results[current] = self.get_multiplier(current, version)
            current += timedelta(days=1)
        return results
    
    def _default_result(self, target_date, season=None):
        return {
            'occupancy_multiplier': Decimal('1.00'),
            'event_multiplier': Decimal('1.00'),
            'combined_multiplier': Decimal('1.00'),
            'occupancy_pct': Decimal('0.0'),
            'total_rooms': 0,
            'booked_rooms': 0,
            'days_out': (target_date - date.today()).days,
            'band_label': 'No data',
            'window_label': 'N/A',
            'season_name': season.name if season else 'No season',
            'season_type': season.season_type if season else 'N/A',
            'event_name': None,
        }
    
    def seed_single_season(self, season):
        """
        Create default dynamic pricing rules for a single season.
        If rules already exist and season_type changed, replaces them.
        
        Called automatically by Season post_save signal.
        """
        from pricing.models import (
            BookingWindowConfig, DynamicPricingRule,
            DynamicPricingBand, DynamicPricingMultiplier,
        )
        
        bw_config = BookingWindowConfig.get_or_create_default(self.hotel)
        window_bands = list(bw_config.bands.order_by('sort_order'))
        
        if len(window_bands) != 4:
            return
        
        wb_7, wb_30, wb_60, wb_90 = window_bands
        
        band_defs = self.SEASON_BAND_MAP.get(season.season_type, self.SHOULDER_BANDS)
        
        # Check for existing rule
        existing = DynamicPricingRule.objects.filter(
            hotel=self.hotel, season=season
        )
        if season.version_id:
            existing = existing.filter(version=season.version)
        
        existing = existing.first()
        
        if existing:
            # Rule exists — check if season_type changed
            # Compare first band's rationale to detect type mismatch
            first_band = existing.bands.order_by('-min_occupancy').first()
            expected_first_rationale = band_defs[0][2] if band_defs else ''
            
            if first_band and first_band.rationale == expected_first_rationale:
                return  # Same season type, preserve user edits
            
            # Season type changed — delete old and recreate
            existing.delete()
        
        rule = DynamicPricingRule.objects.create(
            hotel=self.hotel,
            version=season.version,
            season=season,
            booking_window_config=bw_config,
            is_active=True,
        )
        
        for idx, (min_occ, max_occ, rationale, multipliers) in enumerate(band_defs):
            occ_band = DynamicPricingBand.objects.create(
                rule=rule,
                min_occupancy=Decimal(str(min_occ)),
                max_occupancy=Decimal(str(max_occ)),
                rationale=rationale,
                sort_order=idx,
            )
            for wb, mult_val in zip([wb_90, wb_60, wb_30, wb_7], multipliers):
                DynamicPricingMultiplier.objects.create(
                    band=occ_band,
                    window_band=wb,
                    multiplier=Decimal(str(mult_val)),
                )

    def seed_default_rules(self, version):
        """
        Seed the default dynamic pricing rules from the spreadsheet model.
        Creates rules for peak, shoulder, and low seasons.
        """
        from pricing.models import (
            Season, BookingWindowConfig, BookingWindowBand,
            DynamicPricingRule, DynamicPricingBand, DynamicPricingMultiplier,
        )
        
        # Get or create default booking window config
        bw_config = BookingWindowConfig.get_or_create_default(self.hotel)
        window_bands = list(bw_config.bands.order_by('sort_order'))
        
        if len(window_bands) != 4:
            return  # Can't seed without standard 4 windows
        
        # Window bands order: 7-29, 30-59, 60-89, 90+
        wb_7, wb_30, wb_60, wb_90 = window_bands
        
        seasons = Season.objects.filter(hotel=self.hotel, version=version)
        
        for season in seasons:
            band_defs = self.SEASON_BAND_MAP.get(season.season_type, self.SHOULDER_BANDS)
            
            # Check if rule already exists
            existing = DynamicPricingRule.objects.filter(
                hotel=self.hotel, version=version, season=season
            ).first()
            if existing:
                continue
            
            rule = DynamicPricingRule.objects.create(
                hotel=self.hotel, version=version,
                season=season, booking_window_config=bw_config,
                is_active=True,
            )
            
            for idx, (min_occ, max_occ, rationale, multipliers) in enumerate(band_defs):
                occ_band = DynamicPricingBand.objects.create(
                    rule=rule,
                    min_occupancy=Decimal(str(min_occ)),
                    max_occupancy=Decimal(str(max_occ)),
                    rationale=rationale,
                    sort_order=idx,
                )
                
                # multipliers order: [90+, 60-89, 30-59, 7-29]
                for wb, mult_val in zip([wb_90, wb_60, wb_30, wb_7], multipliers):
                    DynamicPricingMultiplier.objects.create(
                        band=occ_band,
                        window_band=wb,
                        multiplier=Decimal(str(mult_val)),
                    )


# =============================================================================
# DYNAMIC PRICING OPTIMIZER
# =============================================================================

class DynamicPricingOptimizer:
    """
    Analyzes historical reservation data against the current dynamic pricing
    matrix and generates suggestions to optimize RevPAR.
    
    For each cell (season_type × occupancy_band × booking_window):
    1. Finds all bookings that fell into this cell historically
    2. Calculates what ADR, occupancy, and RevPAR were actually achieved
    3. Estimates what multiplier would have maximized RevPAR
    4. Generates a suggestion if the difference is meaningful
    
    Thresholds:
    - Minimum 5 bookings per cell to generate a suggestion
    - Confidence: 5-10 = low, 10-20 = medium, 20+ = high
    - Minimum ±0.05 change to suggest (ignore noise)
    - Maximum ±0.15 change per suggestion (no wild swings)
    """
    
    MIN_SAMPLE_SIZE = 5
    MIN_CHANGE_THRESHOLD = Decimal('0.05')
    MAX_CHANGE_CAP = Decimal('0.15')
    
    CONFIDENCE_THRESHOLDS = {
        'low': 5,
        'medium': 10,
        'high': 20,
    }
    
    def __init__(self, hotel):
        self.hotel = hotel
    
    def analyze(self, version=None):
        """
        Run full analysis and return list of suggestion dicts (not yet saved).
        
        Returns:
            list of dicts, each representing a potential suggestion
        """
        from pricing.models import (
            PricingMatrixVersion, Season, RoomType, Reservation,
            DynamicPricingRule, DynamicPricingBand, DynamicPricingMultiplier,
            BookingWindowConfig,
        )
        
        if version is None:
            version = PricingMatrixVersion.get_published(self.hotel)
        
        if not version:
            return []
        
        # Get all reservations for this hotel (non-cancelled)
        reservations = Reservation.objects.filter(
            hotel=self.hotel,
            status__in=Reservation.ACTIVE_STATUSES,
        ).exclude(adr=Decimal('0.00')).select_related('room_type')
        
        if not reservations.exists():
            return []
        
        # Get total room inventory for occupancy calculations
        total_rooms = RoomType.objects.filter(
            hotel=self.hotel, version=version
        ).aggregate(total=Sum('number_of_rooms'))['total'] or 0
        
        if total_rooms == 0:
            return []
        
        # Get all seasons and booking window config
        seasons = Season.objects.filter(hotel=self.hotel, version=version)
        bw_config = BookingWindowConfig.get_or_create_default(self.hotel)
        window_bands = list(bw_config.bands.order_by('sort_order'))
        
        # Get the base rate for RevPAR normalization
        base_rate = self.hotel.reference_base_rate or Decimal('100.00')
        
        # Build a lookup of current multipliers
        rules = DynamicPricingRule.objects.filter(
            hotel=self.hotel, version=version, is_active=True
        ).select_related('season').prefetch_related(
            'bands__multipliers__window_band'
        )
        
        # Analyze period
        all_booking_dates = reservations.values_list('booking_date', flat=True)
        all_arrival_dates = reservations.values_list('arrival_date', flat=True)
        period_start = min(min(all_booking_dates), min(all_arrival_dates))
        period_end = max(max(all_booking_dates), max(all_arrival_dates))
        
        # === STEP 1: Classify each reservation into a matrix cell ===
        cell_data = {}  # key: (season_type, band_label, window_label)
        
        for res in reservations:
            # Find which season this stay falls in
            season = None
            for s in seasons:
                if s.start_date <= res.arrival_date <= s.end_date:
                    season = s
                    break
            
            if not season:
                continue
            
            # Determine booking window
            lead_time = res.lead_time_days
            if lead_time < 0:
                lead_time = 0
            
            matched_window = None
            for wb in window_bands:
                if wb.contains_days(lead_time):
                    matched_window = wb
                    break
            
            if not matched_window:
                continue
            
            # Estimate OTB occupancy at time of booking
            # Count how many other confirmed bookings existed for this arrival date
            # at or before this booking's booking_date
            otb_at_booking = Reservation.objects.filter(
                hotel=self.hotel,
                arrival_date__lte=res.arrival_date,
                departure_date__gt=res.arrival_date,
                booking_date__lte=res.booking_date,
                status__in=Reservation.ACTIVE_STATUSES,
            ).exclude(pk=res.pk).count()
            
            occupancy_pct = Decimal(str(otb_at_booking)) / Decimal(str(total_rooms)) * Decimal('100')
            
            # Find which occupancy band
            rule = None
            for r in rules:
                if r.season_id == season.id:
                    rule = r
                    break
            
            if not rule:
                continue
            
            matched_band = None
            for band in rule.bands.all().order_by('-min_occupancy'):
                if band.min_occupancy <= occupancy_pct:
                    if occupancy_pct < band.max_occupancy or band.max_occupancy >= 999:
                        matched_band = band
                        break
            
            if not matched_band:
                continue
            
            # Get current multiplier for this cell
            current_mult = Decimal('1.00')
            for mult in matched_band.multipliers.all():
                if mult.window_band_id == matched_window.id:
                    current_mult = mult.multiplier
                    break
            
            # Aggregate into cell
            cell_key = (season.season_type, str(matched_band), matched_window.label)
            
            if cell_key not in cell_data:
                cell_data[cell_key] = {
                    'season_type': season.season_type,
                    'band_label': str(matched_band),
                    'window_label': matched_window.label,
                    'band': matched_band,
                    'window_band': matched_window,
                    'current_multiplier': current_mult,
                    'bookings': [],
                    'adrs': [],
                    'occupancy_at_booking': [],
                    'total_revenue': Decimal('0.00'),
                    'total_nights': 0,
                }
            
            cell = cell_data[cell_key]
            cell['bookings'].append(res)
            cell['adrs'].append(res.adr)
            cell['occupancy_at_booking'].append(float(occupancy_pct))
            cell['total_revenue'] += res.total_amount
            cell['total_nights'] += res.nights
        
        # === STEP 2: For each cell, calculate performance and suggest ===
        suggestions = []
        
        for cell_key, cell in cell_data.items():
            sample_size = len(cell['bookings'])
            
            if sample_size < self.MIN_SAMPLE_SIZE:
                continue
            
            # Actual performance
            actual_adr = sum(cell['adrs']) / len(cell['adrs'])
            avg_occupancy_at_booking = sum(cell['occupancy_at_booking']) / len(cell['occupancy_at_booking'])
            
            # Final occupancy for these stay dates (what did occupancy end up being?)
            # Use average of arrival dates
            arrival_dates = set(r.arrival_date for r in cell['bookings'])
            total_booked_nights = 0
            total_available_nights = 0
            for arr_date in arrival_dates:
                booked = Reservation.objects.filter(
                    hotel=self.hotel,
                    arrival_date__lte=arr_date,
                    departure_date__gt=arr_date,
                    status__in=Reservation.ACTIVE_STATUSES,
                ).count()
                total_booked_nights += booked
                total_available_nights += total_rooms
            
            actual_occ = (Decimal(str(total_booked_nights)) / Decimal(str(total_available_nights)) * 100) if total_available_nights > 0 else Decimal('0')
            actual_revpar = actual_adr * (actual_occ / Decimal('100'))
            
            # What the multiplier implied as ADR target
            # implied_adr = base_rate × avg_season_index × current_multiplier
            avg_season_index = Decimal('1.00')
            for s in seasons:
                if s.season_type == cell['season_type']:
                    avg_season_index = s.season_index
                    break
            
            implied_rate = base_rate * avg_season_index * cell['current_multiplier']
            
            # Calculate effective multiplier from actual data
            # effective_mult = actual_adr / (base_rate × season_index)
            denominator = base_rate * avg_season_index
            if denominator > 0:
                effective_mult = (actual_adr / denominator).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                effective_mult = Decimal('1.00')
            
            # === RevPAR optimization logic ===
            # If actual_occ is very high (>85%) and ADR could be pushed → increase multiplier
            # If actual_occ is low (<50%) and ADR is above implied → multiplier too high
            # Target: find multiplier that maximizes ADR × occupancy
            
            suggested = self._calculate_optimal_multiplier(
                current=cell['current_multiplier'],
                effective=effective_mult,
                actual_occ=float(actual_occ),
                actual_adr=float(actual_adr),
                base_rate=float(base_rate * avg_season_index),
                sample_size=sample_size,
            )
            
            change = suggested - cell['current_multiplier']
            abs_change = abs(change)
            
            # Skip if change is too small
            if abs_change < self.MIN_CHANGE_THRESHOLD:
                continue
            
            # Cap the change
            if abs_change > self.MAX_CHANGE_CAP:
                if change > 0:
                    suggested = cell['current_multiplier'] + self.MAX_CHANGE_CAP
                else:
                    suggested = cell['current_multiplier'] - self.MAX_CHANGE_CAP
            
            # Clamp within 0.50 - 2.00
            suggested = max(Decimal('0.50'), min(Decimal('2.00'), suggested))
            
            # Recalculate direction after capping
            change = suggested - cell['current_multiplier']
            if change > 0:
                direction = 'increase'
            elif change < 0:
                direction = 'decrease'
            else:
                continue
            
            # Confidence
            confidence = 'low'
            if sample_size >= self.CONFIDENCE_THRESHOLDS['high']:
                confidence = 'high'
            elif sample_size >= self.CONFIDENCE_THRESHOLDS['medium']:
                confidence = 'medium'
            
            # Estimate RevPAR improvement
            current_implied_revpar = float(implied_rate) * float(actual_occ) / 100
            new_implied_rate = float(base_rate * avg_season_index * suggested)
            # Rough estimate: higher rate may reduce occupancy slightly
            elasticity = -0.3  # 10% rate increase → 3% occupancy decrease
            rate_change_pct = (float(suggested) - float(cell['current_multiplier'])) / float(cell['current_multiplier'])
            occ_impact = float(actual_occ) * (1 + elasticity * rate_change_pct)
            occ_impact = max(0, min(100, occ_impact))
            estimated_new_revpar = new_implied_rate * occ_impact / 100
            revpar_improvement = ((estimated_new_revpar - current_implied_revpar) / current_implied_revpar * 100) if current_implied_revpar > 0 else 0
            
            # Build reasoning
            reasoning = self._build_reasoning(
                cell['season_type'], cell['band_label'], cell['window_label'],
                cell['current_multiplier'], suggested, direction,
                sample_size, actual_adr, actual_occ, actual_revpar,
                effective_mult, avg_occupancy_at_booking,
            )
            
            suggestions.append({
                'hotel': self.hotel,
                'season_type': cell['season_type'],
                'occupancy_band_label': cell['band_label'],
                'window_band_label': cell['window_label'],
                'band': cell['band'],
                'window_band': cell['window_band'],
                'current_multiplier': cell['current_multiplier'],
                'suggested_multiplier': suggested,
                'direction': direction,
                'sample_size': sample_size,
                'confidence': confidence,
                'actual_adr': actual_adr.quantize(Decimal('0.01')),
                'actual_occupancy_pct': actual_occ.quantize(Decimal('0.1')),
                'actual_revpar': actual_revpar.quantize(Decimal('0.01')),
                'optimal_revpar': Decimal(str(round(estimated_new_revpar, 2))),
                'revpar_improvement_pct': Decimal(str(round(revpar_improvement, 1))),
                'reasoning': reasoning,
                'analysis_period_start': period_start,
                'analysis_period_end': period_end,
            })
        
        # Sort: highest RevPAR improvement first
        suggestions.sort(key=lambda s: float(s['revpar_improvement_pct']), reverse=True)
        
        return suggestions
    
    def _calculate_optimal_multiplier(self, current, effective, actual_occ, actual_adr,
                                       base_rate, sample_size):
        """
        Calculate the optimal multiplier for RevPAR maximization.
        
        Logic:
        - High occ + high ADR → push multiplier up (market can bear more)
        - High occ + low ADR → multiplier is right but could go up slightly
        - Low occ + high ADR → multiplier too aggressive, lower to fill rooms
        - Low occ + low ADR → demand is weak, lower multiplier significantly
        
        Uses a blend of the effective multiplier (what guests actually paid)
        and an occupancy-adjusted target.
        """
        current = Decimal(str(current))
        effective = Decimal(str(effective))
        
        # Weight 1: What guests actually paid (effective multiplier)
        # This tells us what the market was willing to pay
        weight_effective = Decimal('0.50')
        
        # Weight 2: Occupancy-adjusted multiplier
        # If occupancy was very high, we could have charged more
        # If occupancy was low, we need to charge less
        if actual_occ > 85:
            # Room to push rates up — was nearly full regardless
            occ_adjusted = effective * Decimal('1.08')
        elif actual_occ > 70:
            # Good occupancy, slight room to optimize
            occ_adjusted = effective * Decimal('1.03')
        elif actual_occ > 50:
            # Moderate occupancy, trust the effective rate
            occ_adjusted = effective
        elif actual_occ > 30:
            # Below target, need to lower
            occ_adjusted = effective * Decimal('0.95')
        else:
            # Very low occupancy, aggressive discount
            occ_adjusted = effective * Decimal('0.90')
        
        weight_occ = Decimal('0.50')
        
        # Blended suggestion
        suggested = (effective * weight_effective + occ_adjusted * weight_occ)
        
        # Round to nearest 0.05 for clean values
        suggested = (suggested * 20).quantize(Decimal('1'), rounding=ROUND_HALF_UP) / 20
        
        return suggested
    
    def _build_reasoning(self, season_type, band_label, window_label,
                          current, suggested, direction, sample_size,
                          actual_adr, actual_occ, actual_revpar,
                          effective_mult, avg_occ_at_booking):
        """Build human-readable reasoning for a suggestion."""
        
        parts = []
        parts.append(f"Based on {sample_size} bookings in {season_type} season, "
                      f"{band_label} occupancy band, {window_label} booking window.")
        
        parts.append(f"Actual ADR was ${actual_adr:.0f} with {actual_occ:.0f}% final occupancy, "
                      f"yielding RevPAR of ${actual_revpar:.0f}.")
        
        parts.append(f"The effective multiplier from actual rates was x{effective_mult:.2f} "
                      f"vs current setting of x{current:.2f}.")
        
        if direction == 'increase':
            if float(actual_occ) > 75:
                parts.append(f"Strong occupancy ({actual_occ:.0f}%) suggests the market can bear "
                             f"higher rates in this segment.")
            else:
                parts.append(f"Actual rates achieved (x{effective_mult:.2f}) exceeded the current "
                             f"multiplier, suggesting room for increase.")
        else:
            if float(actual_occ) < 50:
                parts.append(f"Low occupancy ({actual_occ:.0f}%) indicates the current multiplier "
                             f"may be too aggressive for this segment.")
            else:
                parts.append(f"Actual rates achieved (x{effective_mult:.2f}) were below the current "
                             f"multiplier, suggesting a reduction would better match demand.")
        
        parts.append(f"Recommendation: adjust from x{current:.2f} to x{suggested:.2f}.")
        
        return " ".join(parts)
    
    def generate_suggestions(self, version=None):
        """
        Run analysis and save suggestions to database.
        Expires any previous pending suggestions for this hotel first.
        
        Returns:
            list of DynamicPricingSuggestion objects created
        """
        from pricing.models import DynamicPricingSuggestion
        
        # Expire old pending suggestions
        DynamicPricingSuggestion.objects.filter(
            hotel=self.hotel, status='pending'
        ).update(status='expired')
        
        # Run analysis
        raw_suggestions = self.analyze(version)
        
        # Save to database
        created = []
        for s in raw_suggestions:
            obj = DynamicPricingSuggestion.objects.create(**s)
            created.append(obj)
        
        return created
    
    @staticmethod
    def apply_suggestion(suggestion_id):
        """
        Accept a suggestion: update the DynamicPricingMultiplier cell
        and mark the suggestion as accepted.
        """
        from pricing.models import DynamicPricingSuggestion, DynamicPricingMultiplier
        
        suggestion = DynamicPricingSuggestion.objects.get(pk=suggestion_id)
        
        if suggestion.status != 'pending':
            raise ValueError(f"Suggestion is {suggestion.status}, not pending.")
        
        if suggestion.band and suggestion.window_band:
            mult_obj, _ = DynamicPricingMultiplier.objects.update_or_create(
                band=suggestion.band,
                window_band=suggestion.window_band,
                defaults={'multiplier': suggestion.suggested_multiplier},
            )
        
        suggestion.status = 'accepted'
        suggestion.reviewed_at = timezone.now()
        suggestion.save()
        
        return suggestion
    
    @staticmethod
    def reject_suggestion(suggestion_id):
        """Mark a suggestion as rejected."""
        from pricing.models import DynamicPricingSuggestion
        
        suggestion = DynamicPricingSuggestion.objects.get(pk=suggestion_id)
        
        if suggestion.status != 'pending':
            raise ValueError(f"Suggestion is {suggestion.status}, not pending.")
        
        suggestion.status = 'rejected'
        suggestion.reviewed_at = timezone.now()
        suggestion.save()
        
        return suggestion
