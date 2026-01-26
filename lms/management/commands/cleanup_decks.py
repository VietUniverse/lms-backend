"""
Management command to clean up orphaned deck files and student collections.

Usage:
    python manage.py cleanup_decks --dry-run  # Preview what would be deleted
    python manage.py cleanup_decks            # Actually delete orphaned files
"""

import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings

from lms.models import Deck


class Command(BaseCommand):
    help = 'Clean up orphaned .apkg files and optionally student collections'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only show what would be deleted, do not actually delete',
        )
        parser.add_argument(
            '--include-collections',
            action='store_true',
            help='Also clean up orphaned student collections (DANGEROUS)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        include_collections = options['include_collections']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No files will be deleted'))
        
        # 1. Clean up orphaned .apkg files
        self.cleanup_apkg_files(dry_run)
        
        # 2. Optionally clean up orphaned student collections
        if include_collections:
            self.cleanup_collections(dry_run)

    def cleanup_apkg_files(self, dry_run: bool):
        """Remove .apkg files that are not referenced by any Deck."""
        self.stdout.write('\n=== Cleaning up .apkg files ===')
        
        media_decks_path = Path(settings.MEDIA_ROOT) / 'decks'
        if not media_decks_path.exists():
            self.stdout.write('No media/decks directory found')
            return
        
        # Get all deck files referenced in database
        referenced_files = set()
        for deck in Deck.objects.all():
            if deck.appwrite_file_id and deck.appwrite_file_id.startswith('local:'):
                filename = deck.appwrite_file_id.replace('local:', '')
                referenced_files.add(filename)
        
        self.stdout.write(f'Referenced files in DB: {len(referenced_files)}')
        
        # Find orphaned files
        orphaned = []
        for file_path in media_decks_path.iterdir():
            if file_path.is_file() and file_path.suffix == '.apkg':
                if file_path.name not in referenced_files:
                    orphaned.append(file_path)
        
        self.stdout.write(f'Orphaned .apkg files: {len(orphaned)}')
        
        for file_path in orphaned:
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if dry_run:
                self.stdout.write(f'  Would delete: {file_path.name} ({size_mb:.2f} MB)')
            else:
                try:
                    os.remove(file_path)
                    self.stdout.write(self.style.SUCCESS(f'  Deleted: {file_path.name} ({size_mb:.2f} MB)'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Failed to delete {file_path.name}: {e}'))

    def cleanup_collections(self, dry_run: bool):
        """Remove student collections for users that no longer exist."""
        from django.contrib.auth import get_user_model
        
        self.stdout.write('\n=== Cleaning up student collections ===')
        
        anki_data_path = Path(getattr(settings, 'ANKI_SYNC_DATA_PATH', '/data'))
        if not anki_data_path.exists():
            self.stdout.write(f'Anki data path not found: {anki_data_path}')
            return
        
        User = get_user_model()
        existing_emails = set(User.objects.values_list('email', flat=True))
        
        self.stdout.write(f'Users in DB: {len(existing_emails)}')
        
        orphaned = []
        for student_dir in anki_data_path.iterdir():
            if student_dir.is_dir():
                email = student_dir.name
                if email not in existing_emails:
                    orphaned.append(student_dir)
        
        self.stdout.write(f'Orphaned collections: {len(orphaned)}')
        
        for student_dir in orphaned:
            if dry_run:
                self.stdout.write(f'  Would delete collection: {student_dir.name}')
            else:
                try:
                    import shutil
                    shutil.rmtree(student_dir)
                    self.stdout.write(self.style.SUCCESS(f'  Deleted collection: {student_dir.name}'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Failed to delete {student_dir.name}: {e}'))
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Cleanup complete!'))
