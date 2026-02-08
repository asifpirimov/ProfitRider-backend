from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    RegisterView, UserProfileView, BillingConfigView, WaitlistView, CountryListView, PlatformListView,
    WorkSessionViewSet, DashboardMetricsView, HealthCheckView
)
from . import lemonsqueezy_views
from .billing_endpoints import BillingPortalView, BillingStatusView, BillingInvoicesView

router = DefaultRouter()
router.register(r'sessions', WorkSessionViewSet, basename='worksession')

urlpatterns = [
    # Health Check
    path('health/', HealthCheckView.as_view(), name='health-check'),
    path('healthz', HealthCheckView.as_view(), name='healthz'),  # Standard health check endpoint
    
    # Auth - OAuth Only (Password auth disabled for security)
    # Password registration/login disabled - use Google/Apple OAuth
    # path('auth/register/', RegisterView.as_view(), name='register'),  # DISABLED
    # path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),  # DISABLED
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  # Still needed for JWT refresh
    
    # Profile & Billing Config
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('me/billing/', BillingConfigView.as_view(), name='billing-config'),
    
    # Waitlist (Public Beta)
    path('waitlist/', WaitlistView.as_view(), name='waitlist'),
    
    # Resources
    path('countries/', CountryListView.as_view(), name='countries'),
    path('platforms/', PlatformListView.as_view(), name='platforms'),
    
    # Dashboard
    path('dashboard/', DashboardMetricsView.as_view(), name='dashboard-metrics'),
    
    # Lemon Squeezy Billing Routes
    path('billing/create-checkout', lemonsqueezy_views.CreateCheckoutView.as_view(), name='ls-checkout'),
    path('billing/portal', lemonsqueezy_views.BillingPortalView.as_view(), name='ls-portal'),
    path('billing/webhook', lemonsqueezy_views.webhook, name='ls-webhook'),

    # Billing Endpoints (To be updated for Lemon Squeezy)
    path('billing/portal/', lemonsqueezy_views.BillingPortalView.as_view(), name='billing-portal'),
    path('billing/status/', BillingStatusView.as_view(), name='billing-status'),
    path('billing/invoices/', BillingInvoicesView.as_view(), name='billing-invoices'),
    
    # Legacy routes for backward compatibility (Cleaned up)
    
    # ViewSets
    path('', include(router.urls)),
]
# Trigger reload for new billing endpoints

