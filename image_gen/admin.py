from django.contrib import admin
from .models import GenerationJob, JobInputImage


class JobInputImageInline(admin.TabularInline):
    model = JobInputImage
    extra = 0
    readonly_fields = ['image', 'order']


@admin.register(GenerationJob)
class GenerationJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'created_by', 'prompt_short', 'created_at', 'duration_seconds']
    list_filter = ['status', 'created_at']
    search_fields = ['prompt', 'created_by__username']
    readonly_fields = ['id', 'created_at', 'started_at', 'completed_at', 'duration_seconds']
    inlines = [JobInputImageInline]

    def prompt_short(self, obj):
        return obj.prompt[:60]
    prompt_short.short_description = 'Prompt'


@admin.register(JobInputImage)
class JobInputImageAdmin(admin.ModelAdmin):
    list_display = ['id', 'job', 'order']
