from django.contrib import admin
from .models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'key_preview', 'created_by', 'is_active', 'total_requests', 'created_at', 'last_used_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'created_by__username']
    readonly_fields = ['id', 'key', 'created_at', 'last_used_at', 'total_requests']

    def key_preview(self, obj):
        return f"{obj.key[:12]}..."
    key_preview.short_description = 'Key'
