# habits/management/commands/create_locust_users.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from habits.models import Profile, Habit
import random

class Command(BaseCommand):
    help = 'Create test users for Locust (phone format: 234##########)'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=50)
        parser.add_argument('--password', default='testpass123')

    def handle(self, *args, **options):
        count = options['count']
        password = options['password']
        created = 0
        
        for i in range(count):
            # Generate: 2348100000000 to 2348100000050 (13 digits)
            phone = f"234810000{i:04d}"  # Ensures 13 digit format
            
            if User.objects.filter(username=phone).exists():
                continue
                
            user = User.objects.create_user(
                username=phone,
                password=password,
                is_active=True
            )
            Profile.objects.create(
                user=user,
                phone_number=phone,  # Must match regex ^234\d{10}$
                timezone='Africa/Lagos'
            )
            
            # Give each user 1-2 habits so the list view has data
            habits = [
                ('Daily Prayers', 'DAILY PRAYERS'),
                ('Work Out', 'WORK OUT'),
                ('Exam Prep', 'EXAM PREPARATION'),
            ]
            for h_name, h_cat in random.sample(habits, k=random.randint(1, 2)):
                Habit.objects.create(
                    user=user,
                    name=h_name,
                    category=h_cat,
                    current_streak=random.randint(0, 5),
                    missed_count=random.randint(0, 1)
                )
            created += 1
            
        self.stdout.write(self.style.SUCCESS(f'Created {created} test users (password: {password})'))
