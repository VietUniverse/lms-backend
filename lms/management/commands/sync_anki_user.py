from django.core.management.base import BaseCommand
from lms.anki_sync import create_anki_user, change_anki_password
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Create or update Anki sync user'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str)
        parser.add_argument('password', type=str)
        parser.add_argument('--update', action='store_true', help='Update password if user exists')

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        update = options['update']

        if update:
            success = change_anki_password(email, password)
            action = "Updated"
        else:
            success = create_anki_user(email, password)
            action = "Created"

        if success:
            self.stdout.write(self.style.SUCCESS(f'{action} Anki user {email} successfully'))
        else:
            self.stdout.write(self.style.ERROR(f'Failed to {action.lower()} Anki user {email}'))
