"""
Management command to import reservations from Excel/CSV files.

Usage:
    python manage.py import_reservations path/to/file.xlsx
    python manage.py import_reservations path/to/file.xlsx --validate-only
    python manage.py import_reservations path/to/file.xlsx --verbose
"""

from django.core.management.base import BaseCommand, CommandError
from pathlib import Path


class Command(BaseCommand):
    help = 'Import reservations from Excel or CSV file'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'file_path',
            type=str,
            help='Path to the Excel or CSV file to import'
        )
        parser.add_argument(
            '--validate-only',
            action='store_true',
            help='Only validate the file without importing'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output'
        )
    
    def handle(self, *args, **options):
        from pricing.services.import_service import ReservationImportService
        
        file_path = Path(options['file_path'])
        
        # Check file exists
        if not file_path.exists():
            raise CommandError(f'File not found: {file_path}')
        
        # Check file extension
        if file_path.suffix.lower() not in ['.xlsx', '.xls', '.csv']:
            raise CommandError(f'Unsupported file format: {file_path.suffix}')
        
        service = ReservationImportService()
        
        self.stdout.write(f'Processing: {file_path.name}')
        self.stdout.write('')
        
        # Validate only mode
        if options['validate_only']:
            self.stdout.write('Validating file...')
            result = service.validate_file(str(file_path))
            
            if result['valid']:
                self.stdout.write(self.style.SUCCESS('✓ File is valid'))
            else:
                self.stdout.write(self.style.ERROR('✗ File has issues'))
            
            # Show issues
            if result['issues']:
                self.stdout.write('')
                self.stdout.write(self.style.ERROR('Issues:'))
                for issue in result['issues']:
                    self.stdout.write(f"  - {issue['message']}")
            
            # Show warnings
            if result['warnings']:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING('Warnings:'))
                for warning in result['warnings']:
                    self.stdout.write(f"  - {warning['message']}")
            
            # Show stats
            stats = result.get('stats', {})
            self.stdout.write('')
            self.stdout.write('Statistics:')
            self.stdout.write(f"  Total rows: {stats.get('total_rows', '?')}")
            
            if stats.get('date_range'):
                self.stdout.write(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")
            
            self.stdout.write(f"  Columns found: {', '.join(stats.get('columns_found', []))}")
            
            return
        
        # Import mode
        self.stdout.write('Importing reservations...')
        self.stdout.write('')
        
        try:
            result = service.import_file(str(file_path))
            
            # Show results
            if result['success']:
                self.stdout.write(self.style.SUCCESS(f"✓ Import completed: {result['status']}"))
            else:
                self.stdout.write(self.style.ERROR(f"✗ Import failed: {result['status']}"))
            
            self.stdout.write('')
            self.stdout.write('Results:')
            self.stdout.write(f"  Total rows:    {result['rows_total']}")
            self.stdout.write(self.style.SUCCESS(f"  Created:       {result['rows_created']}"))
            self.stdout.write(f"  Updated:       {result['rows_updated']}")
            self.stdout.write(f"  Skipped:       {result['rows_skipped']}")
            self.stdout.write(f"  Success rate:  {result['success_rate']:.1f}%")
            
            if result.get('duration_seconds'):
                self.stdout.write(f"  Duration:      {result['duration_seconds']:.1f}s")
            
            # Show errors if verbose or if there are errors
            if result['errors'] and (options['verbose'] or len(result['errors']) <= 10):
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(f"Errors ({len(result['errors'])}):"))
                for error in result['errors'][:20]:
                    row = error.get('row', '?')
                    msg = error.get('message', str(error))
                    self.stdout.write(f"  Row {row}: {msg}")
                
                if len(result['errors']) > 20:
                    self.stdout.write(f"  ... and {len(result['errors']) - 20} more errors")
            elif result['errors']:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(f"{len(result['errors'])} errors (use --verbose to see details)"))
            
            self.stdout.write('')
            self.stdout.write(f"File Import ID: {result['file_import_id']}")
            
        except Exception as e:
            raise CommandError(f'Import failed: {str(e)}')