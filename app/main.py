"""
PhotoLens — PoC web service on Google Cloud Run.

Pipeline for one uploaded photo:
  1. contrast enhancement (histogram equalization, algorithm from lab 1);
  2. Cloud Vision API: labels, objects, OCR text, dominant colors;
  3. Cloud Translation API: labels/objects/text -> Ukrainian;
  4. Cloud Storage: original.jpg, enhanced.jpg, result.json.
"""
import base64
import io
import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError

from . import cloud
from .histeq import equalize

MAX_UPLOAD = 8 * 1024 * 1024
MAX_SIDE = 1600
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="PhotoLens")


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")  # note: /healthz is reserved by Cloud Run's frontend
def health():
    return {"ok": True, "mock": cloud.MOCK}


@app.post("/api/analyze")
def analyze(file: UploadFile = File(...)):
    # sync handler: FastAPI runs it in a threadpool, so blocking API calls don't stall the loop
    raw = file.file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Файл більший за 8 МБ")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(400, "Це не зображення")
    img.thumbnail((MAX_SIDE, MAX_SIDE))

    timings = {}
    t = time.perf_counter()
    enhanced, hist = equalize(img)
    timings["enhance"] = time.perf_counter() - t

    original_jpg, enhanced_jpg = _jpeg(img), _jpeg(enhanced)

    t = time.perf_counter()
    vision = cloud.analyze_image(enhanced_jpg)
    timings["vision"] = time.perf_counter() - t

    t = time.perf_counter()
    words = [l["en"] for l in vision["labels"]] + [o["en"] for o in vision["objects"]]
    text = vision["text"]["full"]
    translated = cloud.translate(words + ([text] if text else []))
    timings["translate"] = time.perf_counter() - t

    n_labels = len(vision["labels"])
    for i, l in enumerate(vision["labels"]):
        l["uk"] = translated[i]
    for j, o in enumerate(vision["objects"]):
        o["uk"] = translated[n_labels + j]

    job_id = uuid.uuid4().hex[:12]
    result = {
        "id": job_id,
        "created": cloud.now_iso(),
        "filename": file.filename,
        "size": list(img.size),
        "labels": vision["labels"],
        "objects": vision["objects"],
        "text": {**vision["text"], "uk": translated[-1] if text else ""},
        "colors": vision["colors"],
        "histogram": hist,
    }

    t = time.perf_counter()
    cloud.save(job_id, "original.jpg", original_jpg, "image/jpeg")
    cloud.save(job_id, "enhanced.jpg", enhanced_jpg, "image/jpeg")
    result["storage"] = cloud.save(job_id, "result.json",
                                   json.dumps(result, ensure_ascii=False).encode(), "application/json")
    timings["storage"] = time.perf_counter() - t
    result["timings_ms"] = {k: round(v * 1000) for k, v in timings.items()}

    result["images"] = {
        "original": "data:image/jpeg;base64," + base64.b64encode(original_jpg).decode(),
        "enhanced": "data:image/jpeg;base64," + base64.b64encode(enhanced_jpg).decode(),
    }
    return result


@app.get("/api/history")
def history():
    return cloud.history()


@app.get("/api/result/{job_id}")
def get_result(job_id: str):
    if not job_id.isalnum():
        raise HTTPException(400)
    data = cloud.load(job_id, "result.json")
    if data is None:
        raise HTTPException(404)
    result = json.loads(data)
    result["images"] = {n: f"/api/image/{job_id}/{n}" for n in ("original", "enhanced")}
    return result


@app.get("/api/image/{job_id}/{name}")
def get_image(job_id: str, name: str):
    if not job_id.isalnum() or name not in ("original", "enhanced"):
        raise HTTPException(400)
    data = cloud.load(job_id, f"{name}.jpg")
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="image/jpeg")
