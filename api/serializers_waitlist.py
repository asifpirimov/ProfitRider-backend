from rest_framework import serializers
from .models import Waitlist
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class WaitlistSerializer(serializers.ModelSerializer):
    """
    Serializer for waitlist signups.
    Validates email format and prevents duplicates.
    """
    class Meta:
        model = Waitlist
        fields = ['email', 'source', 'created_at']
        read_only_fields = ['created_at']
    
    def validate_email(self, value):
        """
        Validate email format and check for duplicates.
        """
        # Normalize email to lowercase
        value = value.lower().strip()
        
        # Validate email format
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError("Please enter a valid email address.")
        
        # Check for duplicates
        if Waitlist.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already on the waitlist.")
        
        return value
