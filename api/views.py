import threading
import logging

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from image_gen.models import GenerationJob, JobInputImage
from image_gen.inference import run_generation, is_pipeline_loaded
from .models import APIKey
from .authentication import APIKeyAuthentication
from .serializers import GenerationJobSerializer, APIKeySerializer

logger = logging.getLogger(__name__)


class APIKeyOrAdminPermission:
    """Allow if user is admin (session) OR authenticated via API key."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


# --------------------------------------------------------------------------- #
#  Generate endpoint  POST /api/generate/
# --------------------------------------------------------------------------- #

class GenerateView(APIView):
    """
    Create a new generation job.
    Accepts multipart/form-data with:
      - input_images (1–3 files)
      - prompt (str, required)
      - negative_prompt (str, optional)
      - num_inference_steps (int, default 40)
      - true_cfg_scale (float, default 4.0)
      - guidance_scale (float, default 1.0)
      - seed (int, default 0)
      - output_width (int, default 1024)
      - output_height (int, default 1024)

    Authentication: X-API-Key header OR session (admin).
    """
    authentication_classes = [APIKeyAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return [IsAuthenticated()]

    def post(self, request):
        prompt = request.data.get('prompt', '').strip()
        if not prompt:
            return Response({'error': 'prompt is required.'}, status=status.HTTP_400_BAD_REQUEST)

        uploaded_images = request.FILES.getlist('input_images')
        max_imgs = getattr(settings, 'QWEN_MAX_IMAGES', 3)
        if not uploaded_images:
            return Response({'error': 'At least one input image is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(uploaded_images) > max_imgs:
            return Response({'error': f'Maximum {max_imgs} input images allowed.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            num_steps = int(request.data.get('num_inference_steps', 40))
            cfg = float(request.data.get('true_cfg_scale', 4.0))
            guidance = float(request.data.get('guidance_scale', 1.0))
            seed = int(request.data.get('seed', 0))
            width = int(request.data.get('output_width', 1024))
            height = int(request.data.get('output_height', 1024))
        except (ValueError, TypeError) as e:
            return Response({'error': f'Invalid parameter: {e}'}, status=status.HTTP_400_BAD_REQUEST)

        # Identify the API key used (auth object is the APIKey instance if key auth)
        api_key_used = request.auth if isinstance(request.auth, APIKey) else None

        job = GenerationJob.objects.create(
            created_by=request.user,
            api_key_used=api_key_used,
            prompt=prompt,
            negative_prompt=request.data.get('negative_prompt', ' ') or ' ',
            num_inference_steps=num_steps,
            true_cfg_scale=cfg,
            guidance_scale=guidance,
            seed=seed,
            output_width=width,
            output_height=height,
            status='pending',
        )

        for idx, img_file in enumerate(uploaded_images):
            JobInputImage.objects.create(job=job, image=img_file, order=idx)

        thread = threading.Thread(target=run_generation, args=(job,), daemon=True)
        thread.start()

        serializer = GenerationJobSerializer(job, context={'request': request})
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


# --------------------------------------------------------------------------- #
#  Job status  GET /api/jobs/<id>/
# --------------------------------------------------------------------------- #

class JobDetailView(APIView):
    authentication_classes = [APIKeyAuthentication]

    def get_permissions(self):
        return [IsAuthenticated()]

    def get(self, request, pk):
        try:
            job = GenerationJob.objects.prefetch_related('input_images').get(pk=pk)
        except GenerationJob.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = GenerationJobSerializer(job, context={'request': request})
        return Response(serializer.data)


# --------------------------------------------------------------------------- #
#  Job list  GET /api/jobs/
# --------------------------------------------------------------------------- #

class JobListView(APIView):
    authentication_classes = [APIKeyAuthentication]

    def get_permissions(self):
        return [IsAuthenticated()]

    def get(self, request):
        jobs = GenerationJob.objects.prefetch_related('input_images').all()[:100]
        serializer = GenerationJobSerializer(jobs, many=True, context={'request': request})
        return Response(serializer.data)


# --------------------------------------------------------------------------- #
#  API Key management  (admin session only)
# --------------------------------------------------------------------------- #

class APIKeyListCreateView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        keys = APIKey.objects.filter(created_by=request.user)
        serializer = APIKeySerializer(keys, many=True)
        return Response(serializer.data)

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        key = APIKey.objects.create(name=name, created_by=request.user)
        serializer = APIKeySerializer(key)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class APIKeyDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get_object(self, request, pk):
        try:
            return APIKey.objects.get(pk=pk, created_by=request.user)
        except APIKey.DoesNotExist:
            return None

    def patch(self, request, pk):
        key = self.get_object(request, pk)
        if not key:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        is_active = request.data.get('is_active')
        if is_active is not None:
            key.is_active = bool(is_active)
            key.save()
        serializer = APIKeySerializer(key)
        return Response(serializer.data)

    def delete(self, request, pk):
        key = self.get_object(request, pk)
        if not key:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        key.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
#  Model status  GET /api/status/
# --------------------------------------------------------------------------- #

class ModelStatusView(APIView):
    authentication_classes = [APIKeyAuthentication]

    def get_permissions(self):
        return [IsAuthenticated()]

    def get(self, request):
        from django.conf import settings
        mock_mode = getattr(settings, 'MOCK_MODE', False)
        return Response({
            'model_loaded': is_pipeline_loaded(),
            'model_id': getattr(settings, 'QWEN_MODEL_ID', 'Qwen/Qwen-Image-Edit-2511'),
            'mock_mode': mock_mode,
        })
