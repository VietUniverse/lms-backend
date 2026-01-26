from .models import MarketplaceItem

class MarketplaceItemSerializer(serializers.ModelSerializer):
    deck_title = serializers.CharField(source='deck.title', read_only=True)
    deck_description = serializers.CharField(source='deck.description', read_only=True, required=False) # Accessing description might fail if deck has no description field? Deck model has description?
    # Deck model in lms/models.py:
    # class Deck(models.Model):
    #     title = models.CharField(max_length=255)
    #     ... (no description field visible in my previous read? Let me check)
    #     card_count...
    
    author_name = serializers.CharField(source='author.full_name', read_only=True) # or email
    
    class Meta:
        model = MarketplaceItem
        fields = ['id', 'deck', 'deck_title', 'author', 'author_name', 'status', 'price', 'downloads', 'rating', 'source_url', 'created_at']
        read_only_fields = ['id', 'status', 'downloads', 'rating', 'author', 'created_at']

    def create(self, validated_data):
        # Assign author from context
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)
