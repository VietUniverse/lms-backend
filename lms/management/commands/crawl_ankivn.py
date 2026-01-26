from django.core.management.base import BaseCommand
from lms.models import Deck, MarketplaceItem, User
import requests

class Command(BaseCommand):
    help = 'Import decks from external source (stub)'

    def handle(self, *args, **options):
        self.stdout.write("Scraping ankivn.com...")
        
        # Stub implementation
        # Real implementation would use BeautifulSoup to parse https://ankivn.com/decks/?sort=date
        # And download .apkg files, then upload to Appwrite.
        
        # Here we just create a sample Marketplace Item
        
        try:
            admin = User.objects.filter(role='teacher').first() # Use a teacher as author
            if not admin:
                self.stdout.write(self.style.ERROR('No teacher found to assign as author'))
                return

            # Check if deck exists
            deck_title = "Demo Imported Deck: 3000 từ vựng thông dụng"
            deck, created = Deck.objects.get_or_create(
                title=deck_title,
                defaults={
                    'teacher': admin,
                    'card_count': 3000,
                    'status': 'ACTIVE',
                    'appwrite_file_id': 'stub_file_id',
                    'appwrite_file_url': 'https://ankivn.com/stub'
                }
            )
            
            # Add to Marketplace
            item, created = MarketplaceItem.objects.get_or_create(
                deck=deck,
                defaults={
                    'author': admin,
                    'status': 'APPROVED',
                    'price': 0,
                    'source_url': 'https://ankivn.com/decks/3000-tu-vung'
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully imported "{deck.title}" to Marketplace'))
            else:
                self.stdout.write(f'Deck "{deck.title}" already in Marketplace')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
