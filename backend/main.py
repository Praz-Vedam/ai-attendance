from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from lms_attendance_routes import register_routes as register_lms_routes, router as lms_router
from lms_client import close_lms_client, get_lms_client
from session_review import init_review_worker, shutdown_review_poller, start_review_poller
from face_matching import (
    FACE_API_ONLY_MESSAGE,
    compare_embeddings,
    is_face_api_embedding,
)
from ml_config import ENABLE_ANTI_SPOOF, ENABLE_LOCATION_DETECTION, post_mark_review_status

from src.anti_spoof_predict import AntiSpoofPredict
from src.generate_patches import CropImage
from src.utility import parse_model_name

import numpy as np
from PIL import Image
import io
import os
import joblib
import torch
from transformers import AutoImageProcessor, AutoModel

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "http://localhost:3003",
    "http://127.0.0.1:3003",
    "https://dev-admin.vedam.org",
    "https://uat-admin.vedam.org",
    "https://admin.vedam.org",
    "https://dev-student.vedam.org",
    "https://uat-student.vedam.org",
    "https://student.vedam.org",
]

# Vercel previews, ngrok/Cloudflare tunnels, and local/LAN dev (any port).
DEFAULT_CORS_ORIGIN_REGEX = (
    r"https://("
    r".*\.vercel\.app"
    r"|.*\.ngrok(-free)?\.(dev|app|io)"
    r"|.*\.trycloudflare\.com"
    r")"
    r"|http://("
    r"localhost|127\.0\.0\.1"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?"
)
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX", DEFAULT_CORS_ORIGIN_REGEX)


def build_allowed_origins() -> list[str]:
    origins = list(DEFAULT_CORS_ORIGINS)
    for key in ("FRONTEND_URL", "CORS_ORIGINS"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        for part in raw.split(","):
            origin = part.strip().rstrip("/")
            if origin and origin not in origins:
                origins.append(origin)
    return origins


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_lms_client()
    init_review_worker(run_post_mark_review)
    await start_review_poller()
    yield
    await shutdown_review_poller()
    await close_lms_client()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def log_incoming_requests(request: Request, call_next):
    auth = request.headers.get("authorization", "")
    access_token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else None
    logging.getLogger("api").info(
        "[FE →] %s %s | accessToken=%s",
        request.method,
        request.url.path,
        access_token or "(none)",
    )
    response = await call_next(request)
    logging.getLogger("api").info(
        "[FE ←] %s %s -> %s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=build_allowed_origins(),
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.info(
    "ML flags: ENABLE_ANTI_SPOOF=%s ENABLE_LOCATION_DETECTION=%s",
    ENABLE_ANTI_SPOOF,
    ENABLE_LOCATION_DETECTION,
)

model_dir = "./resources/anti_spoof_models"
anti_spoof: Optional[AntiSpoofPredict] = None
location_processor = None
location_model = None
location_classifier = None

if ENABLE_ANTI_SPOOF:
    print("Loading SilentFace anti-spoofing models...")
    anti_spoof = AntiSpoofPredict(0)
    print("SilentFace models loaded")
else:
    print("Anti-spoof disabled (ENABLE_ANTI_SPOOF=false)")

if ENABLE_LOCATION_DETECTION:
    print("Loading Location Classifier...")
    location_processor = AutoImageProcessor.from_pretrained(
        "facebook/dinov2-base"
    )
    location_model = AutoModel.from_pretrained(
        "facebook/dinov2-base"
    )
    location_classifier = joblib.load(
        "location_model.pkl"
    )
    print("Location Classifier Loaded")
else:
    print("Location detection disabled (ENABLE_LOCATION_DETECTION=false)")

CLASS_NAMES = {
    0: "Classroom 1",
    1: "Classroom 2",
    2: "Classroom 3",
    3: "Non-Classroom"
}


def get_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def ips_match(admin_ip: Optional[str], student_ip: Optional[str]) -> bool:
    if not admin_ip or not student_ip:
        return True
    return admin_ip == student_ip


def embedding_to_list(embedding) -> list[float]:
    arr = np.array(embedding, dtype=np.float64)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return [float(x) for x in arr]


def check_spoof(image_bytes):
    if not ENABLE_ANTI_SPOOF:
        return True, 1.0

    image = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    image_np = np.array(image)

    prediction = np.zeros((1, 3))

    for model_name in os.listdir(model_dir):

        h_input, w_input, model_type, scale = (
            parse_model_name(model_name)
        )

        cropper = CropImage()

        param = {
            "org_img": image_np,
            "bbox": anti_spoof.get_bbox(image_np),
            "scale": scale,
            "out_w": w_input,
            "out_h": h_input,
            "crop": True,
        }

        img = cropper.crop(**param)

        prediction += anti_spoof.predict(
            img,
            os.path.join(model_dir, model_name)
        )

    label = np.argmax(prediction)

    confidence = prediction[0][label] / 2

    if label == 1:
        return True, float(1.0 - confidence)
    return False, float(confidence)


def get_location_embedding(image_bytes):
    image = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    inputs = location_processor(
        images=image,
        return_tensors="pt"
    )

    with torch.no_grad():
        outputs = location_model(
            **inputs
        )

    embedding = (
        outputs.last_hidden_state
        .mean(dim=1)
        .squeeze()
        .numpy()
    )

    return embedding


def detect_location(image_bytes):
    if not ENABLE_LOCATION_DETECTION:
        return {
            "location": None,
            "confidence": None,
        }

    embedding = get_location_embedding(
        image_bytes
    )

    prediction = (
        location_classifier
        .predict([embedding])[0]
    )

    probabilities = (
        location_classifier
        .predict_proba([embedding])[0]
    )

    confidence = float(
        max(probabilities)
    )

    location = CLASS_NAMES[
        prediction
    ]

    return {
        "location": location,
        "confidence": confidence
    }


@app.get("/")
def home():
    return {
        "message": "AI Proctoring Backend Running"
    }


def verify_lms_face(
    embedding: list,
    image_bytes: bytes,
    *,
    live_embedding: Optional[list] = None,
) -> dict:
    is_real, spoof_confidence = check_spoof(image_bytes)

    if not is_real:
        return {
            "success": False,
            "verified": False,
            "message": "Spoof attack detected",
            "spoof_confidence": spoof_confidence,
        }

    return verify_face_match_only(
        embedding,
        image_bytes,
        spoof_confidence=spoof_confidence,
        live_embedding=live_embedding,
    )


def verify_face_match_only(
    embedding: list,
    image_bytes: bytes,
    *,
    spoof_confidence: Optional[float] = None,
    live_embedding: Optional[list] = None,
) -> dict:
    if not embedding:
        return {
            "success": False,
            "message": "Face not registered for this account",
        }

    if live_embedding is None:
        return {
            "success": False,
            "message": FACE_API_ONLY_MESSAGE,
        }

    if not is_face_api_embedding(embedding) or not is_face_api_embedding(live_embedding):
        return {
            "success": False,
            "message": FACE_API_ONLY_MESSAGE,
        }

    live_embedding = embedding_to_list(live_embedding)

    verified, similarity = compare_embeddings(embedding, live_embedding)

    result = {
        "success": True,
        "verified": bool(verified),
        "similarity": float(similarity),
        "message": (
            "Identity verified"
            if verified
            else "Face does not match registered profile"
        ),
    }
    if spoof_confidence is not None:
        result["spoof_confidence"] = spoof_confidence
    return result


def run_post_mark_review(image_bytes: bytes, expected_classroom: Optional[str]) -> dict:
    is_real, spoof_confidence = check_spoof(image_bytes)
    location_result = detect_location(image_bytes)
    status, reason = post_mark_review_status(
        is_real,
        location_result.get("location"),
        expected_classroom,
    )
    return {
        "spoof_confidence": spoof_confidence,
        "location": location_result.get("location"),
        "location_confidence": location_result.get("confidence"),
        "status": status,
        "reason": reason,
    }


register_lms_routes(
    lms_router,
    get_client_ip=get_client_ip,
    verify_lms_face=verify_lms_face,
    verify_face_match_only=verify_face_match_only,
    detect_location=detect_location,
    ips_match=ips_match,
)

app.include_router(lms_router)