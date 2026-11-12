"""
Thin wrappers around the three Google Cloud APIs used by PhotoLens:

* Cloud Vision API      — labels, objects, text (OCR), dominant colors
* Cloud Translation API — translate labels / recognized text into Ukrainian
* Cloud Storage         — keep original, enhanced image and analysis JSON

With PHOTOLENS_MOCK=1 the module returns canned answers, so the UI can be
developed locally without credentials.
"""
import json
import os
from datetime import datetime, timezone

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
BUCKET = os.environ.get("PHOTOLENS_BUCKET", "")
TARGET_LANG = os.environ.get("PHOTOLENS_LANG", "uk")
MOCK = os.environ.get("PHOTOLENS_MOCK") == "1"

_vision = _translate = _storage = None


def _clients():
    global _vision, _translate, _storage
    if _vision is None:
        from google.cloud import storage, translate_v3, vision
        _vision = vision.ImageAnnotatorClient()
        _translate = translate_v3.TranslationServiceClient()
        _storage = storage.Client(project=PROJECT)
    return _vision, _translate, _storage


# ------------------------------------------------------------------ Vision
def analyze_image(content: bytes) -> dict:
    if MOCK:
        return {
            "labels": [{"en": "Sky", "score": 0.95}, {"en": "Building", "score": 0.91},
                       {"en": "Street", "score": 0.84}],
            "objects": [{"en": "Car", "score": 0.88}],
            "text": {"full": "OPEN 24/7", "locale": "en"},
            "colors": [{"hex": "#4a6fa5", "fraction": 0.41}, {"hex": "#e09f3e", "fraction": 0.22},
                       {"hex": "#9e9e9e", "fraction": 0.18}],
        }
    from google.cloud import vision
    client, _, _ = _clients()
    features = [
        vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=10),
        vision.Feature(type_=vision.Feature.Type.OBJECT_LOCALIZATION, max_results=10),
        vision.Feature(type_=vision.Feature.Type.TEXT_DETECTION),
        vision.Feature(type_=vision.Feature.Type.IMAGE_PROPERTIES),
    ]
    resp = client.annotate_image({"image": {"content": content}, "features": features})
    if resp.error.message:
        raise RuntimeError("Vision API: " + resp.error.message)

    text = resp.text_annotations[0] if resp.text_annotations else None
    colors = sorted(resp.image_properties_annotation.dominant_colors.colors,
                    key=lambda c: -c.pixel_fraction)[:6]
    return {
        "labels": [{"en": l.description, "score": round(l.score, 3)} for l in resp.label_annotations],
        "objects": [{"en": o.name, "score": round(o.score, 3)} for o in resp.localized_object_annotations],
        "text": {"full": text.description.strip() if text else "", "locale": text.locale if text else ""},
        "colors": [{"hex": "#%02x%02x%02x" % (int(c.color.red), int(c.color.green), int(c.color.blue)),
                    "fraction": round(c.pixel_fraction, 3)} for c in colors],
    }


# ------------------------------------------------------------------ Translation
def translate(texts: list[str], target: str = TARGET_LANG) -> list[str]:
    texts = [t for t in texts]
    if not texts:
        return []
    if MOCK:
        demo = {"Sky": "Небо", "Building": "Будівля", "Street": "Вулиця", "Car": "Автомобіль",
                "OPEN 24/7": "ВІДЧИНЕНО 24/7"}
        return [demo.get(t, t) for t in texts]
    _, client, _ = _clients()
    resp = client.translate_text(
        parent=f"projects/{PROJECT}/locations/global",
        contents=texts, target_language_code=target, mime_type="text/plain")
    return [t.translated_text for t in resp.translations]


# ------------------------------------------------------------------ Storage
_mock_store: dict[str, bytes] = {}


def save(job_id: str, name: str, data: bytes, content_type: str) -> str:
    path = f"results/{job_id}/{name}"
    if MOCK or not BUCKET:
        _mock_store[path] = data
        return f"mock://{path}"
    _, _, client = _clients()
    client.bucket(BUCKET).blob(path).upload_from_string(data, content_type=content_type)
    return f"gs://{BUCKET}/{path}"


def load(job_id: str, name: str) -> bytes | None:
    path = f"results/{job_id}/{name}"
    if MOCK or not BUCKET:
        return _mock_store.get(path)
    _, _, client = _clients()
    blob = client.bucket(BUCKET).blob(path)
    return blob.download_as_bytes() if blob.exists() else None


def history(limit: int = 12) -> list[dict]:
    if MOCK or not BUCKET:
        items = [json.loads(v) for k, v in _mock_store.items() if k.endswith("result.json")]
    else:
        _, _, client = _clients()
        blobs = [b for b in client.list_blobs(BUCKET, prefix="results/") if b.name.endswith("result.json")]
        blobs.sort(key=lambda b: b.time_created, reverse=True)
        items = [json.loads(b.download_as_bytes()) for b in blobs[:limit]]
    items.sort(key=lambda r: r.get("created", ""), reverse=True)
    return [{"id": r["id"], "created": r["created"], "filename": r.get("filename", ""),
             "labels": [l["uk"] for l in r.get("labels", [])[:4]]} for r in items[:limit]]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
