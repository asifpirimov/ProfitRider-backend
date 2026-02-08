from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from .services.lemonsqueezy import LemonSqueezyService
from .models import WebhookEvent
import logging
from dateutil import parser  # Requires python-dateutil
import requests

logger = logging.getLogger(__name__)

class CreateCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            # Frontend sends 'plan_type' but for LS we just need the variant ID
            # In Phase 1 we only have one variant? PRO_YEARLY
            # But let's check input
            plan_type = request.data.get('plan_type', 'yearly')
            
            variant_id = None
            if plan_type == 'monthly':
                 variant_id = settings.LEMONSQUEEZY_VARIANT_ID_STARTER_MONTHLY
            elif plan_type == 'yearly':
                 variant_id = settings.LEMONSQUEEZY_VARIANT_ID_STARTER_YEARLY
                 
            if not variant_id:
                return Response({'error': f'Configuration missing for plan: {plan_type}'}, status=500)
            
            # Pass success redirect URL
            redirect_url = f"{settings.FRONTEND_URL}/billing/success"
            checkout_url = LemonSqueezyService.create_checkout(user, variant_id, redirect_url=redirect_url)
            return Response({'url': checkout_url})
            
        except Exception as e:
            logger.error(f"Error creating checkout: {str(e)}", exc_info=True)
            # Handle specific Lemon Squeezy errors (like Store Under Review -> 403)
            if isinstance(e, requests.exceptions.RequestException) and e.response and e.response.status_code == 403:
                 return Response({
                     'error': 'Payments are temporarily unavailable while our store is being reviewed. Please try again soon.',
                     'code': 'STORE_UNDER_REVIEW'
                 }, status=503)
            
            return Response({'error': 'Failed to create checkout'}, status=500)

class BillingPortalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        customer_id = user.profile.ls_customer_id
        
        if not customer_id:
            return Response({'error': 'No active subscription found'}, status=404)
            
        url = LemonSqueezyService.get_customer_portal_url(customer_id)
        if url:
            return Response({'url': url})
        else:
            return Response({'error': 'Could not retrieve portal URL'}, status=500)

@api_view(['POST'])
@permission_classes([AllowAny])
def webhook(request):
    if not LemonSqueezyService.verify_webhook(request):
        return Response({'error': 'Invalid signature'}, status=401)

    # Idempotency Check
    event_id = request.META.get('HTTP_X_EVENT_ID')
    if event_id:
        if WebhookEvent.objects.filter(event_id=event_id).exists():
            logger.info(f"Webhook event {event_id} already processed. Skipping.")
            return Response({'status': 'ok'})
        
        # Record event
        try:
            WebhookEvent.objects.create(event_id=event_id)
        except Exception:
            # Race condition handling
            return Response({'status': 'ok'})

    try:
        data = request.data
        event_name = data.get('meta', {}).get('event_name')
        payload = data.get('data', {})
        attributes = payload.get('attributes', {})
        
        # Meta dictionary often contains custom_data
        meta = data.get('meta', {})
        custom = meta.get('custom_data', {})
        user_id = custom.get('user_id')
        
        # Fallback: finding by email (less reliable if email changed)
        email = data.get('data', {}).get('attributes', {}).get('user_email')
        
        user = None
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                pass
        
        if not user and email:
             try:
                user = User.objects.get(email=email)
             except User.DoesNotExist:
                 pass
                 
        if not user:
             logger.warning(f"Webhook {event_name}: No matching user found.")
             return Response({'status': 'ok'}) # Don't retry if user undefined
        
        profile = user.profile
        
        if event_name in ['subscription_created', 'subscription_updated', 'subscription_payment_success']:
             profile.is_pro = True
             profile.ls_customer_id = attributes.get('customer_id')
             # subscription_id is the ID of the data object
             profile.ls_subscription_id = payload.get('id')
             profile.ls_subscription_id = payload.get('id')
             profile.ls_variant_id = attributes.get('variant_id')

             # Map variant to plan details
             variant_id = str(profile.ls_variant_id)
             if variant_id == str(settings.LEMONSQUEEZY_VARIANT_ID_STARTER_MONTHLY):
                 profile.ls_plan_name = 'starter'
                 profile.ls_billing_interval = 'monthly'
             elif variant_id == str(settings.LEMONSQUEEZY_VARIANT_ID_STARTER_YEARLY):
                 profile.ls_plan_name = 'starter'
                 profile.ls_billing_interval = 'yearly'
             elif variant_id == str(settings.LEMONSQUEEZY_VARIANT_ID_PRO_YEARLY):
                 profile.ls_plan_name = 'pro'
                 profile.ls_billing_interval = 'yearly'
             elif variant_id == str(settings.LEMONSQUEEZY_VARIANT_ID_PRO_MONTHLY):
                 profile.ls_plan_name = 'pro'
                 profile.ls_billing_interval = 'monthly'

             profile.ls_status = attributes.get('status', 'active')
             profile.ls_card_brand = attributes.get('card_brand')
             profile.ls_card_last4 = attributes.get('card_last4')
             
             renews_at = attributes.get('renews_at')
             if renews_at:
                 profile.ls_current_period_end = parser.parse(renews_at)
             
             profile.save()
             logger.info(f"User {user.id} subscription active/updated.")
             
        elif event_name in ['subscription_cancelled', 'subscription_expired']:
             status = attributes.get('status')
             
             if status == 'expired':
                 profile.is_pro = False
             
             elif status == 'cancelled':
                 # Cancelled generally means no renewal, but access remains until period end.
                 # We rely on 'ls_current_period_end' and 'is_pro' logic.
                 # If 'cancelled', we might want to just log it, but let expiration handle the access revocation.
                 pass

             profile.save()
             logger.info(f"User {user.id} subscription status: {status}.")
             
    except Exception as e:
        logger.error(f"Webhook Error: {e}", exc_info=True)
        return Response({'status': 'error'}, status=500)
        
    return Response({'status': 'ok'})
