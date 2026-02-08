from django.db import models
from django.contrib.auth.models import User
from django.core.validators import EmailValidator
from django.db.models import Sum, Avg
from decimal import Decimal

from .models_webhook import WebhookEvent
class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    currency_symbol = models.CharField(max_length=5)
    tax_rate_percentage = models.DecimalField(max_digits=5, decimal_places=2, help_text="Default tax rate for this country")
    distance_unit = models.CharField(max_length=2, choices=[('km', 'Kilometers'), ('mi', 'Miles')], default='km')

    class Meta:
        verbose_name_plural = "Countries"

    def __str__(self):
        return self.name

class Platform(models.Model):
    name = models.CharField(max_length=100)
    base_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='platforms')

    def __str__(self):
        return f"{self.name} ({self.country.name})"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True)
    transport_type = models.CharField(max_length=50, choices=[('bicycle', 'Bicycle'), ('motorcycle', 'Motorcycle'), ('car', 'Car'), ('scooter', 'Electric Scooter')], default='car')
    
    # Courier Type / Fee Settings
    COURIER_TYPE_CHOICES = [
        ('SOLOPRENEUR', 'Solopreneur'),
        ('FLEET_COMPANY', 'Fleet / Company')
    ]
    courier_type = models.CharField(max_length=20, choices=COURIER_TYPE_CHOICES, default='FLEET_COMPANY')
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.0, help_text="Application fee percentage for Fleet/Company")
    
    # Credits / Usage Limits
    credits = models.IntegerField(default=300, help_text="Remaining session credits")

    # Cost Presets (defaults if not overridden per session)
    default_fuel_cost_per_km = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    
    # Availability / Working Hours Defaults
    default_start_time = models.TimeField(null=True, blank=True, help_text="Default start time for sessions")
    default_end_time = models.TimeField(null=True, blank=True, help_text="Default end time for sessions")
    
    RENT_FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly')
    ]
    rent_frequency = models.CharField(max_length=10, choices=RENT_FREQUENCY_CHOICES, default='daily')
    rent_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="Rent amount for the specified frequency")
    
    default_depreciation_rate_per_km = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    
    # Lemon Squeezy Billing
    ls_customer_id = models.CharField(max_length=255, blank=True, null=True)
    ls_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    ls_variant_id = models.CharField(max_length=255, blank=True, null=True)  # To track Plan Type
    ls_current_period_end = models.DateTimeField(blank=True, null=True)
    
    # Plan Details (Derived from Variant)
    ls_plan_name = models.CharField(max_length=50, default='starter', help_text="starter | pro")
    ls_billing_interval = models.CharField(max_length=20, default='monthly', help_text="monthly | yearly")
    
    # Enhanced Billing Info
    ls_card_brand = models.CharField(max_length=20, blank=True, null=True)
    ls_card_last4 = models.CharField(max_length=4, blank=True, null=True)
    ls_status = models.CharField(max_length=20, default='inactive') # active, on_trial, cancelled, expired, past_due
    
    # Generic Pro Status
    is_pro = models.BooleanField(default=False)

    # Platforms (My Platforms)
    platforms = models.ManyToManyField(Platform, blank=True, related_name='users', help_text="Platforms enabled for this user")

    def __str__(self):
        return self.user.username

class WorkSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    platform = models.ForeignKey(Platform, on_delete=models.SET_NULL, null=True)
    webhook_event = models.ForeignKey(WebhookEvent, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration_hours = models.DecimalField(max_digits=5, decimal_places=2, editable=False) # Computed
    
    total_orders = models.IntegerField(default=0)
    total_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Financials (Input)
    gross_earnings = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    tips = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    
    # Costs (Input/Calculated)
    fuel_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    vehicle_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    depreciation_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    other_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    
    # Computed Financials
    application_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="Calculated application fee based on courier type")
    total_earnings = models.DecimalField(max_digits=10, decimal_places=2, editable=False) # gross + tips
    platform_fees = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="Fees charged by the delivery platform") 
    tax_estimate = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    net_profit = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    
    # Computed KPIs
    profit_per_hour = models.DecimalField(max_digits=10, decimal_places=2, editable=False, null=True)
    profit_per_km = models.DecimalField(max_digits=10, decimal_places=2, editable=False, null=True)
    profit_per_order = models.DecimalField(max_digits=10, decimal_places=2, editable=False, null=True)

    def save(self, *args, **kwargs):
        # Calculate duration
        if self.start_time and self.end_time:
            from datetime import datetime, date, timedelta
            dummy_date = date.min
            start = datetime.combine(dummy_date, self.start_time)
            end = datetime.combine(dummy_date, self.end_time)
            if end < start:
                end += timedelta(days=1)
            diff = end - start
            # Decimal conversion for precision
            self.duration_hours = Decimal(diff.total_seconds() / 3600)

        # Ensure decimals
        self.gross_earnings = Decimal(str(self.gross_earnings))
        self.tips = Decimal(str(self.tips))
        self.fuel_cost = Decimal(str(self.fuel_cost))
        # vehicle_rent is calculated below, ignore input if we are automating
        
        self.depreciation_cost = Decimal(str(self.depreciation_cost))
        self.other_expenses = Decimal(str(self.other_expenses))
        self.platform_fees = Decimal(str(self.platform_fees))
        self.total_distance_km = Decimal(str(self.total_distance_km))

        # Automated Rent Calculation
        try:
            if self.user.profile:
                profile = self.user.profile
                daily_cost = Decimal('0.00')
                amount = profile.rent_amount
                freq = profile.rent_frequency
                
                if freq == 'daily':
                    daily_cost = amount
                elif freq == 'weekly':
                    daily_cost = amount / Decimal('7.0')
                elif freq == 'monthly':
                    # Use actual days in month for accuracy
                    import calendar
                    year = self.date.year
                    month = self.date.month
                    days_in_month = calendar.monthrange(year, month)[1]
                    daily_cost = amount / Decimal(str(days_in_month))
                
                # Check if this is the first session of the day
                # We need to exclude self if updating
                existing_sessions = WorkSession.objects.filter(user=self.user, date=self.date)
                if self.pk:
                    existing_sessions = existing_sessions.exclude(pk=self.pk)
                
                if not existing_sessions.exists():
                    self.vehicle_rent = daily_cost
                else:
                    self.vehicle_rent = Decimal('0.00')
        except Exception:
            # Fallback if profile issue
            pass
        
        # Calculate Application Fee
        try:
            if self.user.profile:
                if self.user.profile.courier_type == 'SOLOPRENEUR':
                    self.application_fee = Decimal('0.00')
                else:
                    # FLEET_COMPANY (or existing default)
                    # Fee % from profile
                    fee_pct = self.user.profile.fee_percent
                    self.application_fee = self.gross_earnings * (fee_pct / Decimal('100.0'))
            else:
                self.application_fee = Decimal('0.00')
        except Exception:
            self.application_fee = Decimal('0.00')

        # Calculate Computed Financials
        self.total_earnings = self.gross_earnings + self.tips
        
        # Add application_fee to total costs
        total_costs = self.fuel_cost + self.vehicle_rent + self.depreciation_cost + self.other_expenses + self.platform_fees + self.application_fee
        
        # Tax Estimate
        tax_rate = Decimal('0.00')
        # Check if user has profile and country
        try:
            if self.user.profile and self.user.profile.country:
                tax_rate = self.user.profile.country.tax_rate_percentage / Decimal('100')
        except:
             # Handle case where profile might not be linked yet or accessible
             pass
        
        pre_tax_profit = self.total_earnings - total_costs
        self.tax_estimate = pre_tax_profit * tax_rate if pre_tax_profit > 0 else Decimal('0.00')
        
        self.net_profit = pre_tax_profit - self.tax_estimate

        # KPIs
        if self.duration_hours and self.duration_hours > 0:
            self.profit_per_hour = self.net_profit / self.duration_hours
        else:
            self.profit_per_hour = Decimal('0.00')
            
        if self.total_distance_km and self.total_distance_km > 0:
            self.profit_per_km = self.net_profit / self.total_distance_km
        else:
            self.profit_per_km = Decimal('0.00')
            
        if self.total_orders and self.total_orders > 0:
            self.profit_per_order = self.net_profit / Decimal(self.total_orders)
        else:
            self.profit_per_order = Decimal('0.00')

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.date}"


class Waitlist(models.Model):
    """
    Stores email addresses of users interested in paid plans.
    Used during public beta to collect waitlist signups.
    """
    email = models.EmailField(unique=True, validators=[EmailValidator()])
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=50, default='subscription_page', help_text="Where the signup came from")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Waitlist Entry'
        verbose_name_plural = 'Waitlist Entries'
    
    def __str__(self):
        return f"{self.email} ({self.created_at.strftime('%Y-%m-%d')})"
