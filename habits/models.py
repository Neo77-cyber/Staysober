from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.validators import RegexValidator


class Profile(models.Model):
    phone_regex = RegexValidator(
        regex=r'^234\d{10}$',
        message="Phone number must be entered in the format: '2348123456789'."
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(validators=[phone_regex], max_length=13, unique=True)
    timezone = models.CharField(max_length=50, default='Africa/Lagos')
    is_whatsapp_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile for {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        pass


class Habit(models.Model):
    HABIT_CHOICES = [
    ('DAILY PRAYERS', 'Daily Prayers'),
    ('WORK OUT', 'Work Out'),
    ('EXAM PREPARATION', 'Exam Preparation'),
    ('GAMBLING', 'Gambling'),
    ('WEED SOBER', 'Weed Sober'),
    ('LATE NIGHT EATING', 'Late Night Eating'),
    ('BUY BUY', 'Buy Buy'),
    ('ALCOHOL SOBER', 'Alcohol Sober'),
    ('CUSTOM', 'Custom Habit'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="habits")
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=225, choices=HABIT_CHOICES, default='CUSTOM')
    goal = models.CharField(max_length=255, default="Daily")
    created_at = models.DateTimeField(auto_now_add=True)

    
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    missed_count = models.PositiveIntegerField(default=0)   
    last_marked_date = models.DateField(null=True, blank=True)
    cached_nudge = models.TextField(null=True, blank=True)
    nudge_generated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def marked_today(self) -> bool:
        today = timezone.localdate()
        return self.last_marked_date == today

    @property
    def missed_yesterday(self) -> bool:
        """
        True if the user neither marked yesterday nor today,
        meaning they have an unresolved miss from yesterday.
        Only relevant for habits that have been started (last_marked_date set).
        """
        if self.last_marked_date is None:
            return False
        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)
        # They missed if last mark was before yesterday
        return self.last_marked_date < yesterday

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    def mark_done(self) -> dict:
        """
        Mark today's habit as done.
        Returns a result dict consumed by the view/JS.
        """
        today = timezone.localdate()

        if self.marked_today:
            return {"status": "already_done"}

        yesterday = today - timezone.timedelta(days=1)
        if self.last_marked_date == yesterday:
            
            self.current_streak += 1
        else:
            
            self.current_streak = 1

        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak

        self.last_marked_date = today

        
        DailyRecord.objects.update_or_create(
            habit=self, date=today,
            defaults={"completed": True}
        )

        self.save(update_fields=[
            "current_streak", "longest_streak",
            "last_marked_date"
        ])

        return {
            "status": "success",
            "current_streak": self.current_streak,
            "longest_streak": self.longest_streak,
        }

    def record_miss(self) -> dict:
        """
        Call this at midnight (via a management command / cron) when a user
        did not mark a habit yesterday. Also callable manually.
        Returns a dict describing what happened including if the user is banned.
        """
        self.missed_count += 1
        self.current_streak = 0

        DailyRecord.objects.update_or_create(
            habit=self,
            date=timezone.localdate() - timezone.timedelta(days=1),
            defaults={"completed": False}
        )

        banned = False
        if self.missed_count >= 3:
            user = self.user
            user.is_active = False
            user.save(update_fields=["is_active"])
            banned = True

        self.save(update_fields=["missed_count", "current_streak"])

        return {
            "status": "banned" if banned else "missed",
            "missed_count": self.missed_count,
        }


class DailyRecord(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name="records")
    date = models.DateField(default=timezone.now)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ['habit', 'date']

    def __str__(self):
        return f"{self.habit.name} on {self.date}"