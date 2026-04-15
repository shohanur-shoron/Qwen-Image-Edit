"""
Qwen-Image-Edit-2511 inference engine.
Loads the model once and keeps it in memory for subsequent requests.
Supports MOCK_MODE for testing without the actual model.
"""
import io
import os
import logging
import threading
import uuid
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_pipeline = None
_lock = threading.Lock()
_loading = False


def get_pipeline():
    """Return the loaded pipeline, loading it if necessary."""
    global _pipeline, _loading

    if _pipeline is not None:
        return _pipeline

    with _lock:
        if _pipeline is not None:
            return _pipeline

        _loading = True
        try:
            from django.conf import settings

            # Check if mock mode is enabled
            if getattr(settings, 'MOCK_MODE', False):
                logger.info("MOCK MODE: Skipping model download. Using fake pipeline.")
                _pipeline = "mock"
                return _pipeline

            import torch
            from diffusers import QwenImageEditPlusPipeline

            model_id = getattr(settings, 'QWEN_MODEL_ID', 'Qwen/Qwen-Image-Edit-2511')
            dtype_str = getattr(settings, 'QWEN_TORCH_DTYPE', 'bfloat16')
            dtype = getattr(torch, dtype_str, torch.bfloat16)

            logger.info(f"Loading Qwen pipeline: {model_id} with dtype={dtype_str}")
            pipe = QwenImageEditPlusPipeline.from_pretrained(model_id, torch_dtype=dtype)
            pipe.to('cuda')
            pipe.set_progress_bar_config(disable=True)

            _pipeline = pipe
            logger.info("Qwen pipeline loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Qwen pipeline: {e}")
            raise
        finally:
            _loading = False

    return _pipeline


def is_pipeline_loaded():
    return _pipeline is not None


def run_generation(job):
    """
    Run inference for a GenerationJob.
    Updates the job in-place and saves to DB.
    Returns (success: bool, error_message: str)
    """
    from PIL import Image as PILImage
    from django.utils import timezone
    from django.core.files.base import ContentFile
    from django.conf import settings

    # Check mock mode
    mock_mode = getattr(settings, 'MOCK_MODE', False)

    if not mock_mode:
        try:
            pipeline = get_pipeline()
        except Exception as e:
            return False, f"Failed to load model: {str(e)}"

    # Mark as processing
    job.status = 'processing'
    job.started_at = timezone.now()
    job.save(update_fields=['status', 'started_at'])

    try:
        if mock_mode:
            # MOCK MODE: Simulate generation without actual model
            logger.info(f"MOCK MODE: Simulating generation for job {job.id}")
            time.sleep(3)  # Simulate processing time

            # Create a simple test image (solid color with text)
            output_image = PILImage.new('RGB', (job.output_width, job.output_height), color=(70, 130, 180))
            
            # Draw some text on it
            from PIL import ImageDraw
            draw = ImageDraw.Draw(output_image)
            text = f"MOCK OUTPUT\nJob: {str(job.id)[:8]}\nPrompt: {job.prompt[:50]}"
            draw.text((50, 50), text, fill=(255, 255, 255))
        else:
            # REAL MODE: Use actual model
            # Load input images
            input_imgs = []
            for job_img in job.input_images.all():
                img = PILImage.open(job_img.image.path).convert("RGB")
                input_imgs.append(img)

            if not input_imgs:
                return False, "No input images provided."

            # Single image or list
            image_input = input_imgs[0] if len(input_imgs) == 1 else input_imgs

            negative_prompt = job.negative_prompt if job.negative_prompt.strip() else " "

            import torch

            inputs = {
                "image": image_input,
                "prompt": job.prompt,
                "negative_prompt": negative_prompt,
                "generator": torch.manual_seed(job.seed),
                "true_cfg_scale": job.true_cfg_scale,
                "guidance_scale": job.guidance_scale,
                "num_inference_steps": job.num_inference_steps,
                "num_images_per_prompt": 1,
                "height": job.output_height,
                "width": job.output_width,
            }

            with torch.inference_mode():
                output = pipeline(**inputs)

            output_image = output.images[0]

        # Save output image to media
        buffer = io.BytesIO()
        output_image.save(buffer, format='PNG')
        buffer.seek(0)

        filename = f"{uuid.uuid4().hex}.png"
        job.output_image.save(filename, ContentFile(buffer.read()), save=False)

        job.status = 'done'
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at', 'output_image'])

        if mock_mode:
            logger.info(f"MOCK MODE: Job {job.id} completed successfully (fake output).")

        return True, ""

    except Exception as e:
        logger.exception(f"Generation failed for job {job.id}: {e}")
        job.status = 'failed'
        job.error_message = str(e)
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'error_message', 'completed_at'])
        return False, str(e)
