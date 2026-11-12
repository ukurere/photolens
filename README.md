# PhotoLens — покращення та розпізнавання фото в Google Cloud

Лабораторна робота 2 (семінар-презентація), курс «Хмарні обчислення», ТТП-42, КНУ, 2026.
PoC-проєкт з інтеграцією хмарних API: **Google Cloud Vision**, **Cloud Translation**, **Cloud Storage**, **Cloud Run**.

![демо](docs/screenshots/demo.png)

## 1. Опис проєкту

Користувач завантажує фото у вебзастосунок, а сервіс:

1. **покращує контраст** — вирівнювання гістограми яскравості (алгоритм з
   [лабораторної 1](https://github.com/ukurere/parcs-histogram-equalization));
2. **розпізнає вміст** через Cloud Vision API: мітки (що на фото), об'єкти, текст (OCR), домінантні кольори;
3. **перекладає** мітки й розпізнаний текст українською через Cloud Translation API;
4. **зберігає** оригінал, покращене фото і JSON-результат у Cloud Storage (є історія запитів).

**Де можна використати:**
* оцифрування документів, чеків, вивісок — OCR + переклад;
* інтернет-магазини й каталоги — автоматичні теги та кольори товарів;
* доступність — текстовий опис фото для людей з порушеннями зору;
* архіви старих / темних фото — автоматичне покращення контрасту перед розпізнаванням.

## 2. Використані API

| Сервіс | Що робить у проєкті | Метод / клієнт |
|---|---|---|
| **Cloud Vision API** | `LABEL_DETECTION` — мітки; `OBJECT_LOCALIZATION` — об'єкти; `TEXT_DETECTION` — OCR + мова тексту; `IMAGE_PROPERTIES` — домінантні кольори. Усе одним запитом `annotate_image` | `google-cloud-vision` → `ImageAnnotatorClient.annotate_image` |
| **Cloud Translation API (v3)** | переклад міток, об'єктів і OCR-тексту на українську, мова джерела визначається автоматично | `google-cloud-translate` → `TranslationServiceClient.translate_text` |
| **Cloud Storage** | `results/<id>/original.jpg`, `enhanced.jpg`, `result.json`; історія = список `result.json` | `google-cloud-storage` → `Bucket.blob().upload_from_string`, `list_blobs` |
| **Cloud Run** | хостинг контейнера з FastAPI, автомасштабування 0…2 інстанси, HTTPS, IAM-автентифікація | `gcloud run deploy --source .` (Cloud Build + Artifact Registry) |
| **IAM** | окремий service account `photolens-sa` з мінімальними правами: `storage.objectAdmin` лише на bucket, `cloudtranslate.user` | — |

Приклад відповіді Vision API (скорочено):

```json
{ "labelAnnotations": [{ "description": "Graphic design", "score": 0.83 }],
  "textAnnotations":  [{ "locale": "en", "description": "OPEN 24/7 CAFE" }],
  "imagePropertiesAnnotation": { "dominantColors": { "colors": [{ "color": {"red": 163, "green": 96, "blue": 117}, "pixelFraction": 0.12 }] } } }
```

## 3. Взаємодія сервісів

```
 Браузер ──HTTPS POST /api/analyze (фото)──▶ Cloud Run: контейнер FastAPI (service account photolens-sa)
                                              │
                                              ├─ 1. histeq.equalize()  — вирівнювання гістограми Y (numpy)
                                              ├─ 2. Cloud Vision API   — labels, objects, OCR, colors
                                              ├─ 3. Cloud Translation  — EN/… → UK
                                              ├─ 4. Cloud Storage      — original.jpg, enhanced.jpg, result.json
                                              ▼
 Браузер ◀──────────────── JSON (мітки, текст, кольори, гістограми, час кожного кроку) + зображення
```

* Автентифікація між сервісами — через service account Cloud Run (жодних ключів у коді).
* Доступ користувача — через IAM: сервіс не публічний, відкривається через
  `gcloud run services proxy` (захист від витрати кредиту сторонніми).
* Інтерфейс показує час кожного кроку: типово покращення ~80 мс, Vision ~2 с, Translation ~0.4 с, Storage ~0.3 с.

## 4. Демонстрація

Відео: [`docs/demo.mp4`](docs/demo.mp4)

## 5. Запуск

### Локально без хмари (mock-режим)

```powershell
python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
$env:PHOTOLENS_MOCK = "1" ; .venv\Scripts\uvicorn app.main:app --port 8000
# http://localhost:8000
```

### Google Cloud

```powershell
$P = "<project-id>" ; $B = "photolens-<suffix>"
gcloud services enable vision.googleapis.com translate.googleapis.com storage.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud storage buckets create gs://$B --location=europe-central2 --uniform-bucket-level-access --public-access-prevention
gcloud iam service-accounts create photolens-sa
$SA = "photolens-sa@$P.iam.gserviceaccount.com"
gcloud storage buckets add-iam-policy-binding gs://$B --member="serviceAccount:$SA" --role=roles/storage.objectAdmin
gcloud projects add-iam-policy-binding $P --member="serviceAccount:$SA" --role=roles/cloudtranslate.user
gcloud projects add-iam-policy-binding $P --member="serviceAccount:$SA" --role=roles/serviceusage.serviceUsageConsumer

gcloud run deploy photolens --source . --region europe-central2 --service-account $SA `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$P,PHOTOLENS_BUCKET=$B" --memory 1Gi --max-instances 2 --no-allow-unauthenticated

gcloud run services proxy photolens --region europe-central2 --port 8081
# http://localhost:8081
```

Прибрати: `gcloud run services delete photolens --region europe-central2 ; gcloud storage rm -r gs://$B`

## 6. Структура

```
app/main.py          — FastAPI: /api/analyze, /api/history, /api/result/<id>, /api/image/<id>/<name>
app/cloud.py         — обгортки Vision / Translation / Storage (+ mock-режим)
app/histeq.py        — вирівнювання гістограми (алгоритм з ЛР1, numpy)
app/static/index.html— інтерфейс (без фреймворків)
Dockerfile           — образ для Cloud Run
```

## 7. GitHub

https://github.com/ukurere/photolens
