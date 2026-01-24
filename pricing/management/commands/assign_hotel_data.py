from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Assign existing data to Biosphere Inn hotel'

    def handle(self, *args, **options):
        from pricing.models import (
            Organization, Property, Season, RoomType, Reservation, FileImport,
            DailyPickupSnapshot, MonthlyPickupSnapshot, PickupCurve, OccupancyForecast
        )
        
        # Get the hotel
        try:
            hotel = Property.objects.get(code='biosphere-inn')
            self.stdout.write(f"Found hotel: {hotel.name} (ID: {hotel.id})")
        except Property.DoesNotExist:
            self.stdout.write(self.style.ERROR("Hotel 'biosphere-inn' not found!"))
            return
        
        # Models that need hotel assignment
        models_to_update = [
            (Season, 'seasons'),
            (RoomType, 'room types'),
            (Reservation, 'reservations'),
            (FileImport, 'file imports'),
            (DailyPickupSnapshot, 'daily snapshots'),
            (MonthlyPickupSnapshot, 'monthly snapshots'),
            (PickupCurve, 'pickup curves'),
            (OccupancyForecast, 'forecasts'),
        ]
        
        self.stdout.write("")
        self.stdout.write("Checking for orphaned records...")
        self.stdout.write("")
        
        total_updated = 0
        
        with transaction.atomic():
            for model, name in models_to_update:
                # Count orphaned records
                orphaned_count = model.objects.filter(hotel__isnull=True).count()
                
                if orphaned_count > 0:
                    # Update them
                    updated = model.objects.filter(hotel__isnull=True).update(hotel=hotel)
                    total_updated += updated
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ Assigned {updated} {name} to {hotel.name}")
                    )
                else:
                    self.stdout.write(f"  - No orphaned {name}")
        
        self.stdout.write("")
        if total_updated > 0:
            self.stdout.write(self.style.SUCCESS(f"Total: {total_updated} records assigned to {hotel.name}"))
        else:
            self.stdout.write("All data is already assigned to a hotel.")
        
        # Summary
        self.stdout.write("")
        self.stdout.write("Current data summary:")
        for model, name in models_to_update:
            count = model.objects.filter(hotel=hotel).count()
            self.stdout.write(f"  {name}: {count}")