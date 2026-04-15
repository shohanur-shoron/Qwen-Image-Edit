import threading
import logging
import csv
import json
import uuid
from io import StringIO
from urllib.parse import urlencode

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, Http404, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q, F, FloatField
from django.db.models.functions import Extract
from django.utils import timezone
from datetime import datetime, timedelta

from .models import GenerationJob, JobInputImage, JobTag, SavedSearch
from .inference import run_generation, is_pipeline_loaded
from api.models import APIKey

logger = logging.getLogger(__name__)


def is_admin(user):
    return user.is_authenticated and user.is_staff


# --------------------------------------------------------------------------- #
#  Auth views
# --------------------------------------------------------------------------- #

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user and user.is_staff:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, 'Invalid credentials or insufficient permissions.')
    return render(request, 'image_gen/login.html')


@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


# --------------------------------------------------------------------------- #
#  Jobs list (paginated + advanced search)
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
def jobs_list(request):
    jobs_qs = GenerationJob.objects.select_related(
        'created_by', 'api_key_used'
    ).prefetch_related('input_images', 'tags')

    # ---- Collect all filter params ----
    query = request.GET.get('q', '').strip()
    error_query = request.GET.get('error_q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    source_filter = request.GET.get('source', '').strip()
    has_output_filter = request.GET.get('has_output', '').strip()

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    steps_min = request.GET.get('steps_min', '').strip()
    steps_max = request.GET.get('steps_max', '').strip()
    cfg_min = request.GET.get('cfg_min', '').strip()
    cfg_max = request.GET.get('cfg_max', '').strip()
    resolution = request.GET.get('resolution', '').strip()

    duration_min = request.GET.get('duration_min', '').strip()
    duration_max = request.GET.get('duration_max', '').strip()

    api_key_filter = request.GET.get('api_key', '').strip()
    tag_filter = request.GET.get('tag', '').strip()

    sort_by = request.GET.get('sort', '-created_at')

    # ---- Apply filters ----
    if query:
        jobs_qs = jobs_qs.filter(
            Q(prompt__icontains=query) | Q(id__icontains=query)
        )
    if error_query:
        jobs_qs = jobs_qs.filter(error_message__icontains=error_query)
    if status_filter:
        jobs_qs = jobs_qs.filter(status=status_filter)
    if source_filter:
        if source_filter == 'ui':
            jobs_qs = jobs_qs.filter(api_key_used__isnull=True)
        elif source_filter == 'api':
            jobs_qs = jobs_qs.filter(api_key_used__isnull=False)
    if has_output_filter == 'yes':
        jobs_qs = jobs_qs.filter(output_image__isnull=False)
    elif has_output_filter == 'no':
        jobs_qs = jobs_qs.filter(output_image__isnull=True)

    if date_from:
        try:
            jobs_qs = jobs_qs.filter(created_at__gte=datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            jobs_qs = jobs_qs.filter(created_at__lte=datetime.fromisoformat(date_to) + timedelta(days=1))
        except ValueError:
            pass

    if steps_min:
        jobs_qs = jobs_qs.filter(num_inference_steps__gte=int(steps_min))
    if steps_max:
        jobs_qs = jobs_qs.filter(num_inference_steps__lte=int(steps_max))
    if cfg_min:
        jobs_qs = jobs_qs.filter(true_cfg_scale__gte=float(cfg_min))
    if cfg_max:
        jobs_qs = jobs_qs.filter(true_cfg_scale__lte=float(cfg_max))
    if resolution:
        w, h = resolution.split('x')
        jobs_qs = jobs_qs.filter(output_width=int(w), output_height=int(h))

    if duration_min:
        jobs_qs = jobs_qs.filter(
            completed_at__isnull=False, started_at__isnull=False
        ).annotate(
            dur=F('completed_at') - F('started_at')
        ).filter(dur__gte=timedelta(seconds=float(duration_min)))
    if duration_max:
        jobs_qs = jobs_qs.filter(
            completed_at__isnull=False, started_at__isnull=False
        ).annotate(
            dur=F('completed_at') - F('started_at')
        ).filter(dur__lte=timedelta(seconds=float(duration_max)))

    if api_key_filter:
        jobs_qs = jobs_qs.filter(api_key_used_id=api_key_filter)
    if tag_filter:
        jobs_qs = jobs_qs.filter(tags__id=tag_filter)

    # ---- Sorting ----
    valid_sorts = {
        'created_at': '-created_at',
        '-created_at': '-created_at',
        'prompt': 'prompt',
        '-prompt': '-prompt',
        'duration': 'duration_sort',
        '-duration': '-duration_sort',
        'status': 'status',
        '-status': '-status',
        'steps': 'num_inference_steps',
        '-steps': '-num_inference_steps',
        'cfg': 'true_cfg_scale',
        '-cfg': '-true_cfg_scale',
    }
    actual_sort = valid_sorts.get(sort_by, '-created_at')
    if actual_sort in ('duration_sort', '-duration_sort'):
        jobs_qs = jobs_qs.annotate(
            duration_sort=F('completed_at') - F('started_at')
        )
    jobs_qs = jobs_qs.order_by(actual_sort)

    # ---- Pagination ----
    paginator = Paginator(jobs_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # ---- Context data ----
    all_api_keys = APIKey.objects.filter(is_active=True)
    all_tags = JobTag.objects.all()
    saved_searches = SavedSearch.objects.filter(created_by=request.user)

    # Resolution presets
    resolution_presets = [
        '512x512', '512x768', '768x768', '768x1024',
        '1024x1024', '1024x1536', '1280x720', '1280x1280',
        '1536x1024', '1536x1536', '2048x2048',
    ]

    return render(request, 'image_gen/jobs_list.html', {
        'page_obj': page_obj,
        'query': query,
        'error_query': error_query,
        'status_filter': status_filter,
        'source_filter': source_filter,
        'has_output_filter': has_output_filter,
        'date_from': date_from,
        'date_to': date_to,
        'steps_min': steps_min,
        'steps_max': steps_max,
        'cfg_min': cfg_min,
        'cfg_max': cfg_max,
        'resolution': resolution,
        'duration_min': duration_min,
        'duration_max': duration_max,
        'api_key_filter': api_key_filter,
        'tag_filter': tag_filter,
        'sort_by': sort_by,
        'all_api_keys': all_api_keys,
        'all_tags': all_tags,
        'saved_searches': saved_searches,
        'resolution_presets': resolution_presets,
    })


# --------------------------------------------------------------------------- #
#  Dashboard (admin only)
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
def dashboard(request):
    jobs = GenerationJob.objects.select_related('created_by', 'api_key_used').prefetch_related('input_images')[:50]
    api_keys = APIKey.objects.filter(created_by=request.user)
    model_loaded = is_pipeline_loaded()
    from django.conf import settings
    mock_mode = getattr(settings, 'MOCK_MODE', False)
    context = {
        'jobs': jobs,
        'api_keys': api_keys,
        'model_loaded': model_loaded,
        'mock_mode': mock_mode,
        'total_jobs': GenerationJob.objects.count(),
        'done_jobs': GenerationJob.objects.filter(status='done').count(),
        'failed_jobs': GenerationJob.objects.filter(status='failed').count(),
    }
    return render(request, 'image_gen/dashboard.html', context)


# --------------------------------------------------------------------------- #
#  Generate (UI)
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
def generate_view(request):
    if request.method == 'GET':
        return render(request, 'image_gen/generate.html')

    if request.method == 'POST':
        prompt = request.POST.get('prompt', '').strip()
        negative_prompt = request.POST.get('negative_prompt', ' ').strip() or ' '
        num_steps = int(request.POST.get('num_inference_steps', 40))
        cfg = float(request.POST.get('true_cfg_scale', 4.0))
        guidance = float(request.POST.get('guidance_scale', 1.0))
        seed = int(request.POST.get('seed', 0))
        width = int(request.POST.get('output_width', 1024))
        height = int(request.POST.get('output_height', 1024))

        if not prompt:
            messages.error(request, 'Prompt is required.')
            return redirect('generate')

        uploaded_images = request.FILES.getlist('input_images')
        max_imgs = getattr(settings, 'QWEN_MAX_IMAGES', 3)
        if not uploaded_images:
            messages.error(request, 'At least one input image is required.')
            return redirect('generate')
        if len(uploaded_images) > max_imgs:
            messages.error(request, f'Maximum {max_imgs} input images allowed.')
            return redirect('generate')

        # Create job
        job = GenerationJob.objects.create(
            created_by=request.user,
            prompt=prompt,
            negative_prompt=negative_prompt,
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

        # Run in background thread so the response returns immediately
        thread = threading.Thread(target=run_generation, args=(job,), daemon=True)
        thread.start()

        messages.success(request, f'Job {job.id} submitted successfully.')
        return redirect('job_detail', pk=str(job.id))

    raise Http404


# --------------------------------------------------------------------------- #
#  Job detail & status polling
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
def job_detail(request, pk):
    job = get_object_or_404(GenerationJob, pk=pk)
    params = [
        ('STEPS', job.num_inference_steps),
        ('CFG SCALE', job.true_cfg_scale),
        ('GUIDANCE', job.guidance_scale),
        ('SEED', job.seed),
        ('WIDTH', f'{job.output_width}px'),
        ('HEIGHT', f'{job.output_height}px'),
    ]
    return render(request, 'image_gen/job_detail.html', {'job': job, 'params': params})


@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_GET
def job_status_api(request, pk):
    """Lightweight polling endpoint for the UI."""
    job = get_object_or_404(GenerationJob, pk=pk)
    data = {
        'status': job.status,
        'output_image_url': job.output_image.url if job.output_image else None,
        'error_message': job.error_message,
        'duration': job.duration_seconds,
    }
    return JsonResponse(data)


# --------------------------------------------------------------------------- #
#  Bulk actions
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def bulk_action(request):
    action = request.POST.get('action', '').strip()
    job_ids = request.POST.getlist('job_ids')

    if not job_ids:
        messages.error(request, 'No jobs selected.')
        return redirect('jobs_list')

    jobs = GenerationJob.objects.filter(id__in=job_ids)
    count = jobs.count()

    if action == 'delete':
        jobs.delete()
        messages.success(request, f'{count} job(s) deleted.')
    elif action == 'rerun':
        for job in jobs:
            job.status = 'pending'
            job.output_image = None
            job.error_message = ''
            job.started_at = None
            job.completed_at = None
            job.save()
            thread = threading.Thread(target=run_generation, args=(job,), daemon=True)
            thread.start()
        messages.success(request, f'{count} job(s) queued for re-run.')
    elif action == 'tag':
        tag_ids = request.POST.getlist('tag_ids')
        tags = JobTag.objects.filter(id__in=tag_ids)
        for job in jobs:
            job.tags.set(tags)
        messages.success(request, f'{count} job(s) tagged.')
    else:
        messages.error(request, 'Invalid action.')

    return redirect('jobs_list')


# --------------------------------------------------------------------------- #
#  Export jobs (CSV / JSON)
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_GET
def export_jobs(request):
    fmt = request.GET.get('fmt', 'csv')
    ids = request.GET.getlist('id')

    if ids:
        jobs = GenerationJob.objects.filter(id__in=ids)
    else:
        # Export current filtered view
        jobs = GenerationJob.objects.all()[:5000]

    if fmt == 'json':
        data = []
        for job in jobs:
            data.append({
                'id': str(job.id),
                'prompt': job.prompt,
                'status': job.status,
                'created_at': job.created_at.isoformat(),
                'duration_seconds': job.duration_seconds,
                'steps': job.num_inference_steps,
                'cfg_scale': job.true_cfg_scale,
                'seed': job.seed,
                'width': job.output_width,
                'height': job.output_height,
                'error_message': job.error_message,
                'source': 'api' if job.api_key_used else 'ui',
                'tags': [t.name for t in job.tags.all()],
            })
        response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
        response['Content-Disposition'] = 'attachment; filename=qwen_jobs.json'
        return response

    # CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', 'Prompt', 'Status', 'Created At', 'Duration (s)',
        'Steps', 'CFG Scale', 'Seed', 'Width', 'Height',
        'Error', 'Source', 'Tags'
    ])
    for job in jobs:
        writer.writerow([
            str(job.id),
            job.prompt,
            job.status,
            job.created_at.isoformat(),
            job.duration_seconds or '',
            job.num_inference_steps,
            job.true_cfg_scale,
            job.seed,
            job.output_width,
            job.output_height,
            job.error_message,
            'api' if job.api_key_used else 'ui',
            ', '.join(t.name for t in job.tags.all()),
        ])

    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=qwen_jobs.csv'
    return response


# --------------------------------------------------------------------------- #
#  Saved searches
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def save_search(request):
    name = request.POST.get('name', '').strip()
    if not name:
        messages.error(request, 'Search name is required.')
        return redirect('jobs_list')

    # Capture all filter params from the referer's query string
    referer = request.META.get('HTTP_REFERER', '')
    if '?' in referer:
        query_string = referer.split('?', 1)[1]
        # Parse into dict
        from urllib.parse import parse_qs
        parsed = parse_qs(query_string)
        filters = {k: v[0] for k, v in parsed.items() if v[0]}
    else:
        filters = {}

    SavedSearch.objects.create(
        name=name,
        created_by=request.user,
        filters=filters,
    )
    messages.success(request, f'Search "{name}" saved.')
    return redirect('jobs_list')


@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def delete_saved_search(request, pk):
    ss = get_object_or_404(SavedSearch, pk=pk, created_by=request.user)
    ss.delete()
    messages.success(request, 'Saved search deleted.')
    return redirect('jobs_list')


# --------------------------------------------------------------------------- #
#  Tag management
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def create_tag(request):
    name = request.POST.get('name', '').strip()
    color = request.POST.get('color', '#10b981').strip()
    if not name:
        messages.error(request, 'Tag name is required.')
        return redirect('jobs_list')

    from django.utils.text import slugify
    slug = slugify(name)
    # Handle duplicate slugs
    base_slug = slug
    counter = 1
    while JobTag.objects.filter(slug=slug).exists():
        slug = f'{base_slug}-{counter}'
        counter += 1

    JobTag.objects.create(name=name, slug=slug, color=color)
    messages.success(request, f'Tag "{name}" created.')
    return redirect('jobs_list')


@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def delete_tag(request, pk):
    tag = get_object_or_404(JobTag, pk=pk)
    tag.delete()
    messages.success(request, 'Tag deleted.')
    return redirect('jobs_list')


# --------------------------------------------------------------------------- #
#  API Key management (UI)
# --------------------------------------------------------------------------- #

@login_required
@user_passes_test(is_admin, login_url='/login/')
def api_keys_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Key name is required.')
        else:
            key = APIKey.objects.create(name=name, created_by=request.user)
            messages.success(request, f'API key "{key.name}" created. Save it now: {key.key}')
        return redirect('api_keys')

    keys = APIKey.objects.filter(created_by=request.user)
    return render(request, 'image_gen/api_keys.html', {'api_keys': keys})


@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def revoke_api_key(request, pk):
    key = get_object_or_404(APIKey, pk=pk, created_by=request.user)
    key.is_active = False
    key.save()
    messages.success(request, f'API key "{key.name}" revoked.')
    return redirect('api_keys')


@login_required
@user_passes_test(is_admin, login_url='/login/')
@require_POST
def delete_api_key(request, pk):
    key = get_object_or_404(APIKey, pk=pk, created_by=request.user)
    key.delete()
    messages.success(request, 'API key deleted.')
    return redirect('api_keys')
