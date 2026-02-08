from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Country, Platform, UserProfile, WorkSession

class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = '__all__'

class PlatformSerializer(serializers.ModelSerializer):
    country_name = serializers.ReadOnlyField(source='country.name')
    
    class Meta:
        model = Platform
        fields = ['id', 'name', 'base_fee_percentage', 'country', 'country_name']

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    country_details = CountrySerializer(source='country', read_only=True)
    platforms_details = PlatformSerializer(source='platforms', many=True, read_only=True)
    
    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'country', 'country_details', 'transport_type',
                  'courier_type', 'fee_percent',
                  'default_start_time', 'default_end_time',
                  'default_fuel_cost_per_km', 'rent_amount', 'rent_frequency',
                  'default_depreciation_rate_per_km', 'is_pro', 'credits',
                  'ls_customer_id', 'ls_subscription_id', 'ls_current_period_end',
                  'platforms', 'platforms_details']
        read_only_fields = ['ls_customer_id', 'ls_subscription_id', 'ls_current_period_end', 'platforms_details']

    def update(self, instance, validated_data):
        # Handle M2M separately if needed, but ModelSerializer usually handles it if IDs are passed
        # We need to make sure we don't clear platforms if not provided?
        # Default behavior is fine: if 'platforms' key is missing, it won't touch it.
        # If key is present, it replaces.
        return super().update(instance, validated_data)

class WorkSessionSerializer(serializers.ModelSerializer):
    platform_name = serializers.ReadOnlyField(source='platform.name')
    
    class Meta:
        model = WorkSession
        fields = '__all__'
        read_only_fields = ('user', 'duration_hours', 'total_earnings', 'tax_estimate', 
                            'net_profit', 'application_fee', 'profit_per_hour', 'profit_per_km', 'profit_per_order')

    def create(self, validated_data):
        # Assign current user to session
        user = self.context['request'].user
        validated_data['user'] = user
        
        # TASK A: Backend enforcement - force fuel_cost=0 for non-fuel vehicles
        if hasattr(user, 'profile') and user.profile:
            transport_type = user.profile.transport_type.lower() if user.profile.transport_type else ''
            if transport_type in ['bicycle', 'scooter']:
                # Ignore any incoming fuel_cost for non-fuel vehicles
                validated_data['fuel_cost'] = 0
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        # TASK A: Backend enforcement - force fuel_cost=0 for non-fuel vehicles on update
        user = self.context['request'].user
        if hasattr(user, 'profile') and user.profile:
            transport_type = user.profile.transport_type.lower() if user.profile.transport_type else ''
            if transport_type in ['bicycle', 'scooter']:
                # Ignore any incoming fuel_cost for non-fuel vehicles
                validated_data['fuel_cost'] = 0
        
        return super().update(instance, validated_data)

class DashboardMetricsSerializer(serializers.Serializer):
    # Serializer for aggregated data, not a model
    total_net_profit = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_earnings = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_costs = serializers.DecimalField(max_digits=10, decimal_places=2)
    avg_profit_per_hour = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_duration_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    session_count = serializers.IntegerField()
