import uuid
import os
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


def input_image_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1]
    return f'inputs/{uuid.uuid4().hex}{ext}'


def output_image_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1]
    return f'outputs/{uuid.uuid4().hex}{ext}'


class GenerationJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generation_jobs'
    )
    # API key used (null if from UI)
    api_key_used = models.ForeignKey(
        'api.APIKey', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='jobs'
    )

    prompt = models.TextField()
    negative_prompt = models.TextField(default=' ', blank=True)

    # Generation parameters
    num_inference_steps = models.PositiveIntegerField(default=40)
    true_cfg_scale = models.FloatField(default=4.0)
    guidance_scale = models.FloatField(default=1.0)
    seed = models.IntegerField(default=0)
    output_width = models.PositiveIntegerField(default=1024)
    output_height = models.PositiveIntegerField(default=1024)

    # Output
    output_image = models.ImageField(upload_to=output_image_upload_path, null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default='')

    # Timing
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Tags
    tags = models.ManyToManyField('JobTag', blank=True, related_name='jobs')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job {self.id} [{self.status}] - {self.prompt[:50]}"

    @property
    def duration_seconds(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def input_images_list(self):
        return list(self.input_images.all())


class JobInputImage(models.Model):
    job = models.ForeignKey(GenerationJob, on_delete=models.CASCADE, related_name='input_images')
    image = models.ImageField(upload_to=input_image_upload_path)
    order = models.PositiveSmallIntegerField(default=0)  # for ordering multiple inputs

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Input image {self.order} for job {self.job.id}"


class JobTag(models.Model):
    """Tags associated with generation jobs for filtering and organization."""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default='#10b981',
                             help_text='Hex color, e.g. #10b981')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SavedSearch(models.Model):
    """Saved filter combinations for quick re-use."""
    name = models.CharField(max_length=100)
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='saved_searches'
    )
    filters = models.JSONField(
        help_text='JSON dict of filter parameters'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.created_by.username})"
