from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError

class Command(BaseCommand):
    help = 'Checks database connection'

    def handle(self, *args, **options):
        db_conn = connections['default']
        try:
            c = db_conn.cursor()
            self.stdout.write(self.style.SUCCESS('Database connected successfully'))
        except OperationalError:
            self.stdout.write(self.style.ERROR('Database unavailable'))
