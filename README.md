# Qwen Studio — Django Image Editing App

A full Django web application for running **Qwen-Image-Edit-2511** locally.
Includes an MVT UI for admins and a REST API secured with API keys.

---

<img width="1917" height="958" alt="image" src="https://github.com/user-attachments/assets/6ea210de-35f2-4075-aa7c-1f2268a82fef" />
<img width="1918" height="957" alt="image" src="https://github.com/user-attachments/assets/2e4bc471-f7b3-415a-a516-57b8028f5073" />
<img width="1919" height="956" alt="image" src="https://github.com/user-attachments/assets/6b85cf5b-d3a7-4462-b0be-bf5c074bace9" />
<img width="1915" height="958" alt="image" src="https://github.com/user-attachments/assets/c71c1673-39ef-4c0b-b5c3-ffa84a82846d" />
<img width="1918" height="957" alt="image" src="https://github.com/user-attachments/assets/cb5dab2d-1a10-4c43-888d-4a1da5c5e313" />
<img width="1919" height="956" alt="image" src="https://github.com/user-attachments/assets/1d613095-ed53-4e9d-815a-dd27c3f31895" />

---

## Project Structure

```
qwen_studio/
├── manage.py
├── requirements.txt
├── db.sqlite3               (auto-created)
├── media/
│   ├── inputs/              (uploaded input images)
│   └── outputs/             (generated output images)
├── qwen_studio/             (Django project)
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── image_gen/               (MVT app: UI + models)
│   ├── models.py            (GenerationJob, JobInputImage)
│   ├── views.py
│   ├── urls.py
│   ├── inference.py         (Qwen pipeline wrapper)
│   ├── admin.py
│   └── templates/image_gen/
│       ├── base.html
│       ├── login.html
│       ├── dashboard.html
│       ├── generate.html
│       ├── job_detail.html
│       └── api_keys.html
└── api/                     (DRF REST API app)
    ├── models.py            (APIKey)
    ├── views.py
    ├── urls.py
    ├── serializers.py
    ├── authentication.py    (X-API-Key auth)
    └── admin.py
```

---

## Setup

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# PyTorch with CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# Diffusers from GitHub (required for 2511 support)
pip install git+https://github.com/huggingface/diffusers

pip install django djangorestframework Pillow transformers accelerate huggingface_hub
```

### 2. Database setup

```bash
python manage.py migrate
python manage.py createsuperuser
# ↑ This user will be the admin who can log in and generate images
```

### 3. Run

```bash
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000 and sign in with your superuser credentials.

---

## Pages

| URL | Description |
|---|---|
| `/` | Dashboard — job list, stats, API key overview |
| `/generate/` | Submit a new generation job |
| `/jobs/<id>/` | Job detail with live status polling |
| `/api-keys/` | Create and manage API keys |
| `/admin/` | Django admin panel |

---

## REST API

### Authentication

Pass your API key in the `X-API-Key` header:

```
X-API-Key: your_key_here
```

### Endpoints

#### `POST /api/generate/`
Submit a generation job. Accepts `multipart/form-data`.

| Field | Type | Required | Default |
|---|---|---|---|
| `input_images` | file(s) | ✓ | — |
| `prompt` | string | ✓ | — |
| `negative_prompt` | string | | ` ` |
| `num_inference_steps` | int | | 40 |
| `true_cfg_scale` | float | | 4.0 |
| `guidance_scale` | float | | 1.0 |
| `seed` | int | | 0 |
| `output_width` | int | | 1024 |
| `output_height` | int | | 1024 |

Returns `202 Accepted` with the job object.

#### `GET /api/jobs/<uuid>/`
Poll a job for its current status and output image URL.

#### `GET /api/jobs/`
List the last 100 jobs.

#### `GET /api/status/`
Check if the model pipeline is loaded in memory.

#### `GET /api/keys/`
List your API keys (admin session only).

#### `POST /api/keys/`
Create an API key (admin session only). Body: `{"name": "My App"}`

#### `PATCH /api/keys/<uuid>/`
Activate/revoke a key. Body: `{"is_active": false}`

#### `DELETE /api/keys/<uuid>/`
Permanently delete a key.

---

## Example API usage (Python)

```python
import requests
import time

BASE = "http://localhost:8000"
API_KEY = "your_key_here"
HEADERS = {"X-API-Key": API_KEY}

# Submit job
with open("my_photo.png", "rb") as f:
    resp = requests.post(
        f"{BASE}/api/generate/",
        headers=HEADERS,
        files={"input_images": f},
        data={
            "prompt": "Replace the background with a sunset beach",
            "num_inference_steps": 40,
            "true_cfg_scale": 4.0,
            "seed": 42,
        }
    )

job = resp.json()
job_id = job["id"]
print(f"Job submitted: {job_id}")

# Poll until done
while True:
    status = requests.get(f"{BASE}/api/jobs/{job_id}/", headers=HEADERS).json()
    print(f"Status: {status['status']}")
    if status["status"] in ("done", "failed"):
        break
    time.sleep(5)

if status["status"] == "done":
    img_url = status["output_image_url"]
    print(f"Output: {img_url}")
    img_data = requests.get(img_url).content
    with open("output.png", "wb") as f:
        f.write(img_data)
```

---

## Notes

- The Qwen pipeline loads on first request and stays in memory (~24GB VRAM).
- Generation runs in a **background thread** so the HTTP response returns immediately.
- Poll `/api/jobs/<id>/` every 3–5s until `status` is `done` or `failed`.
- Multi-image input (up to 3 images) is supported for reference-guided editing.
- The UI auto-polls the job detail page every 3 seconds using JavaScript.
