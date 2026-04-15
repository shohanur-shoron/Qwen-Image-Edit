from rest_framework import serializers
from image_gen.models import GenerationJob, JobInputImage
from .models import APIKey


class JobInputImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = JobInputImage
        fields = ['id', 'order', 'image_url']

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None


class GenerationJobSerializer(serializers.ModelSerializer):
    input_images = JobInputImageSerializer(many=True, read_only=True)
    output_image_url = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = GenerationJob
        fields = [
            'id', 'status', 'prompt', 'negative_prompt',
            'num_inference_steps', 'true_cfg_scale', 'guidance_scale',
            'seed', 'output_width', 'output_height',
            'input_images', 'output_image_url',
            'error_message', 'created_at', 'started_at', 'completed_at',
            'duration_seconds', 'created_by_username',
        ]
        read_only_fields = [
            'id', 'status', 'output_image_url', 'error_message',
            'created_at', 'started_at', 'completed_at', 'duration_seconds',
            'created_by_username',
        ]

    def get_output_image_url(self, obj):
        request = self.context.get('request')
        if obj.output_image and request:
            return request.build_absolute_uri(obj.output_image.url)
        return None

    def get_created_by_username(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None


class APIKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIKey
        fields = ['id', 'name', 'key', 'created_at', 'last_used_at', 'is_active', 'total_requests']
        read_only_fields = ['id', 'key', 'created_at', 'last_used_at', 'total_requests']
