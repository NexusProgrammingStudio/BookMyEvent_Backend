import math
import os
import pickle  # nosec

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

INDEX_PATH = "../data/"
os.makedirs(INDEX_PATH, exist_ok=True)

embedder = SentenceTransformer("all-MiniLM-L6-v2")


def build_content(doc: dict, doc_type: str) -> str:
    """
    Build string content for embedding.
    Users include past bookings (nested dicts).
    """
    if doc_type == "user":
        # Flatten past bookings
        bookings_text = ""
        for b in doc.get("past_bookings_text", []):
            bookings_text += (
                f"Event: {b.get('Event')}, "
                f"Categories: {b.get('Categories')}, "
                f"Venue: {b.get('Venue')}\n"
            )
        if not bookings_text:
            bookings_text = "No past bookings"

        return (
            f"User: {doc.get('name')} ({doc.get('username')})\n"
            f"Email: {doc.get('email')}\n"
            f"Role: {doc.get('role')}\n"
            f"Interests: {', '.join(doc.get('interests', []))}\n"
            f"Location: ({doc.get('latitude')}, {doc.get('longitude')})\n"
            f"Past bookings:\n{bookings_text}"
        )

    elif doc_type == "event":
        return (
            f"Event: {doc.get('title')}\n"
            f"Description: {doc.get('description')}\n"
            f"Venue: {doc.get('venue')}\n"
            f"Categories: {', '.join(doc.get('categories', []))}\n"
            f"Location: ({doc.get('latitude')}, {doc.get('longitude')})\n"
            f"Start: {doc.get('start_time')}\n"
            f"End: {doc.get('end_time')}"
        )
    else:
        raise ValueError("doc_type must be 'user' or 'event'")


def _get_index_files(doc_type: str) -> tuple[str, str]:
    """Return correct index + metadata file paths per doc_type."""
    index_file = os.path.join(INDEX_PATH, f"events_faiss_index.faiss")
    meta_file = os.path.join(INDEX_PATH, f"events_faiss_metadata.pkl")
    return index_file, meta_file


def ingest_or_update_doc(
    doc: dict,
    doc_type: str,
    replace: bool = True,
) -> bool:
    """
    Single function to ingest or update embeddings for users or events.
    Users can include past bookings for re-embedding.
    """

    # --- Load event index ---
    index_file, meta_file = _get_index_files("event")

    content = build_content(doc, doc_type)
    vector = embedder.encode([content]).astype("float32")
    vector /= np.linalg.norm(vector, axis=1, keepdims=True)

    # Load or create FAISS index
    if os.path.exists(index_file):
        index = faiss.read_index(index_file)
        with open(meta_file, "rb") as f:
            metadata_store = pickle.load(f)  # nosec
    else:
        dim = vector.shape[1]
        index = faiss.IndexIDMap(faiss.IndexFlatL2(dim))
        metadata_store = {}

    # Remove old embeddings if updating
    if replace:
        old_ids = [
            idx
            for idx, meta in metadata_store.items()
            if meta.get("doc_type") == doc_type and meta.get("doc_id") == doc["id"]
        ]
        if old_ids:
            index.remove_ids(np.array(old_ids, dtype=np.int64))
            for oid in old_ids:
                metadata_store.pop(oid, None)

    # Add new embedding
    new_id = max(metadata_store.keys(), default=0) + 1
    index.add_with_ids(vector, np.array([new_id], dtype=np.int64))  # type: ignore

    # Save metadata
    metadata_store[new_id] = {
        "doc_type": doc_type,
        "doc_id": doc["id"],
        "content": content,
        **doc,
    }

    # Persist
    faiss.write_index(index, index_file)
    with open(meta_file, "wb") as f:
        pickle.dump(metadata_store, f)

    return True


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points on Earth (in km).
    """
    R = 6371  # Earth radius km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def recommend_events_for_user(
    user_doc: dict, top_k: int = 5, max_distance_km: int = 50
) -> list[dict]:
    """
    Recommend events for a given user with semantic, location, booking history,
    and interest-based filtering. Includes reasoning for recommendations.
    """

    # --- User embedding ---
    user_content = build_content(user_doc, "user")
    user_vector = embedder.encode([user_content]).astype("float32")
    user_vector /= np.linalg.norm(user_vector, axis=1, keepdims=True)

    # --- Load event index ---
    index_file, meta_file = _get_index_files("event")
    if not os.path.exists(index_file):
        raise ValueError("No event index available. Please ingest events first.")

    index = faiss.read_index(index_file)
    with open(meta_file, "rb") as f:
        metadata_store = pickle.load(f)  # nosec

    # --- Search top candidates ---
    D, I = index.search(user_vector, top_k * 5)  # fetch more, filter later

    recommendations = []
    user_lat, user_lon = user_doc.get("latitude"), user_doc.get("longitude")

    # Extract user preferences
    raw_past_bookings = user_doc.get("past_bookings", [])
    past_booking_categories = {
        b["category"] for b in raw_past_bookings if "category" in b
    }
    interests = set(user_doc.get("interests", []))

    for dist, idx in zip(D[0], I[0]):
        if idx not in metadata_store:
            continue
        meta = metadata_store[idx]

        event_lat, event_lon = meta.get("latitude"), meta.get("longitude")
        location_ok = False
        distance_km = None
        if user_lat and user_lon and event_lat and event_lon:
            distance_km = haversine(user_lat, user_lon, event_lat, event_lon)
            location_ok = distance_km <= max_distance_km

        # --- Base semantic score (higher = better) ---
        semantic_score = float(1 - dist)
        reasons = []

        # --- Location boost ---
        if location_ok and distance_km is not None:
            boost = max(0, (max_distance_km - distance_km) / max_distance_km) * 0.3
            semantic_score += boost
            reasons.append(f"Nearby ({round(distance_km,1)} km)")

        # --- Past booking boost ---
        if meta.get("id") in raw_past_bookings or any(
            cat in past_booking_categories for cat in meta.get("categories", [])
        ):
            semantic_score += 0.2
            reasons.append("Similar to your past bookings")

        # --- Interest match boost ---
        if any(cat in interests for cat in meta.get("categories", [])):
            semantic_score += 0.25
            reasons.append("Matches your interests")

        if semantic_score < 0.1:
            continue  # Skip low-score events

        recommendations.append(
            {
                "event_id": meta["id"],
                "title": meta.get("title"),
                "categories": meta.get("categories"),
                "venue": meta.get("venue"),
                "distance_km": round(distance_km, 1) if distance_km else 0.0,
                "score": float(round(semantic_score, 3)),
                "reason": ", ".join(reasons),
            }
        )

    # --- Sort & limit ---
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    return recommendations[:top_k]
