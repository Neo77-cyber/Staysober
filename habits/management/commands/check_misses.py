from django.core.management.base import BaseCommand
from django.utils import timezone
from habits.models import Habit

class Command(BaseCommand):
    help = "Record misses for any habit not marked yesterday."

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)

        # 1. Find habits that haven't been touched since before yesterday
        # 2. Only check active users
        # 3. Exclude habits that have never been started (last_marked_date=None)
        stale = Habit.objects.filter(
            last_marked_date__lt=yesterday,
            user__is_active=True,
        ).exclude(last_marked_date=None)

        if not stale.exists():
            self.stdout.write(self.style.SUCCESS("No stale habits found. Everyone is on track!"))
            return

        for habit in stale:
            result = habit.record_miss()
            status_msg = f"{habit.user.username} - {habit.name}: {result['status']}"
            
            # Color code the output for the logs
            if result['status'] == 'banned':
                self.stdout.write(self.style.ERROR(status_msg))
            else:
                self.stdout.write(self.style.WARNING(status_msg))