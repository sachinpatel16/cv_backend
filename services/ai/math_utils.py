import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Tuple, Optional, Dict, Any

def find_best_face_match(
    ref_embeddings: List[np.ndarray], 
    faces: List[Dict], 
    threshold: float
) -> Tuple[Optional[Dict], float]:
    """
    Compares the embeddings of detected faces in a frame against a list of reference embeddings.
    
    Args:
        ref_embeddings: List of numpy arrays representing search target embeddings.
        faces: List of face dicts, each containing 'embedding' and 'bbox'.
        threshold: Minimum similarity threshold.
        
    Returns:
        best_face: The face dictionary from the input list that has the highest similarity, or None.
        best_sim: The highest similarity score found.
    """
    if not ref_embeddings or not faces:
        return None, -1.0

    frame_embeddings = np.array([face["embedding"] for face in faces])
    best_sim = -1.0
    best_face = None

    for ref_emb in ref_embeddings:
        similarities = cosine_similarity([ref_emb], frame_embeddings)[0]
        for idx, sim in enumerate(similarities):
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_face = faces[idx]

    return best_face, best_sim


def group_timestamps(seconds_list: list, max_gap: float) -> list:
    """Groups consecutive detection seconds into continuous intervals."""
    if not seconds_list:
        return []
    sorted_secs = sorted(seconds_list)
    intervals = []
    start = sorted_secs[0]
    prev = sorted_secs[0]
    for sec in sorted_secs[1:]:
        if sec - prev <= max_gap:
            prev = sec
        else:
            intervals.append((start, prev))
            start = sec
            prev = sec
    intervals.append((start, prev))
    return intervals


def map_similarity_threshold(threshold: float) -> float:
    """
    Maps similarity thresholds from the ReID range [0.70, 1.0] to face recognition [0.35, 0.65].
    If the threshold is in the face recognition range (e.g. < 0.70), it is returned unchanged.
    """
    if threshold >= 0.70:
        return 0.35 + (threshold - 0.70) * 1.0
    return threshold

def find_best_match_in_cache(
    target_embedding: np.ndarray,
    cache: List[Tuple[Any, np.ndarray]],
    threshold: float
) -> Optional[Tuple[Any, float]]:
    """
    Computes cosine similarity in-memory using numpy dot product against cached embeddings.
    Strictly normalizes vectors to unit length to ensure the dot product equals cosine similarity.
    """
    # L2 normalize target embedding
    target_norm = np.linalg.norm(target_embedding)
    if target_norm > 0:
        target_embedding = target_embedding / target_norm

    best_sim = -1.0
    best_entity = None
    for entity, emb in cache:
        # L2 normalize cached embedding to be defensive
        emb_norm = np.linalg.norm(emb)
        emb_normalized = emb / emb_norm if emb_norm > 0 else emb
        
        sim = float(np.dot(target_embedding, emb_normalized))
        if sim >= threshold and sim > best_sim:
            best_sim = sim
            best_entity = entity
    if best_entity is not None:
        return best_entity, best_sim
    return None

