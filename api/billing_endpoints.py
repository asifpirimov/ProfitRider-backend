from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

class BillingPortalView(APIView):
    """
    Redirect to Lemon Squeezy Customer Portal.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        customer_id = user.profile.ls_customer_id
        
        if not customer_id:
             # If no customer ID, maybe they need to checkout first?
            return Response({'error': 'No active subscription found. Please subscribe first.'}, status=404)
            
        from .services.lemonsqueezy import LemonSqueezyService
        url = LemonSqueezyService.get_customer_portal_url(customer_id)
        if url:
             return Response({'url': url})
             
        return Response({'error': 'Could not retrieve portal URL'}, status=500)


class BillingStatusView(APIView):
    """
    Placeholder for Billing Status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
             profile = request.user.profile
        except:
             from .models import UserProfile
             profile, created = UserProfile.objects.get_or_create(user=request.user)
        
        from django.conf import settings
        
        from .services.lemonsqueezy import LemonSqueezyService
        from dateutil import parser
        
        # 1. Try to fetch fresh data from Lemon Squeezy
        sub_data = None
        if profile.ls_subscription_id:
            sub_data = LemonSqueezyService.get_subscription(profile.ls_subscription_id)
        
        # Fallback: If no ID or fetch failed, try by email
        if not sub_data:
             sub_data = LemonSqueezyService.get_subscription_by_email(request.user.email)
             if sub_data:
                 profile.ls_subscription_id = sub_data.get('id')
                 profile.ls_customer_id = str(sub_data.get('attributes', {}).get('customer_id')) # Also save customer ID

        if sub_data:
             attrs = sub_data.get('attributes', {})
             # Update local profile with source of truth
             profile.ls_status = attrs.get('status')
             profile.ls_variant_id = str(attrs.get('variant_id'))
             profile.ls_card_brand = attrs.get('card_brand')
             profile.ls_card_last4 = attrs.get('card_last_four')
             if attrs.get('renews_at'):
                 profile.ls_current_period_end = parser.parse(attrs.get('renews_at'))
             profile.is_pro = profile.ls_status in ['active', 'on_trial', 'past_due']
             profile.save()
        
        if profile.is_pro:
            plan_name = 'Starter' # Default
            amount = '€3.99'
            interval = 'month'
            
            vid = str(profile.ls_variant_id)
            logger.info(f"BillingStatus: Checking variant_id {vid} against settings.")
            logger.info(f"Starter Monthly: {settings.LEMONSQUEEZY_VARIANT_ID_STARTER_MONTHLY}")
            logger.info(f"Starter Yearly: {settings.LEMONSQUEEZY_VARIANT_ID_STARTER_YEARLY}")
            
            if vid == str(settings.LEMONSQUEEZY_VARIANT_ID_STARTER_MONTHLY):
                plan_name = 'Starter'
                amount = '€3.99'
                interval = 'month'
            elif vid == str(settings.LEMONSQUEEZY_VARIANT_ID_STARTER_YEARLY):
                plan_name = 'Starter'
                amount = '€29.00'
                interval = 'year'
            elif vid == str(settings.LEMONSQUEEZY_VARIANT_ID_PRO_YEARLY):
                plan_name = 'Pro'
                amount = '€59.00'
                interval = 'year'
            elif vid == str(settings.LEMONSQUEEZY_VARIANT_ID_PRO_MONTHLY):
                 plan_name = 'Pro'
                 amount = '€7.99'
                 interval = 'month'
            else:
                 logger.warning(f"BillingStatus: Unknown variant_id {vid}. Defaulting to Starter Monthly display but this might be wrong.")

            # Determine status for frontend badge
            status_display = 'active'
            if profile.ls_status == 'on_trial':
                status_display = 'trial'
            elif profile.ls_status:
                status_display = profile.ls_status
            
            # Construct payment method string
            payment_method = None
            if profile.ls_card_brand and profile.ls_card_last4:
                payment_method = f"{profile.ls_card_brand.title()} •••• {profile.ls_card_last4}"
                
            return Response({
                'plan_name': plan_name,
                'status': status_display,
                'amount': amount,
                'interval': interval,
                'has_active_subscription': True,
                'next_billing_date': profile.ls_current_period_end.timestamp() if profile.ls_current_period_end else None,
                'cancel_at_period_end': profile.ls_status == 'cancelled',
                'payment_method': payment_method,
                'manageable': bool(profile.ls_customer_id)
            })
        
        return Response({
            'plan_name': None,
            'status': 'inactive',
            'has_active_subscription': False,
        })


class BillingInvoicesView(APIView):
    """
    Placeholder for Invoices.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
            if not profile.ls_subscription_id:
                return Response({'invoices': []})
                
            from .services.lemonsqueezy import LemonSqueezyService
            from dateutil import parser
            
            ls_invoices = LemonSqueezyService.get_subscription_invoices(profile.ls_subscription_id)
            
            invoices = []
            for invoice in ls_invoices:
                attrs = invoice.get('attributes', {})
                invoices.append({
                    'invoice_id': invoice.get('id'),
                    'created': parser.parse(attrs.get('created_at')).timestamp(),
                    'amount_paid': float(attrs.get('total', 0)) / 100.0,
                    'currency': attrs.get('currency', 'EUR'),
                    'status': attrs.get('status'),
                    'hosted_invoice_url': attrs.get('urls', {}).get('invoice_url'),
                    'invoice_pdf': None
                })
                
            return Response({'invoices': invoices})
            
        except Exception as e:
            logger.error(f"Error fetching invoices: {e}")
            return Response({'error': 'Failed to fetch invoices'}, status=500)
