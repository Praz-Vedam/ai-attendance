"""Face embedding comparison for browser face-api.js (128-dim descriptors)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

FACE_API_DIM = 128

# face-api FaceMatcher default distance threshold is 0.6; stricter for 1:1 account binding.
FACE_API_DISTANCE_THRESHOLD = float(os.getenv("FACE_API_DISTANCE_THRESHOLD", "0.45"))

FACE_API_ONLY_MESSAGE = (
    "Only browser face-api.js (128-dim) face descriptors are supported. "
    "Re-enroll in the student portal."
)


def normalize_embedding(vec: List[float] | np.ndarray) -> np.ndarray:
    arr = np.array(vec, dtype=np.float64)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr


def is_face_api_embedding(embedding: List[float]) -> bool:
    return len(embedding) == FACE_API_DIM


def _is_number_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, (int, float)) for item in value)
    )


def _to_float_list(value: List[float]) -> List[float]:
    return [float(item) for item in value]


def _average_embeddings(embeddings: List[List[float]]) -> List[float]:
    if not embeddings:
        return []
    size = len(embeddings[0])
    if size != FACE_API_DIM or any(len(embedding) != size for embedding in embeddings):
        return []
    averaged = [0.0] * size
    for embedding in embeddings:
        for index, number in enumerate(embedding):
            averaged[index] += float(number)
    count = float(len(embeddings))
    return [number / count for number in averaged]


def parse_embedding_payload(payload: object) -> List[float]:
    if _is_number_list(payload):
        embedding = _to_float_list(payload)
        return embedding if is_face_api_embedding(embedding) else []

    if not isinstance(payload, dict):
        return []

    for key in ("embedding", "descriptor"):
        value = payload.get(key)
        if _is_number_list(value):
            embedding = _to_float_list(value)
            if is_face_api_embedding(embedding):
                return embedding

    for key in ("embeddings", "descriptors"):
        value = payload.get(key)
        if not isinstance(value, list) or not value:
            continue

        if _is_number_list(value):
            embedding = _to_float_list(value)
            if is_face_api_embedding(embedding):
                return embedding
            continue

        vectors: List[List[float]] = []
        for item in value:
            extracted = parse_embedding_payload(item)
            if extracted:
                vectors.append(extracted)
        averaged = _average_embeddings(vectors)
        if averaged:
            return averaged

    return []


def parse_client_embedding(raw: str) -> List[float]:
    payload = json.loads(raw)
    embedding = parse_embedding_payload(payload)
    if not embedding:
        raise ValueError(FACE_API_ONLY_MESSAGE)
    return embedding


def embedding_format_mismatch_message(stored: List[float], live: List[float]) -> str:
    return (
        f"Face enrollment format mismatch ({len(stored)}-dim stored vs "
        f"{len(live)}-dim live). {FACE_API_ONLY_MESSAGE}"
    )


def euclidean_distance(a: List[float], b: List[float]) -> float:
    return float(np.linalg.norm(normalize_embedding(a) - normalize_embedding(b)))


def cosine_similarity(a: List[float] | np.ndarray, b: List[float] | np.ndarray) -> float:
    a_norm = normalize_embedding(a)
    b_norm = normalize_embedding(b)
    return float(np.dot(a_norm, b_norm))


@dataclass(frozen=True)
class FaceMatchScore:
    verified: bool
    similarity: float
    distance: Optional[float] = None


def score_face_match(stored: List[float], live: List[float]) -> FaceMatchScore:
    if not is_face_api_embedding(stored) or not is_face_api_embedding(live):
        return FaceMatchScore(verified=False, similarity=0.0)

    similarity = cosine_similarity(stored, live)
    distance = euclidean_distance(stored, live)
    return FaceMatchScore(
        verified=distance <= FACE_API_DISTANCE_THRESHOLD,
        similarity=similarity,
        distance=distance,
    )


def compare_embeddings(stored: List[float], live: List[float]) -> Tuple[bool, float]:
    score = score_face_match(stored, live)
    return score.verified, score.similarity
