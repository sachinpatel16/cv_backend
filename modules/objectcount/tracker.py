import numpy as np
from scipy.optimize import linear_sum_assignment
import logging

logger = logging.getLogger(__name__)

class KalmanFilter:
    """
    A Kalman Filter tracking bounding boxes in center format [xc, yc, w, h].
    State vector: [xc, yc, w, h, vxc, vyc, vw, vh]
    Measurement vector: [xc, yc, w, h]
    Process and measurement noise covariances are dynamically scaled by target bounding box dimensions.
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
            
        # Noise coefficients
        self._std_weight_position = 1.0 / 20.0  # 0.05
        self._std_weight_velocity = 1.0 / 160.0  # 0.00625

    def initiate(self, measurement):
        """
        Initializes the state mean and covariance from the first measurement.
        measurement: [xc, yc, w, h]
        """
        mean = np.zeros(8)
        mean[:4] = measurement
        
        w, h = measurement[2], measurement[3]
        std = [
            2 * self._std_weight_position * w,
            2 * self._std_weight_position * h,
            2 * self._std_weight_position * w,
            2 * self._std_weight_position * h,
            10 * self._std_weight_velocity * w,
            10 * self._std_weight_velocity * h,
            10 * self._std_weight_velocity * w,
            10 * self._std_weight_velocity * h
        ]
        covariance = np.diag(np.square(std))
        
        return mean, covariance

    def predict(self, mean, covariance):
        """
        Predicts the state mean and covariance in the next time step.
        """
        w, h = mean[2], mean[3]
        std = [
            self._std_weight_position * w,
            self._std_weight_position * h,
            self._std_weight_position * w,
            self._std_weight_position * h,
            self._std_weight_velocity * w,
            self._std_weight_velocity * h,
            self._std_weight_velocity * w,
            self._std_weight_velocity * h
        ]
        Q = np.diag(np.square(std))
        
        mean_p = np.dot(self.F, mean)
        covariance_p = np.dot(np.dot(self.F, covariance), self.F.T) + Q
        return mean_p, covariance_p

    def update(self, mean, covariance, measurement):
        """
        Updates the state mean and covariance with a new measurement.
        """
        projected_mean = np.dot(self.H, mean)
        
        w, h = measurement[2], measurement[3]
        std = [
            self._std_weight_position * w,
            self._std_weight_position * h,
            self._std_weight_position * w,
            self._std_weight_position * h
        ]
        R = np.diag(np.square(std))
        
        projected_cov = np.dot(np.dot(self.H, covariance), self.H.T) + R
        K = np.dot(np.dot(covariance, self.H.T), np.linalg.inv(projected_cov))
        
        innovation = measurement - projected_mean
        new_mean = mean + np.dot(K, innovation)
        
        I_KH = np.eye(8) - np.dot(K, self.H)
        new_cov = np.dot(np.dot(I_KH, covariance), I_KH.T) + np.dot(np.dot(K, R), K.T)
        
        return new_mean, new_cov


class STrack:
    """
    State Track class representing an individual tracked object.
    Coordinates are predicted and updated in center-width-height space.
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

    def __init__(self, tlwh, score, class_name, feature=None, gender=None, gender_conf=None):
        self.track_id = STrack.get_next_id()
        self.class_name = class_name
        
        # Gender tracking variables
        self.gender = gender
        self.gender_conf = gender_conf
        self.gender_history = []
        if gender is not None:
            self.gender_history.append((gender, gender_conf))

        self.mean = None
        self.covariance = None
        self.kalman_filter = KalmanFilter()
        
        xc = tlwh[0] + tlwh[2] / 2.0
        yc = tlwh[1] + tlwh[3] / 2.0
        xywh = [xc, yc, tlwh[2], tlwh[3]]
        
        self.mean, self.covariance = self.kalman_filter.initiate(xywh)
        
        self.score = score
        self.is_activated = True
        self.state = "tracked"  # "tracked" or "lost"
        
        self.start_frame = 0
        self.last_frame = 0
        self.visible_frames = 1
        self.lost_frames = 0

        self.smooth_feat = feature.copy() if feature is not None else None
        self.features = [feature] if feature is not None else []

    @property
    def tlwh(self):
        """Get current position in [top-left x, top-left y, width, height] format."""
        if self.mean is None:
            return None
        xc, yc, w, h = self.mean[:4]
        return [xc - w/2.0, yc - h/2.0, w, h]

    @property
    def tlbr(self):
        """Get current position in [top-left x, top-left y, bottom-right x, bottom-right y] format."""
        tlwh = self.tlwh
        if tlwh is None:
            return None
        return [tlwh[0], tlwh[1], tlwh[0] + tlwh[2], tlwh[1] + tlwh[3]]

    @property
    def xywh(self):
        """Get current position in center-coordinate [xc, yc, w, h] format."""
        if self.mean is None:
            return None
        return self.mean[:4].tolist()

    def camera_update(self, H):
        """
        Applies Global Motion Compensation (GMC) to compensate camera movement.
        H is a 2x3 affine transformation matrix mapping from previous frame to current frame.
        """
        if self.mean is None:
            return
            
        R = H[:2, :2]
        t = H[:2, 2]
        
        self.mean[:2] = np.dot(R, self.mean[:2]) + t
        self.mean[4:6] = np.dot(R, self.mean[4:6])
        
        M = np.eye(8)
        M[:2, :2] = R
        M[4:6, 4:6] = R
        self.covariance = np.dot(np.dot(M, self.covariance), M.T)

    def predict(self):
        """Predicts the next state of the track."""
        self.mean, self.covariance = self.kalman_filter.predict(self.mean, self.covariance)
        if self.state == "lost":
            self.lost_frames += 1

    def update(self, new_track, frame_id):
        """
        Updates the track with a new detection.
        """
        new_xywh = new_track.xywh
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, new_xywh
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
                self.smooth_feat /= np.linalg.norm(self.smooth_feat)
            
            self.features.append(new_track.smooth_feat)
            if len(self.features) > 100:
                self.features.pop(0)

        # Update gender history and resolve via majority vote
        if getattr(new_track, "gender", None) is not None:
            self.gender_history.append((new_track.gender, new_track.gender_conf))
            genders = [g for g, c in self.gender_history]
            from collections import Counter
            self.gender = Counter(genders).most_common(1)[0][0]
            matching_confs = [c for g, c in self.gender_history if g == self.gender]
            self.gender_conf = sum(matching_confs) / len(matching_confs) if matching_confs else 0.0


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
    """
    cost_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float32)
    for i, track in enumerate(tracks):
        for j, det in enumerate(detections):
            if track.smooth_feat is not None and det.smooth_feat is not None:
                similarity = np.dot(track.smooth_feat, det.smooth_feat)
                cost_matrix[i, j] = 1.0 - similarity
            else:
                cost_matrix[i, j] = 1.0
    return cost_matrix


class BoTSORTTracker:
    """
    Main BoT-SORT implementation managing track association, creation, and deletion,
    integrating Global Motion Compensation and dynamic noise Kalman Filter.
    """
    def __init__(self, track_thresh=0.25, match_thresh=0.8, track_buffer=30, reid_alpha=0.5, reid_max_dist=0.35):
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self.reid_alpha = reid_alpha
        self.reid_max_dist = reid_max_dist
        self.frame_id = 0
        
        # Track storage
        self.tracked_stracks = []  # Active tracks
        self.lost_stracks = []     # Lost tracks

    def update(self, detections, H, class_name):
        """
        Updates the tracker with new detections from a frame.
        """
        self.frame_id += 1
        
        strack_detections = []
        for det in detections:
            x1, y1, x2, y2 = det["box"]
            tlwh = [x1, y1, x2 - x1, y2 - y1]
            strack_detections.append(STrack(
                tlwh, 
                det["confidence"], 
                class_name, 
                feature=det.get("feature"),
                gender=det.get("gender"),
                gender_conf=det.get("gender_conf")
            ))

        # Split detections into high-confidence and low-confidence groups
        detections_high = []
        detections_low = []
        
        for det in strack_detections:
            if det.score >= self.track_thresh:
                detections_high.append(det)
            else:
                detections_low.append(det)
                
        # Apply Camera Motion Compensation (GMC) to state of active and lost tracks
        for track in self.tracked_stracks:
            track.camera_update(H)
        for track in self.lost_stracks:
            track.camera_update(H)
            
        # Predict new state of all active and lost tracks
        for track in self.tracked_stracks:
            track.predict()
        for track in self.lost_stracks:
            track.predict()
            
        # Pools for association
        strack_pool = self.tracked_stracks + self.lost_stracks
        
        # First association (Associate active/lost tracks with high-score detections)
        dists_iou = iou_distance(strack_pool, detections_high)
        dists_cos = cosine_distance(strack_pool, detections_high)
        
        dists = np.zeros_like(dists_iou)
        for i, track in enumerate(strack_pool):
            alpha = self.reid_alpha if track.state == "tracked" else 0.1
            
            gated_cos = dists_cos[i].copy()
            gated_cos[gated_cos > self.reid_max_dist] = 1.0
            
            for j, det in enumerate(detections_high):
                if track.smooth_feat is None or det.smooth_feat is None:
                    dists[i, j] = dists_iou[i, j]
                else:
                    dists[i, j] = alpha * dists_iou[i, j] + (1 - alpha) * gated_cos[j]
                    
        row_ind, col_ind = linear_sum_assignment(dists)
        
        matches_1 = []
        unmatched_tracks_1 = list(range(len(strack_pool)))
        unmatched_detections_high = list(range(len(detections_high)))
        
        for r, c in zip(row_ind, col_ind):
            if dists[r, c] < self.match_thresh:
                matches_1.append((r, c))
                if r in unmatched_tracks_1:
                    unmatched_tracks_1.remove(r)
                if c in unmatched_detections_high:
                    unmatched_detections_high.remove(c)
                    
        activated_stracks = []
        refind_stracks = []
        
        for r, c in matches_1:
            track = strack_pool[r]
            det = detections_high[c]
            if track.state == "tracked":
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.update(det, self.frame_id)
                refind_stracks.append(track)
                
        # Second association (Associate remaining unmatched active tracks with low-score detections)
        unmatched_track_instances = [strack_pool[i] for i in unmatched_tracks_1 if strack_pool[i].state == "tracked"]
        
        dists_low = iou_distance(unmatched_track_instances, detections_low)
        row_ind_low, col_ind_low = linear_sum_assignment(dists_low)
        
        matches_2 = []
        unmatched_tracks_2 = list(range(len(unmatched_track_instances)))
        
        for r, c in zip(row_ind_low, col_ind_low):
            if dists_low[r, c] < self.match_thresh:
                matches_2.append((r, c))
                if r in unmatched_tracks_2:
                    unmatched_tracks_2.remove(r)
                    
        for r, c in matches_2:
            track = unmatched_track_instances[r]
            det = detections_low[c]
            track.update(det, self.frame_id)
            activated_stracks.append(track)
            
        new_lost_stracks = []
        for r in unmatched_tracks_2:
            track = unmatched_track_instances[r]
            if track.state != "lost":
                track.state = "lost"
                new_lost_stracks.append(track)
                
        # Initialize new tracks from unmatched high-confidence detections
        for c in unmatched_detections_high:
            det = detections_high[c]
            det.start_frame = self.frame_id
            det.last_frame = self.frame_id
            activated_stracks.append(det)
            
        # Update lost tracks list (add new lost and keep those within track_buffer)
        current_lost = []
        for track in self.lost_stracks:
            if track.state == "lost":
                if self.frame_id - track.last_frame <= self.track_buffer:
                    current_lost.append(track)
                
        for track in new_lost_stracks:
            current_lost.append(track)
            
        self.tracked_stracks = activated_stracks + refind_stracks
        self.lost_stracks = current_lost
        
        return [track for track in self.tracked_stracks if track.state == "tracked"]
