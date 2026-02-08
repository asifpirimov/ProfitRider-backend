from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth.models import User
from django.db.models import Sum, Avg, Count, F, Q
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import datetime, timedelta, date
from decouple import config
# Note: Rate limiting temporarily disabled due to package compatibility
# from ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from rest_framework.exceptions import APIException
from django.db import transaction
from django.db.models import F

class CreditsExhausted(APIException):
    status_code = 402
    default_detail = 'You have used all your free credits. Upgrade to continue tracking.'
    default_code = 'CREDITS_EXHAUSTED'

from .models import Country, Platform, UserProfile, WorkSession
from .serializers import (
    CountrySerializer, PlatformSerializer, UserProfileSerializer, 
    WorkSessionSerializer, UserSerializer, DashboardMetricsSerializer
)
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
import sys


class HealthCheckView(APIView):
    """
    Health check endpoint for monitoring and deployment verification.
    Returns 200 OK with basic system information.
    No authentication required.
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        return Response({
            'status': 'healthy',
            'service': 'ProfitRider API',
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'debug': config('DEBUG', default=False, cast=bool),
        }, status=status.HTTP_200_OK)

# DISABLED FOR PRODUCTION: OAuth-only authentication enforced
# Password-based registration is no longer supported for security reasons
class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # OAuth-only authentication - password registration disabled
        return Response({
            'error': 'Password registration is disabled. Please use Google or Apple Sign-In for secure authentication.',
            'oauth_providers': ['google', 'apple']
        }, status=status.HTTP_403_FORBIDDEN)
    
    # LEGACY CODE - KEPT FOR REFERENCE IF NEEDED TO RE-ENABLE
    # def post(self, request):
    #     username = request.data.get('username')
    #     password = request.data.get('password')
    #     email = request.data.get('email')
    #     
    #     if not username or not password:
    #         return Response({'error': 'Username and password required'}, status=status.HTTP_400_BAD_REQUEST)
    #     
    #     # Email validation
    #     if not email:
    #         return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
    #     
    #     try:
    #         validate_email(email)
    #     except ValidationError:
    #         return Response({'error': 'Invalid email format'}, status=status.HTTP_400_BAD_REQUEST)
    #     
    #     if User.objects.filter(username=username).exists():
    #         return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)
    #     
    #     if User.objects.filter(email=email).exists():
    #         return Response({'error': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)
    #         
    #     user = User.objects.create_user(username=username, password=password, email=email)
    #     # UserProfile is automatically created by post_save signal in signals.py
    #     
    #     return Response({'message': 'User registered successfully'}, status=status.HTTP_201_CREATED)

class UserProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BillingConfigView(APIView):
    """
    Returns billing configuration and current plan status for the authenticated user.
    Used by frontend to determine what billing UI to show.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        
        # Determine plan type
        plan = 'pro' if profile.is_pro else 'starter_beta'
        
        # Get subscription status
        subscription_status = 'active' if profile.is_pro else 'none'
        
        return Response({
            'billing_enabled': config('BILLING_ENABLED', default=False, cast=bool),
            'plan': plan,
            'plan_display': 'Pro' if profile.is_pro else 'Starter (Free Beta)',
            'credits_remaining': profile.credits,
            'credits_total': 300,
            'is_pro': profile.is_pro,
            'subscription_status': subscription_status,
            'subscription_ends_at': None  # Will be populated when subscriptions are active
        })

class WaitlistView(APIView):
    """
    Handles waitlist signups for paid plans during public beta.
    POST /api/waitlist/ - Add email to waitlist
    """
    permission_classes = [permissions.AllowAny]  # Public endpoint

    def post(self, request):
        from .serializers_waitlist import WaitlistSerializer
        
        serializer = WaitlistSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Successfully added to waitlist! We\'ll notify you when paid plans launch.'
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

class CountryListView(generics.ListAPIView):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    permission_classes = [permissions.AllowAny]

class SessionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class PlatformListView(generics.ListCreateAPIView):
    queryset = Platform.objects.all()
    serializer_class = PlatformSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        queryset = Platform.objects.all()
        country_id = self.request.query_params.get('country', None)
        if country_id:
            queryset = queryset.filter(country_id=country_id)
        return queryset

class WorkSessionViewSet(viewsets.ModelViewSet):
    serializer_class = WorkSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SessionPagination

    def get_queryset(self):
        return WorkSession.objects.filter(user=self.request.user)\
            .select_related('platform', 'user__profile__country')\
            .order_by('-date', '-start_time')

    def perform_create(self, serializer):
        user = self.request.user
        # Credit logic
        if not hasattr(user, 'profile'):
            UserProfile.objects.create(user=user) # Should exist via signal, but safety check

        # Check if user is PRO or STARTER (paid)
        # We check is_pro OR if they have an active plan (simple check on is_pro for now as it's the gate)
        if not user.profile.is_pro:
            # Check credits
            if user.profile.credits < 10:
                raise CreditsExhausted()
            
            # Atomic deduction
            with transaction.atomic():
                # Re-fetch to lock? Or just atomic update
                # Since we are just decrementing, F() is safe for race conditions on value
                # But we checked value above which is a race. 
                # Ideally: select_for_update.
                profile = UserProfile.objects.select_for_update().get(user=user)
                if profile.credits < 10:
                     raise CreditsExhausted()
                
                profile.credits = F('credits') - 10
                profile.save()
                
                # Refresh to get clean value if needed, but F expression is DB side
                # profile.refresh_from_db()

        serializer.save(user=user)

class DashboardMetricsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        period = request.query_params.get('period', 'today') # today, week, month, all
        local_date_str = request.query_params.get('local_date')
        user = request.user
        
        # Determine "today" based on client's local time if provided
        if local_date_str:
            try:
                today = datetime.strptime(local_date_str, '%Y-%m-%d').date()
            except ValueError:
                today = date.today()
        else:
            today = date.today()

        queryset = WorkSession.objects.filter(user=user)
        
        if period == 'today':
            queryset = queryset.filter(date=today)
        elif period == 'week':
            # Start of week (Monday) relative to the client's "today"
            start_date = today - timedelta(days=today.weekday()) 
            # We want to show the whole week including future days (if any sessions logged ahead) or just up to today?
            # Standard is usually start_date onwards.
            # But we also might want to end at end of week? Let's just filter >= start_date for now.
            # Actually, let's limit to the current week window (Mon-Sun).
            end_date = start_date + timedelta(days=6)
            queryset = queryset.filter(date__range=[start_date, end_date])
        elif period == 'month':
            queryset = queryset.filter(date__year=today.year, date__month=today.month)
            
        # Aggregation
        metrics = queryset.aggregate(
            total_net_profit=Sum('net_profit'),
            total_earnings=Sum('total_earnings'),
            total_fuel=Sum('fuel_cost'),
            total_rent=Sum('vehicle_rent'),
            total_depreciation=Sum('depreciation_cost'),
            total_other=Sum('other_expenses'),
            total_fees=Sum('platform_fees'),
            total_duration=Sum('duration_hours'),
            total_dist=Sum('total_distance_km'),
            count=Count('id')
        )
        
        # Calculate total costs properly
        total_costs = (
            (metrics['total_fuel'] or Decimal(0)) +
            (metrics['total_rent'] or Decimal(0)) +
            (metrics['total_depreciation'] or Decimal(0)) +
            (metrics['total_other'] or Decimal(0)) +
            (metrics['total_fees'] or Decimal(0))
        )
        
        # Chart Data (Daily breakdown)
        chart_data_qs = queryset.values('date').annotate(
            profit=Sum('net_profit'),
            earnings=Sum('total_earnings'),
            # Calculate total costs for chart: earnings - profit (simplified) or sum components
            costs=Sum('total_earnings') - Sum('net_profit') 
        ).order_by('date')
        
        chart_data = []
        for item in chart_data_qs:
            chart_data.append({
                'date': item['date'].strftime('%a, %d'), # Mon, 01 or yyyy-mm-dd
                'full_date': item['date'].isoformat(),
                'profit': item['profit'],
                'earnings': item['earnings'],
                'costs': item['costs']
            })

        total_profit = metrics['total_net_profit'] or Decimal(0)
        total_duration = metrics['total_duration'] or Decimal(0)
        total_dist = metrics['total_dist'] or Decimal(0)
        
        # Recent Sessions (Top 5) - optimized with select_related
        recent_qs = WorkSession.objects.filter(user=user)\
            .select_related('platform')\
            .order_by('-date', '-start_time')[:5]
        recent_sessions = WorkSessionSerializer(recent_qs, many=True).data

        data = {
            'total_net_profit': total_profit,
            'total_earnings': metrics['total_earnings'] or Decimal(0),
            'total_costs': total_costs,
            'avg_profit_per_hour': (total_profit / total_duration) if total_duration > 0 else 0,
            'total_duration_hours': total_duration,
            'total_distance_km': total_dist,
            'session_count': metrics['count'],
            'chart_data': chart_data,
            'recent_sessions': recent_sessions
        }
        
        return Response(data)

# Health Check Endpoint
class HealthCheckView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        return Response({
            'status': 'healthy',
            'service': 'ProfitRider API',
            'timestamp': datetime.now().isoformat()
        }, status=status.HTTP_200_OK)

class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = config('GOOGLE_OAUTH_REDIRECT_URI', default='http://localhost:5173')
    client_class = OAuth2Client
