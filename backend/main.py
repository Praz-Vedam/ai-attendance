from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from local_db import kv_get, kv_set

import json
import logging
import time
from typing import Annotated, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from lms_attendance_routes import register_routes as register_lms_routes, router as lms_router
from student_store import (
    create_session,
    create_student_with_face,
    get_session_email,
    get_student,
    list_students,
    student_has_face,
    upsert_face,
)

from insightface.app import FaceAnalysis

from src.anti_spoof_predict import AntiSpoofPredict
from src.generate_patches import CropImage
from src.utility import parse_model_name

import numpy as np
from PIL import Image
import io
import os
from datetime import datetime, timezone
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
    "http://192.168.20.76:3000",
    "http://192.168.20.76:3003",
    "https://dev-admin.vedam.org",
    "https://uat-admin.vedam.org",
    "https://admin.vedam.org",
    "https://dev-student.vedam.org",
    "https://uat-student.vedam.org",
    "https://student.vedam.org",
]

# Vercel production + preview deployments (https://*.vercel.app)
VERCEL_CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://.*\.vercel\.app",
)


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

app = FastAPI()


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
    allow_origin_regex=VERCEL_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Loading InsightFace models...")

face_app = FaceAnalysis(name="buffalo_l")
face_app.prepare(ctx_id=-1)

print("InsightFace models loaded")

print("Loading SilentFace anti-spoofing models...")

model_dir = "./resources/anti_spoof_models"

anti_spoof = AntiSpoofPredict(0)

print("SilentFace models loaded")

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

CLASS_NAMES = {
    0: "Classroom 1",
    1: "Classroom 2",
    2: "Classroom 3",
    3: "Non-Classroom"
}

attendance_active = False
attendance_started_at = None
attendance_session_ip: Optional[str] = None
attendance_expected_classroom: Optional[str] = None
attendance_records = []

SIMILARITY_THRESHOLD = 0.45
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
MIN_SIGNUP_SCANS = 1


class AttendanceStartRequest(BaseModel):
    classroom: str


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


def marked_student_public(record: dict) -> dict:
    payload = {
        "email": record["email"],
        "name": record["name"],
        "marked_at": record["marked_at"],
        "ip_match": record.get("ip_match", True),
        "student_ip": record.get("student_ip"),
        "location": record.get("location"),
        "location_confidence": record.get(
            "location_confidence"
        ),
        "status": record.get("status", "Present"),
        "reason": record.get("reason"),
    }
    if record.get("snapshot"):
        payload["has_snapshot"] = True
    return payload


def attendance_status_public() -> dict:
    return {
        "active": attendance_active,
        "started_at": attendance_started_at,
        "teacher_ip": attendance_session_ip,
        "expected_classroom": attendance_expected_classroom,
        "marked_count": len(attendance_records),
        "marked_students": [
            marked_student_public(record)
            for record in attendance_records
        ],
    }


def student_public_profile(student: Dict) -> Dict:
    return {
        "email": student["email"],
        "student_id": student.get("student_id", student["email"].split("@")[0]),
        "name": student["name"],
        "face_registered": student_has_face(student),
        "face_registered_at": student.get("face_registered_at"),
        "created_at": student.get("created_at"),
    }


def require_student(
    authorization: Annotated[Optional[str], Header()] = None,
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.removeprefix("Bearer ").strip()
    email = get_session_email(token)
    if not email:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    student = get_student(email)
    if not student:
        raise HTTPException(status_code=401, detail="Student account not found")

    return student


def embedding_to_list(embedding) -> list[float]:
    return [float(x) for x in embedding]


def get_embedding(image_bytes):
    image = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    image_np = np.array(image)

    faces = face_app.get(image_np)

    if len(faces) == 0:
        return None

    return faces[0].embedding


def check_spoof(image_bytes):
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

    return label == 1, float(confidence)


def find_student_by_email(email: str):
    return get_student(email)


def cosine_similarity(a, b):
    return float(
        np.dot(a, b)
        / (np.linalg.norm(a) * np.linalg.norm(b))
    )


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


def average_embedding_from_images(image_bytes_list: List[bytes]):
    vectors = []
    for image_bytes in image_bytes_list:
        embedding = get_embedding(image_bytes)
        if embedding is not None:
            vectors.append(embedding)
    if not vectors:
        return None
    return np.mean(vectors, axis=0)


def find_student_by_face(embedding) -> Tuple[Optional[Dict], float]:
    best_similarity = 0.0
    best_student = None

    for student in list_students():
        if not student_has_face(student):
            continue
        similarity = cosine_similarity(
            np.array(student["embedding"]),
            embedding,
        )
        if similarity > best_similarity:
            best_similarity = similarity
            best_student = student

    return best_student, best_similarity


def verify_student_face(email: str, image_bytes):
    student = find_student_by_email(email)

    if student is None:
        return {
            "success": False,
            "message": "Student not registered",
        }

    is_real, spoof_confidence = check_spoof(image_bytes)

    if not is_real:
        return {
            "success": False,
            "verified": False,
            "message": "Spoof attack detected",
            "spoof_confidence": spoof_confidence,
        }

    live_embedding = get_embedding(image_bytes)

    if live_embedding is None:
        return {
            "success": False,
            "message": "No face detected",
        }

    if not student_has_face(student):
        return {
            "success": False,
            "message": "Face not registered for this account",
        }

    similarity = cosine_similarity(
        np.array(student["embedding"]),
        live_embedding,
    )

    verified = similarity > SIMILARITY_THRESHOLD

    return {
        "success": True,
        "verified": bool(verified),
        "similarity": similarity,
        "spoof_confidence": spoof_confidence,
        "message": (
            "Identity verified"
            if verified
            else "Face does not match registered student"
        ),
    }


@app.get("/")
def home():
    return {
        "message": "AI Proctoring Backend Running"
    }


@app.post("/register-student")
async def register_student(
    name: str = Form(...),
    files: List[UploadFile] = File(...),
):
    display_name = name.strip()
    if not display_name:
        return {"success": False, "message": "Name is required"}

    if len(files) < MIN_SIGNUP_SCANS:
        return {
            "success": False,
            "message": f"At least {MIN_SIGNUP_SCANS} face scan is required",
        }

    image_bytes_list = [await upload.read() for upload in files]
    embedding = average_embedding_from_images(image_bytes_list)

    if embedding is None:
        return {
            "success": False,
            "message": "No face detected in the scans. Try better lighting.",
        }

    existing, similarity = find_student_by_face(embedding)
    if existing is not None and similarity > SIMILARITY_THRESHOLD:
        return {
            "success": False,
            "message": "This face is already registered",
        }

    student = create_student_with_face(
        display_name,
        embedding_to_list(embedding),
    )
    token = create_session(student["email"], SESSION_TTL_SECONDS)

    student_id = student["student_id"]

    return {
        "success": True,
        "message": f"{student['name']} enrolled successfully",
        "id": student_id,
        "student_id": student_id,
        "token": token,
        "student": student_public_profile(student),
        "scans_used": len(files),
    }


@app.post("/auth/login")
async def login(file: UploadFile = File(...)):
    image_bytes = await file.read()
    embedding = get_embedding(image_bytes)

    if embedding is None:
        return {"success": False, "message": "No face detected"}

    student, similarity = find_student_by_face(embedding)

    if student is None or similarity <= SIMILARITY_THRESHOLD:
        return {
            "success": False,
            "message": "Face not recognized. Sign up first.",
            "similarity": float(similarity),
        }

    token = create_session(student["email"], SESSION_TTL_SECONDS)

    return {
        "success": True,
        "message": f"Welcome back, {student['name']}",
        "token": token,
        "student": student_public_profile(student),
        "similarity": float(similarity),
    }


@app.get("/auth/me")
def me(student: dict = Depends(require_student)):
    return {
        "success": True,
        "student": student_public_profile(student),
    }


@app.get("/students")
def students_for_teacher():
    return {
        "success": True,
        "students": [
            student_public_profile(student)
            for student in list_students()
        ],
    }


@app.post("/register-face")
async def register_face(
    file: UploadFile = File(...),
    name: str = Form(...),
    student: dict = Depends(require_student),
):
    display_name = name.strip()
    if not display_name:
        return {"success": False, "message": "Name is required"}

    image_bytes = await file.read()

    embedding = get_embedding(image_bytes)

    if embedding is None:
        return {
            "success": False,
            "message": "No face detected"
        }

    updated = upsert_face(
        student["email"],
        embedding_to_list(embedding),
        display_name,
    )

    if updated is None:
        return {"success": False, "message": "Student account not found"}

    return {
        "success": True,
        "message": f"{updated['name']} registered successfully",
        "student": student_public_profile(updated),
        "total_users": len(list_students()),
    }


@app.post("/attendance/start")
def start_attendance(
    request: Request,
    payload: AttendanceStartRequest,
):
    global attendance_active, attendance_started_at, attendance_records, attendance_session_ip, attendance_expected_classroom

    if attendance_active:
        return {
            "success": False,
            "message": "Attendance session is already active",
            "started_at": attendance_started_at,
        }

    attendance_active = True
    attendance_started_at = datetime.now(timezone.utc).isoformat()
    attendance_session_ip = get_client_ip(request)
    attendance_expected_classroom = payload.classroom
    attendance_records = []

    return {
        "success": True,
        "message": "Attendance session started",
        "started_at": attendance_started_at,
        "classroom": attendance_expected_classroom,
    }


@app.post("/attendance/stop")
def stop_attendance():
    global attendance_active, attendance_started_at, attendance_expected_classroom

    if not attendance_active:
        return {
            "success": False,
            "message": "No active attendance session",
        }

    attendance_active = False
    attendance_expected_classroom = None

    payload = attendance_status_public()
    return {
        "success": True,
        "message": "Attendance session stopped",
        "marked_count": payload["marked_count"],
        "marked_students": payload["marked_students"],
        "teacher_ip": payload["teacher_ip"],
    }


@app.get("/attendance/status")
def attendance_status():
    return attendance_status_public()


@app.get("/attendance/snapshot/{email}")
def attendance_snapshot(email: str):
    for record in attendance_records:
        if record["email"] == email:
            snapshot = record.get("snapshot")
            if snapshot:
                return Response(content=snapshot, media_type="image/jpeg")
            break
    raise HTTPException(status_code=404, detail="Snapshot not found")


@app.get("/students/me/status")
def student_status(student: dict = Depends(require_student)):
    email = student["email"]
    already_marked = any(
        record["email"] == email
        for record in attendance_records
    )

    profile = student_public_profile(student)

    return {
        "student_id": email,
        "email": email,
        "name": student["name"],
        "registered": profile["face_registered"],
        "attendance_active": attendance_active,
        "already_marked": already_marked,
    }


@app.post("/students/me/mark-attendance")
async def mark_attendance(
    request: Request,
    file: UploadFile = File(...),
    student: dict = Depends(require_student),
):
    global attendance_records

    email = student["email"]

    if not attendance_active:
        return {
            "success": False,
            "message": "Attendance session is not active",
        }

    if any(record["email"] == email for record in attendance_records):
        return {
            "success": False,
            "message": "Attendance already marked for this session",
        }

    image_bytes = await file.read()
    result = verify_student_face(email, image_bytes)

    if not result.get("success") or not result.get("verified"):
        return result

    marked_at = datetime.now(timezone.utc).isoformat()
    student_ip = get_client_ip(request)
    ip_match = ips_match(attendance_session_ip, student_ip)

    location_result = detect_location(
        image_bytes
    )

    detected_location = location_result["location"]

    status = "Present"
    reason = None

    if detected_location == "Non-Classroom":
        status = "Flagged"
        reason = "Outside Classroom"
    elif attendance_expected_classroom and (
        detected_location != attendance_expected_classroom
    ):
        status = "Flagged"
        reason = "Wrong Classroom"

    attendance_records.append({
        "email": email,
        "name": student["name"],
        "marked_at": marked_at,
        "similarity": result["similarity"],
        "student_ip": student_ip,
        "ip_match": ip_match,
        "snapshot": image_bytes,
        "location": detected_location,
        "location_confidence": location_result["confidence"],
        "status": status,
        "reason": reason,
    })

    return {
        "success": True,
        "verified": True,
        "message": "Attendance marked successfully",
        "similarity": result["similarity"],
        "spoof_confidence": result["spoof_confidence"],
        "marked_at": marked_at,
        "ip_match": ip_match,
        "location": detected_location,
        "location_confidence": location_result["confidence"],
        "status": status,
        "reason": reason,
        "student": student_public_profile(student),
    }


@app.post("/verify-face")
async def verify_face(file: UploadFile = File(...)):
    registered = [
        student
        for student in list_students()
        if student_has_face(student)
    ]

    if len(registered) == 0:
        return {
            "success": False,
            "message": "No registered users found"
        }

    image_bytes = await file.read()

    is_real, spoof_confidence = check_spoof(image_bytes)

    if not is_real:
        return {
            "success": False,
            "verified": False,
            "message": "Spoof attack detected",
            "spoof_confidence": spoof_confidence
        }

    live_embedding = get_embedding(image_bytes)

    if live_embedding is None:
        return {
            "success": False,
            "message": "No face detected"
        }

    best_similarity = 0.0
    detected_person = None
    detected_email = None

    for user in registered:
        similarity = cosine_similarity(
            np.array(user["embedding"]),
            live_embedding,
        )

        if similarity > best_similarity:
            best_similarity = similarity
            detected_person = user["name"]
            detected_email = user["email"]

    verified = best_similarity > SIMILARITY_THRESHOLD

    return {
        "success": True,
        "verified": bool(verified),
        "person": detected_person if verified else "Unknown",
        "email": detected_email if verified else None,
        "similarity": float(best_similarity),
        "spoof_confidence": spoof_confidence
    }

@app.post("/start-attendance")
def start_attendance():

        kv_set(
            "attendance:session",
            json.dumps({
                "active": True,
                "started_at": time.time()
            }),
            ttl_seconds=30,
        )

        return {
            "success": True,
            "message": "Attendance started"
        }


@app.get("/attendance-session")
def attendance_session():

    session = kv_get("attendance:session")

    if not session:

        return {

            "active": False

        }

    return json.loads(session)


def verify_lms_face(embedding: list, image_bytes: bytes) -> dict:
    is_real, spoof_confidence = check_spoof(image_bytes)

    if not is_real:
        return {
            "success": False,
            "verified": False,
            "message": "Spoof attack detected",
            "spoof_confidence": spoof_confidence,
        }

    live_embedding = get_embedding(image_bytes)

    if live_embedding is None:
        return {
            "success": False,
            "message": "No face detected",
        }

    if not embedding:
        return {
            "success": False,
            "message": "Face not registered for this account",
        }

    similarity = cosine_similarity(
        np.array(embedding),
        live_embedding,
    )

    verified = similarity > SIMILARITY_THRESHOLD

    return {
        "success": True,
        "verified": bool(verified),
        "similarity": float(similarity),
        "spoof_confidence": spoof_confidence,
        "message": (
            "Identity verified"
            if verified
            else "Face does not match registered profile"
        ),
    }


register_lms_routes(
    lms_router,
    get_client_ip=get_client_ip,
    verify_lms_face=verify_lms_face,
    average_embedding_from_images=average_embedding_from_images,
    embedding_to_list=embedding_to_list,
    detect_location=detect_location,
    ips_match=ips_match,
)

app.include_router(lms_router)