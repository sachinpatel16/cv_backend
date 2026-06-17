import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Tuple, Optional, Dict

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

