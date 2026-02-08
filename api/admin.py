from django.contrib import admin
from .models import Country, Platform, UserProfile, WorkSession

@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('name', 'currency_symbol', 'tax_rate_percentage')

@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'base_fee_percentage')
    list_filter = ('country',)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'country', 'transport_type')

@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'net_profit', 'profit_per_hour', 'duration_hours')
    list_filter = ('user', 'date', 'platform')
