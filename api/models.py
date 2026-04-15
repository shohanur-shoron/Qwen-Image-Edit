import uuid
import secrets
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class APIKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text="Friendly name for this API key")
    key = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    total_requests = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.key[:8]}...)"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self._generate_key()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_key():
        return secrets.token_urlsafe(48)

    def record_use(self):
        self.last_used_at = timezone.now()
        self.total_requests += 1
        self.save(update_fields=['last_used_at', 'total_requests'])
