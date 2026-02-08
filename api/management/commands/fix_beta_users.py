from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from api.models import UserProfile


class Command(BaseCommand):
    help = 'Fix is_pro status for beta users'

    def handle(self, *args, **options):
        # Get all users
        profiles = UserProfile.objects.all()
        
        self.stdout.write(self.style.SUCCESS(f'\nFound {profiles.count()} user profiles\n'))
        
        fixed_count = 0
        for profile in profiles:
            user = profile.user
            self.stdout.write(f'\nUser: {user.email}')
            self.stdout.write(f'  is_pro: {profile.is_pro}')
            self.stdout.write(f'  credits: {profile.credits}')
            self.stdout.write(f'  ls_status: {profile.ls_status}')
            
            # Fix: Set is_pro to False for users without active subscription
            if profile.is_pro and profile.ls_status != 'active':
                self.stdout.write(self.style.WARNING(f'  ⚠️  Fixing: is_pro=True but ls_status={profile.ls_status}'))
                profile.is_pro = False
                profile.save()
                fixed_count += 1
                self.stdout.write(self.style.SUCCESS(f'  ✅ Fixed! is_pro is now False'))
        
        self.stdout.write(self.style.SUCCESS(f'\n\nFixed {fixed_count} users'))
