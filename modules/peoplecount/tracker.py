import numpy as np
from scipy.optimize import linear_sum_assignment
import logging

logger = logging.getLogger(__name__)

class KalmanFilter:
    """
    A simple constant-velocity Kalman Filter for tracking bounding boxes [x, y, w, h].
    State vector: [x, y, w, h, vx, vy, vw, vh]
    Measurement vector: [x, y, w, h]
    """
    def __init__(self):
        # State transition matrix F
        self.F = np.eye(8)
        for i in range(4):
            self.F[i, i + 4] = 1.0  # dt = 1
            
        # Measurement matrix H
        self.H = np.zeros((4, 8))
        for i in range(4):
            self.H[i, i] = 1.0
            
        # Process noise covariance Q (tuned for tracking stability)
        self.Q = np.eye(8) * 0.05
        self.Q[4:, 4:] *= 0.1  # Velocity changes are slower/smoother
        
        # Measurement noise covariance R (trust in detection quality)
        self.R = np.eye(4) * 1.5

    def initiate(self, measurement):
        """
        Initializes the state mean and covariance from the first measurement.
        """
        mean = np.zeros(8)
        mean[:4] = measurement
        
        # Higher initial uncertainty for velocities
        covariance = np.eye(8) * 10.0
        covariance[:4, :4] = 1.0
        
        return mean, covariance

    def predict(self, mean, covariance):
        """
        Predicts the state mean and covariance in the next time step.
        """
        mean_p = np.dot(self.F, mean)
        covariance_p = np.dot(np.dot(self.F, covariance), self.F.T) + self.Q
        return mean_p, covariance_p

    def update(self, mean, covariance, measurement):
        """
        Updates the state mean and covariance with a new measurement.
        """
        projected_mean = np.dot(self.H, mean)
        projected_cov = np.dot(np.dot(self.H, covariance), self.H.T) + self.R
        
        # Kalman Gain
        K = np.dot(np.dot(covariance, self.H.T), np.linalg.inv(projected_cov))
        
        innovation = measurement - projected_mean
        new_mean = mean + np.dot(K, innovation)
        # Joseph form covariance update for numerical stability
        I_KH = np.eye(8) - np.dot(K, self.H)
        new_cov = np.dot(np.dot(I_KH, covariance), I_KH.T) + np.dot(np.dot(K, self.R), K.T)
        
        return new_mean, new_cov


class STrack:
    """
    State Track class representing an individual tracked object.
    """
    _next_id = 1
    
    @classmethod
    def get_next_id(cls):
        idx = cls._next_id
        cls._next_id += 1
        return idx
        
    @classmethod
    def reset_id_counter(cls):
        cls._next_id = 1

    def __init__(self, tlwh, score, class_name, feature=None):
        self.track_id = STrack.get_next_id()
        self.class_name = class_name
        
        # State variables
        self.mean = None
        self.covariance = None
        
        # Kalman Filter instance
        self.kalman_filter = KalmanFilter()
        
        # Initialize track with the first measurement
        self.mean, self.covariance = self.kalman_filter.initiate(tlwh)
        
        # Status variables
        self.score = score
        self.is_activated = True
        self.state = "tracked"  # "tracked" or "lost"
        
        # Frame tracking
        self.start_frame = 0
        self.last_frame = 0
        self.visible_frames = 1
        self.lost_frames = 0

        # Visual Re-ID appearance features
        self.smooth_feat = feature.copy() if feature is not None else None
        self.features = [feature] if feature is not None else []

    @property
    def tlwh(self):
        """Get current position in [top-left x, top-left y, width, height] format."""
        if self.mean is None:
            return None
        return self.mean[:4].tolist()

    @property
    def tlbr(self):
        """Get current position in [top-left x, top-left y, bottom-right x, bottom-right y] format."""
        tlwh = self.tlwh
        if tlwh is None:
            return None
        return [tlwh[0], tlwh[1], tlwh[0] + tlwh[2], tlwh[1] + tlwh[3]]

    def predict(self):
        """Predicts the next state of the track."""
        self.mean, self.covariance = self.kalman_filter.predict(self.mean, self.covariance)
        if self.state == "lost":
            self.lost_frames += 1

    def update(self, new_track, frame_id):
        """
        Updates the track with a new detection.
        """
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, new_track.tlwh
        )
        self.score = new_track.score
        self.state = "tracked"
        self.is_activated = True
        self.last_frame = frame_id
        self.visible_frames += 1
        self.lost_frames = 0

        # Update visual appearance embedding using exponential moving average (EMA)
        if new_track.smooth_feat is not None:
            if self.smooth_feat is None:
                self.smooth_feat = new_track.smooth_feat.copy()
            else:
                self.smooth_feat = 0.9 * self.smooth_feat + 0.1 * new_track.smooth_feat
                # Re-normalize to unit vector
                self.smooth_feat /= np.linalg.norm(self.smooth_feat)
            
            self.features.append(new_track.smooth_feat)
            if len(self.features) > 100:
                self.features.pop(0)


def calculate_iou(box1, box2):
    """
    Calculates Intersection over Union (IOU) between two bounding boxes.
    Boxes are in format [x1, y1, x2, y2].
    """
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - intersection
    
    if union <= 0.0:
        return 0.0
    return intersection / union


def iou_distance(tracks, detections):
    """
    Calculates the 1 - IOU cost matrix between a list of tracks and detections.
    """
    cost_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float32)
    for i, track in enumerate(tracks):
        track_box = track.tlbr
        for j, det in enumerate(detections):
            det_box = det.tlbr
            cost_matrix[i, j] = 1.0 - calculate_iou(track_box, det_box)
    return cost_matrix


def cosine_distance(tracks, detections):
    """
    Calculates the cosine distance matrix between a list of tracks and detections.
    Tracks and detections features are L2-normalized.
    """
    cost_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float32)
    for i, track in enumerate(tracks):
        for j, det in enumerate(detections):
            if track.smooth_feat is not None and det.smooth_feat is not None:
                # Cosine distance is 1.0 - cosine_similarity. Since vectors are L2-normalized,
                # similarity is simply the dot product.
                similarity = np.dot(track.smooth_feat, det.smooth_feat)
                cost_matrix[i, j] = 1.0 - similarity
            else:
                cost_matrix[i, j] = 1.0  # Max distance if either feature is missing
    return cost_matrix


class BYTETracker:
    """
    Main ByteTrack implementation managing track association, creation, and deletion.
    """
    def __init__(self, track_thresh=0.25, match_thresh=0.8, track_buffer=30, reid_alpha=0.5, reid_max_dist=0.35):
        """
        Initializes the ByteTrack tracker.
        
        Args:
            track_thresh (float): Threshold to separate high and low score detections.
            match_thresh (float): Maximum allowed distance (1 - IOU) for a valid match.
            track_buffer (int): Max number of frames to keep a lost track in memory.
            reid_alpha (float): Weight for active tracks IoU vs Cosine distance.
            reid_max_dist (float): Threshold above which visual matches are gated.
        """
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self.reid_alpha = reid_alpha
        self.reid_max_dist = reid_max_dist
        self.frame_id = 0
        
        # Track storage
        self.tracked_stracks = []  # Active tracks
        self.lost_stracks = []     # Lost tracks

    def update(self, detections, class_name):
        """
        Updates the tracker with new detections from a frame.
        
        Args:
            detections (list of dicts): Bounding boxes, confidence scores, and optional features.
                                        Each dict must have:
                                        - 'box': [x1, y1, x2, y2]
                                        - 'confidence': float
                                        - 'feature': np.ndarray (optional)
            class_name (str): The class name of the detections.
                                        
        Returns:
            list of STrack: Currently active and visible tracks.
        """
        self.frame_id += 1
        
        # Convert incoming detections to STrack instances
        strack_detections = []
        for det in detections:
            x1, y1, x2, y2 = det["box"]
            tlwh = [x1, y1, x2 - x1, y2 - y1]
            strack_detections.append(STrack(tlwh, det["confidence"], class_name, feature=det.get("feature")))
            
        # Step 1: Split detections into high-confidence and low-confidence groups
        detections_high = []
        detections_low = []
        
        for det in strack_detections:
            if det.score >= self.track_thresh:
                detections_high.append(det)
            else:
                detections_low.append(det)
                
        # Step 2: Predict new state of all active and lost tracks
        for track in self.tracked_stracks:
            track.predict()
        for track in self.lost_stracks:
            track.predict()
            
        # Pools for association
        strack_pool = self.tracked_stracks + self.lost_stracks
        
        # Step 3: First association (Associate active/lost tracks with high-score detections)
        dists_iou = iou_distance(strack_pool, detections_high)
        dists_cos = cosine_distance(strack_pool, detections_high)
        
        # Compute combined distance matrix
        dists = np.zeros_like(dists_iou)
        for i, track in enumerate(strack_pool):
            # Active tracks balance IoU & Cosine.
            # Lost tracks rely heavily on Cosine (90%) to account for potential Kalman Filter drift.
            alpha = self.reid_alpha if track.state == "tracked" else 0.1
            
            # Gate cosine distance at reid_max_dist
            gated_cos = dists_cos[i].copy()
            gated_cos[gated_cos > self.reid_max_dist] = 1.0
            
            for j, det in enumerate(detections_high):
                if track.smooth_feat is None or det.smooth_feat is None:
                    # Fallback to pure IoU if visual features are missing
                    dists[i, j] = dists_iou[i, j]
                else:
                    dists[i, j] = alpha * dists_iou[i, j] + (1 - alpha) * gated_cos[j]
                    
        # Apply Hungarian algorithm
        row_ind, col_ind = linear_sum_assignment(dists)
        
        matches_1 = []
        unmatched_tracks_1 = list(range(len(strack_pool)))
        unmatched_detections_high = list(range(len(detections_high)))
        
        for r, c in zip(row_ind, col_ind):
            # Only match if the combined distance is below match_thresh
            if dists[r, c] < self.match_thresh:
                matches_1.append((r, c))
                if r in unmatched_tracks_1:
                    unmatched_tracks_1.remove(r)
                if c in unmatched_detections_high:
                    unmatched_detections_high.remove(c)
                    
        # Apply updates for First Association matches
        activated_stracks = []
        refind_stracks = []
        
        for r, c in matches_1:
            track = strack_pool[r]
            det = detections_high[c]
            if track.state == "tracked":
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                # Track was lost and is now re-found
                track.update(det, self.frame_id)
                refind_stracks.append(track)
                
        # Step 4: Second association (Associate remaining unmatched tracks with low-score detections)
        unmatched_track_instances = [strack_pool[i] for i in unmatched_tracks_1 if strack_pool[i].state == "tracked"]
        
        dists_low = iou_distance(unmatched_track_instances, detections_low)
        row_ind_low, col_ind_low = linear_sum_assignment(dists_low)
        
        matches_2 = []
        unmatched_tracks_2 = list(range(len(unmatched_track_instances)))
        
        for r, c in zip(row_ind_low, col_ind_low):
            # Low score association threshold can be slightly higher (less strict match)
            if dists_low[r, c] < self.match_thresh:
                matches_2.append((r, c))
                if r in unmatched_tracks_2:
                    unmatched_tracks_2.remove(r)
                    
        # Apply updates for Second Association matches
        for r, c in matches_2:
            track = unmatched_track_instances[r]
            det = detections_low[c]
            track.update(det, self.frame_id)
            activated_stracks.append(track)
            
        # Step 5: Mark unmatched tracks from Second Association as Lost
        new_lost_stracks = []
        for r in unmatched_tracks_2:
            track = unmatched_track_instances[r]
            if track.state != "lost":
                track.state = "lost"
                new_lost_stracks.append(track)
                
        # Step 6: Initialize new tracks from unmatched high-confidence detections
        for c in unmatched_detections_high:
            det = detections_high[c]
            # Create a brand new track
            det.start_frame = self.frame_id
            det.last_frame = self.frame_id
            activated_stracks.append(det)
            
        # Step 7: Update lost tracks list (add new lost and keep those within track_buffer)
        current_lost = []
        for track in self.lost_stracks:
            # Only keep it in the lost pool if it is still in the lost state (not re-found)
            if track.state == "lost":
                # Keep if within track_buffer
                if self.frame_id - track.last_frame <= self.track_buffer:
                    current_lost.append(track)
                
        for track in new_lost_stracks:
            current_lost.append(track)
            
        # Remove old lost tracks that exceeded buffer
        # (These are effectively deleted from the tracker completely)
        
        # Step 8: Update tracking storage state
        self.tracked_stracks = activated_stracks + refind_stracks
        self.lost_stracks = current_lost
        
        # Return only the active (currently visible) tracks for drawing
        return [track for track in self.tracked_stracks if track.state == "tracked"]
