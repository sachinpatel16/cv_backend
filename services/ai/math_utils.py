import numpy as np
import cv2
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


def is_face_occluded(frame, kps, threshold=15.0):
    """
    Checks if the nose or mouth keypoints are occluded by comparing their chrominance (Cr, Cb)
    to the reference skin tone of the forehead (midpoint between the eyes, shifted slightly up).
    Returns True if an occlusion (non-skin object covering the features) is detected.
    """
    if not kps or len(kps) < 5:
        return False
        
    h, w = frame.shape[:2]
    
    def get_patch_chroma(cx, cy, patch_size=5):
        half = patch_size // 2
        x1 = max(0, int(cx - half))
        x2 = min(w - 1, int(cx + half))
        y1 = max(0, int(cy - half))
        y2 = min(h - 1, int(cy + half))
        
        patch_bgr = frame[y1:y2+1, x1:x2+1]
        if patch_bgr.size == 0:
            return None
            
        patch_ycrcb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2YCrCb)
        mean_ycrcb = cv2.mean(patch_ycrcb)
        return mean_ycrcb[1], mean_ycrcb[2] # Cr, Cb

    # Keypoint indices: 0/1: Eyes, 2: Nose, 3/4: Mouth corners
    le_x, le_y = kps[0]
    re_x, re_y = kps[1]
    
    # Forehead reference point: shifted up from eye midpoint by 25% of inter-pupillary distance
    eye_dist = np.sqrt((re_x - le_x)**2 + (re_y - le_y)**2)
    fh_x = (le_x + re_x) / 2.0
    fh_y = (le_y + re_y) / 2.0 - (eye_dist * 0.25)
    
    fh_y = max(0, min(h - 1, fh_y))
    fh_x = max(0, min(w - 1, fh_x))
    
    fh_chroma = get_patch_chroma(fh_x, fh_y)
    if not fh_chroma:
        return False
    fh_cr, fh_cb = fh_chroma
    
    # Fallback to standard skin tone if forehead is not skin-colored (e.g., hat/hair/extreme light)
    if not (133 <= fh_cr <= 173 and 77 <= fh_cb <= 127):
        fh_cr, fh_cb = 153.0, 102.0
        
    # Check nose tip (2) and mouth corners (3, 4)
    for idx in [2, 3, 4]:
        tx, ty = kps[idx]
        t_chroma = get_patch_chroma(tx, ty)
        if not t_chroma:
            continue
        t_cr, t_cb = t_chroma
        
        # If Cr or Cb difference exceeds the threshold, check if it's still within universal skin bounds
        if abs(fh_cr - t_cr) > threshold or abs(fh_cb - t_cb) > threshold:
            # Safety Net: If the patch is still within the broad, universal human skin bounds,
            # we accept it to prevent false rejections due to skin conditions, burns, or redness.
            is_universal_skin = (133 <= t_cr <= 173) and (77 <= t_cb <= 127)
            if not is_universal_skin:
                return True
            
    return False

