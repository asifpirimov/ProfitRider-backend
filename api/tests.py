from django.test import TestCase
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date, time
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from .models import Country, Platform, UserProfile, WorkSession
from django.conf import settings

class ProfitCalculationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        
        self.country = Country.objects.create(
            name='TestLand', 
            currency_symbol='$', 
            tax_rate_percentage=10.00
        )
        
        # UserProfile is automatically created by signal
        # Just update it with test data
        profile = self.user.profile
        profile.country = self.country
        profile.transport_type = 'car'
        profile.default_fuel_cost_per_km = Decimal('0.10')
        profile.default_depreciation_rate_per_km = Decimal('0.05')
        profile.save()
        
        self.platform = Platform.objects.create(
            name='TestEats',
            country=self.country,
            base_fee_percentage=0.00
        )

    def test_profit_calculation(self):
        session = WorkSession.objects.create(
            user=self.user,
            platform=self.platform,
            date=date.today(),
            start_time=time(18, 0),
            end_time=time(20, 0), # 2 hours
            total_distance_km=Decimal('20.0'),
            gross_earnings=Decimal('100.00'),
            tips=Decimal('10.00'),
            fuel_cost=Decimal('5.00'),
            maintenance_cost=Decimal('2.00')
        )
        
        # Check computed fields
        self.assertEqual(session.duration_hours, Decimal('2.00'))
        self.assertEqual(session.total_earnings, Decimal('110.00')) # 100 + 10
        
        # Costs = 5 + 2 = 7
        # Pre-tax profit = 110 - 7 = 103
        # Tax (10%) = 10.30
        # Net Profit = 103 - 10.30 = 92.70
        
        self.assertEqual(session.net_profit, Decimal('92.70'))
        
        # KPIs
        # Profit per hour = 92.70 / 2 = 46.35
        self.assertEqual(session.profit_per_hour, Decimal('46.35'))
        
    def test_cross_day_duration(self):
        session = WorkSession.objects.create(
            user=self.user,
            date=date.today(),
            start_time=time(23, 0),
            end_time=time(1, 0)
        )
        self.assertEqual(session.duration_hours, Decimal('2.00'))

class APIEndpointsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='apiuser', password='password')
        self.client.force_login(self.user)
        
    def test_dashboard_access(self):
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_net_profit', response.data)


class RegistrationRegressionTests(TestCase):
    """
    Regression tests for the duplicate UserProfile creation bug.
    Ensures registration creates exactly one UserProfile and returns 201.
    """
    
    def test_registration_creates_single_profile(self):
        """
        Test that registering a new user creates exactly ONE UserProfile.
        This prevents the duplicate creation bug that caused 500 errors.
        """
        registration_data = {
            'username': 'testuser_regression',
            'email': 'regression@example.com',
            'password': 'SecurePass123!'
        }
        
        response = self.client.post('/api/auth/register/', registration_data)
        
        # Assert - Registration succeeds
        self.assertEqual(response.status_code, 201, 
                        f"Registration failed: {response.data}")
        self.assertEqual(response.data['message'], 'User registered successfully')
        
        # Assert - User exists
        user = User.objects.get(username='testuser_regression')
        self.assertIsNotNone(user)
        
        # Assert - EXACTLY ONE UserProfile exists
        profile_count = UserProfile.objects.filter(user=user).count()
        self.assertEqual(profile_count, 1, 
                        f"Expected 1 UserProfile, found {profile_count}. Duplicate creation bug!")
        
        # Assert - Profile is accessible
        self.assertIsNotNone(user.profile)
        self.assertEqual(user.profile.user, user)
    
    def test_registration_no_500_error(self):
        """
        Test that registration does not return 500 Internal Server Error.
        This was the symptom of the duplicate UserProfile creation bug.
        """
        registration_data = {
            'username': 'testuser_no500',
            'email': 'no500@example.com',
            'password': 'SecurePass123!'
        }
        
        response = self.client.post('/api/auth/register/', registration_data)
        
        # Should NOT be 500
        self.assertNotEqual(response.status_code, 500,
                           "Registration returned 500 - duplicate UserProfile bug!")
        
        # Should be 201 Created
        self.assertEqual(response.status_code, 201)
    
    def test_multiple_registrations_independent(self):
        """
        Test that multiple user registrations each create their own profile.
        Ensures the fix doesn't break normal operation.
        """
        users_data = [
            {'username': 'user1', 'email': 'user1@example.com', 'password': 'Pass123!'},
            {'username': 'user2', 'email': 'user2@example.com', 'password': 'Pass123!'},
            {'username': 'user3', 'email': 'user3@example.com', 'password': 'Pass123!'},
        ]
        
        for user_data in users_data:
            response = self.client.post('/api/auth/register/', user_data)
            self.assertEqual(response.status_code, 201)
        
        # Verify total counts
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(UserProfile.objects.count(), 3)
        
        # Verify each user has exactly one profile
        for user_data in users_data:
            user = User.objects.get(username=user_data['username'])
            self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)


class FuelCostEnforcementTests(TestCase):
    """
    TASK A: Regression tests for backend enforcement of fuel_cost=0 for non-fuel vehicles.
    Ensures bicycle/scooter users cannot submit non-zero fuel costs.
    """
    
    def setUp(self):
        # Create user with bicycle transport type
        self.user = User.objects.create_user(username='bicycleuser', password='password')
        self.country = Country.objects.create(
            name='TestCountry',
            currency_symbol='$',
            tax_rate_percentage=10.00
        )
        self.platform = Platform.objects.create(
            name='TestPlatform',
            country=self.country,
            base_fee_percentage=0.00
        )
        
        # Set user profile to bicycle
        profile = self.user.profile
        profile.country = self.country
        profile.transport_type = 'bicycle'
        profile.save()
        
        # Use REST framework's APIClient with force_authenticate
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_bicycle_user_cannot_submit_nonzero_fuel_cost(self):
        """
        Test that bicycle users have fuel_cost forced to 0 even if they try to submit non-zero value.
        """
        session_data = {
            'platform': self.platform.id,
            'date': date.today().isoformat(),
            'start_time': '18:00:00',
            'end_time': '20:00:00',
            'total_distance_km': '10.0',
            'gross_earnings': '50.00',
            'tips': '5.00',
            'fuel_cost': '10.00',  # Attempting to submit non-zero fuel cost
            'maintenance_cost': '0.00',
            'other_costs': '0.00',
            'number_of_orders': 5
        }
        
        response = self.client.post('/api/sessions/', session_data)
        
        # Assert - Session created successfully
        self.assertEqual(response.status_code, 201)
        
        # Assert - fuel_cost was forced to 0 by backend
        session = WorkSession.objects.get(id=response.data['id'])
        self.assertEqual(session.fuel_cost, Decimal('0.00'), 
                        "Bicycle user's fuel_cost should be forced to 0 by backend")
    
    def test_scooter_user_fuel_cost_enforcement(self):
        """
        Test that scooter users also have fuel_cost forced to 0.
        """
        # Change transport type to scooter
        profile = self.user.profile
        profile.transport_type = 'scooter'
        profile.save()
        
        session_data = {
            'platform': self.platform.id,
            'date': date.today().isoformat(),
            'start_time': '18:00:00',
            'end_time': '20:00:00',
            'total_distance_km': '15.0',
            'gross_earnings': '60.00',
            'tips': '0.00',
            'fuel_cost': '20.00',  # Attempting to submit non-zero fuel cost
            'maintenance_cost': '0.00',
            'other_costs': '0.00',
            'number_of_orders': 8
        }
        
        response = self.client.post('/api/sessions/', session_data)
        
        # Assert - Session created successfully
        self.assertEqual(response.status_code, 201)
        
        # Assert - fuel_cost was forced to 0 by backend
        session = WorkSession.objects.get(id=response.data['id'])
        self.assertEqual(session.fuel_cost, Decimal('0.00'),
                        "Scooter user's fuel_cost should be forced to 0 by backend")
    
    def test_motorcycle_user_can_submit_fuel_cost(self):
        """
        Test that motorcycle users CAN submit non-zero fuel costs (control test).
        """
        # Change transport type to motorcycle
        profile = self.user.profile
        profile.transport_type = 'motorcycle'
        profile.save()
        
        session_data = {
            'platform': self.platform.id,
            'date': date.today().isoformat(),
            'start_time': '18:00:00',
            'end_time': '20:00:00',
            'total_distance_km': '25.0',
            'gross_earnings': '80.00',
            'tips': '10.00',
            'fuel_cost': '15.00',  # Should be allowed for motorcycle
            'maintenance_cost': '0.00',
            'other_costs': '0.00',
            'number_of_orders': 10
        }
        
        response = self.client.post('/api/sessions/', session_data)
        
        # Assert - Session created successfully
        self.assertEqual(response.status_code, 201)
        
        # Assert - fuel_cost was NOT modified (motorcycle can have fuel costs)
        session = WorkSession.objects.get(id=response.data['id'])
        self.assertEqual(session.fuel_cost, Decimal('15.00'),
                        "Motorcycle user's fuel_cost should be preserved")


class LemonSqueezyWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ls_user', email='ls@example.com', password='password')
        # Profile created by signal
        
    @patch('api.services.lemonsqueezy.LemonSqueezyService.verify_webhook')
    def test_webhook_subscription_created(self, mock_verify):
        mock_verify.return_value = True
        
        payload = {
            "meta": {
                "event_name": "subscription_created",
                "custom_data": {"user_id": self.user.id}
            },
            "data": {
                "id": "sub_123",
                "attributes": {
                    "customer_id": "cust_123",
                    "variant_id": "111", # Mock variant
                    "status": "active",
                    "card_brand": "visa",
                    "card_last4": "4242",
                    "renews_at": "2026-12-31T23:59:59Z"
                }
            }
        }
        
        # Mock settings
        with self.settings(
            LEMONSQUEEZY_VARIANT_ID_STARTER_MONTHLY='111',
            LEMONSQUEEZY_WEBHOOK_SECRET='secret'
        ):
            response = self.client.post('/api/lemonsqueezy/webhook', payload, format='json')
            self.assertEqual(response.status_code, 200)
            
            self.user.profile.refresh_from_db()
            self.assertTrue(self.user.profile.is_pro)
            self.assertEqual(self.user.profile.ls_plan_name, 'starter')
            self.assertEqual(self.user.profile.ls_billing_interval, 'monthly')
            self.assertEqual(self.user.profile.ls_status, 'active')