# Human Activity & Theft Detection API Documentation

This module provides APIs for uploading media (photos/videos), configuring analysis settings (Region of Interest, detection rules for fall, aggression, intrusion, loitering, occupancy limits), and fetching detected alerts and summary statistics.

---

## Global API Design Notes

### Authentication
All requests to the Human Activity & Theft Detection module require an authenticated user session.
Include the user token in the request header:
`Authorization: Bearer <your_access_token>`

### Standard Response Wrapper
Every endpoint returns a unified JSON format wrapped in a standard structure:
```json
{
  "message": "Human-readable description of the operation outcome.",
  "status": 200,
  "data": null
}
```
* **`message`** *(string)*: Descriptive feedback from the server.
* **`status`** *(integer)*: Standard HTTP status code.
* **`data`** *(any | null)*: The payload containing the requested resource or result list.

---

## Endpoint Index

1. [Upload Activity Media (`POST /activity/media`)](#1-upload-activity-media-post-activitymedia)
2. [List Activity Media (`GET /activity/media`)](#2-list-activity-media-get-activitymedia)
3. [Get Activity Media Detail (`GET /activity/media/{media_id}`)](#3-get-activity-media-detail-get-activitymediamedia_id)
4. [Process Activity Media (`POST /activity/media/{media_id}/process`)](#4-process-activity-media-post-activitymediamedia_idprocess)
5. [Delete Activity Media (`DELETE /activity/media/{media_id}`)](#5-delete-activity-media-delete-activitymediamedia_id)
6. [Get Activity Configuration (`GET /activity/config/{media_id}`)](#6-get-activity-configuration-get-activityconfigmedia_id)
7. [Configure Activity Rules (`POST /activity/config/{media_id}`)](#7-configure-activity-rules-post-activityconfigmedia_id)
8. [Get Alerts Report (`GET /activity/report`)](#8-get-alerts-report-get-activityreport)
9. [Get Alerts Summary (`GET /activity/report/summary`)](#9-get-alerts-summary-get-activityreportsummary)

---

### 1. Upload Activity Media (`POST /activity/media`)

Uploads multiple photos or videos to the database namespace. Newly uploaded files default to a `"pending"` status and default tracking configurations are created, allowing users to configure rules before triggering analysis.

* **Method:** `POST`
* **URL:** `/activity/media`
* **Content-Type:** `multipart/form-data`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `files` | `List[File]` | Form (Multipart) | One or more photo or video files to process. |
| `media_type` | `string` | Form field | Must be either `"photo"` or `"video"`. |

#### Response (`StandardResponse[List[ActivityMediaResponse]]`)
* **HTTP Status Code:** `201 Created`
* **`data`** Array contains items with the following structure:
  * **`id`** *(UUID)*: Unique identifier of the uploaded media source.
  * **`filename`** *(string)*: Name of the uploaded file.
  * **`media_type`** *(string)*: `"photo"` or `"video"`.
  * **`filepath`** *(string)*: Absolute or relative server file path.
  * **`status`** *(string)*: Processing status (e.g. `"processing"`, `"completed"`, `"failed"`).
  * **`created_at`** *(string)*: Timestamp of the upload in ISO 8601 format.

#### Example Response
```json
{
  "message": "Successfully uploaded 1 media source(s) and submitted tracking task.",
  "status": 201,
  "data": [
    {
      "id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
      "filename": "security_cam_entrance.mp4",
      "media_type": "video",
      "filepath": "uploads/activity/security_cam_entrance.mp4",
      "status": "pending",
      "created_at": "2026-06-22T17:45:00.123456Z"
    }
  ]
}
```

---

### 2. List Activity Media (`GET /activity/media`)

Retrieves all active (non-deleted) activity monitoring media sources uploaded for the current tenant.

* **Method:** `GET`
* **URL:** `/activity/media`

#### Request Parameters
None.

#### Response (`StandardResponse[List[ActivityMediaResponse]]`)
* **HTTP Status Code:** `200 OK`
* **`data`**: Array of media source objects (see upload response structure above).

#### Example Response
```json
{
  "message": "Retrieved 1 media sources.",
  "status": 200,
  "data": [
    {
      "id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
      "filename": "security_cam_entrance.mp4",
      "media_type": "video",
      "filepath": "uploads/activity/security_cam_entrance.mp4",
      "status": "completed",
      "created_at": "2026-06-22T17:45:00.123456Z"
    }
  ]
}
```

---

### 3. Get Activity Media Detail (`GET /activity/media/{media_id}`)

Retrieves detailed information and the current processing status of a single media source.

* **Method:** `GET`
* **URL:** `/activity/media/{media_id}`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Response (`StandardResponse[ActivityMediaResponse]`)
* **HTTP Status Code:** `200 OK`
* **`data`**:
  * **`id`** *(UUID)*: Unique identifier of the uploaded media source.
  * **`filename`** *(string)*: Name of the uploaded file.
  * **`media_type`** *(string)*: `"photo"` or `"video"`.
  * **`filepath`** *(string)*: Absolute or relative server file path.
  * **`status`** *(string)*: Processing status (`"pending"`, `"processing"`, `"completed"`, `"failed"`).
  * **`created_at`** *(string)*: Datetime in ISO 8601 format.

#### Example Response
```json
{
  "message": "Activity media details retrieved successfully.",
  "status": 200,
  "data": {
    "id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "filename": "security_cam_entrance.mp4",
    "media_type": "video",
    "filepath": "uploads/activity/security_cam_entrance.mp4",
    "status": "pending",
    "created_at": "2026-06-22T17:45:00.123456Z"
  }
}
```

---

### 4. Process Activity Media (`POST /activity/media/{media_id}/process`)

Manually triggers frame-by-frame activity detection models on the selected media file.

* **Method:** `POST`
* **URL:** `/activity/media/{media_id}/process`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Response (`StandardResponse[ActivityMediaResponse]`)
* **HTTP Status Code:** `200 OK`
* **`data`**:
  * **`id`** *(UUID)*: Unique identifier of the uploaded media source.
  * **`filename`** *(string)*: Name of the uploaded file.
  * **`media_type`** *(string)*: `"photo"` or `"video"`.
  * **`filepath`** *(string)*: Absolute or relative server file path.
  * **`status`** *(string)*: Processing status (`"processing"`).
  * **`created_at`** *(string)*: Datetime in ISO 8601 format.

#### Example Response
```json
{
  "message": "Activity detection tracking started successfully.",
  "status": 200,
  "data": {
    "id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "filename": "security_cam_entrance.mp4",
    "media_type": "video",
    "filepath": "uploads/activity/security_cam_entrance.mp4",
    "status": "processing",
    "created_at": "2026-06-22T17:45:00.123456Z"
  }
}
```

---

### 5. Delete Activity Media (`DELETE /activity/media/{media_id}`)

Soft deletes an uploaded activity media file, including all its associated configurations and alert records.

* **Method:** `DELETE`
* **URL:** `/activity/media/{media_id}`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | The unique identifier of the media source to delete. |

#### Response (`StandardResponse[null]`)
* **HTTP Status Code:** `200 OK`

#### Example Response
```json
{
  "message": "Activity media and all associated configurations and alerts deleted successfully.",
  "status": 200,
  "data": null
}
```

---

### 6. Get Activity Configuration (`GET /activity/config/{media_id}`)

Fetches safety monitoring rules, toggles, thresholds, and ROI polygon coordinate points configured for a specific media source.

* **Method:** `GET`
* **URL:** `/activity/config/{media_id}`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Response (`StandardResponse[ActivityConfigResponse]`)
* **HTTP Status Code:** `200 OK`
* **`data`** contains the configuration structure:
  * **`id`** *(UUID)*: Unique configuration ID.
  * **`activity_media_id`** *(UUID)*: ID of the corresponding media source.
  * **`detect_fall`** *(boolean)*: Whether fall detection is active.
  * **`detect_aggression`** *(boolean)*: Whether physical aggression detection is active.
  * **`detect_intrusion`** *(boolean)*: Whether Region of Interest (ROI) boundary intrusion detection is active.
  * **`detect_loitering`** *(boolean)*: Whether loitering detection is active.
  * **`loitering_threshold`** *(float)*: Minimum duration (in seconds) someone must remain in the area to trigger a loitering alert.
  * **`detect_occupancy`** *(boolean)*: Whether room capacity limit warning is active.
  * **`occupancy_limit`** *(integer)*: Maximum allowed number of humans in the frame before raising a warning.
  * **`detect_sleeping`** *(boolean)*: Whether horizontal sleeping/lying down detection is active.
  * **`detect_walking`** *(boolean)*: Whether standing/walking posture detection is active.
  * **`polygon_points`** *(array[array[integer]] | null)*: Coordinates of the custom Region of Interest polygon, e.g. `[[x1, y1], [x2, y2], ...]`.
  * **`created_at`** *(string)*: Timestamp configuration was established in ISO 8601 format.

#### Example Response
```json
{
  "message": "Activity configuration retrieved successfully.",
  "status": 200,
  "data": {
    "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "activity_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "detect_fall": true,
    "detect_aggression": true,
    "detect_intrusion": true,
    "detect_loitering": true,
    "loitering_threshold": 15.0,
    "detect_occupancy": true,
    "occupancy_limit": 5,
    "detect_sleeping": true,
    "detect_walking": true,
    "polygon_points": [
      [100, 150],
      [400, 150],
      [450, 500],
      [80, 500]
    ],
    "created_at": "2026-06-22T17:46:30.987654Z"
  }
}
```

---

### 7. Configure Activity Rules (`POST /activity/config/{media_id}`)

Updates the safety configuration rules and the Region of Interest polygon for a media source.
Updating this config **automatically re-runs the background analysis** on the media file using the new rules.

* **Method:** `POST`
* **URL:** `/activity/config/{media_id}`
* **Content-Type:** `application/json`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Request Body (`ActivityConfigPayload`)
```json
{
  "activity_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
  "detect_fall": true,
  "detect_aggression": true,
  "detect_intrusion": true,
  "detect_loitering": true,
  "loitering_threshold": 15.0,
  "detect_occupancy": true,
  "occupancy_limit": 5,
  "detect_sleeping": true,
  "detect_walking": true,
  "polygon_points": [
    [100, 150],
    [400, 150],
    [450, 500],
    [80, 500]
  ]
}
```
*(All configurations default to true/threshold standards if not provided. Send `polygon_points` as `null` to clear ROI filters)*

#### Response (`StandardResponse[ActivityConfigResponse]`)
* **HTTP Status Code:** `200 OK`
* **`data`**: Updated configuration object (see Schema 4 above).

#### Example Response
```json
{
  "message": "Activity rules updated and detection processing re-triggered successfully.",
  "status": 200,
  "data": {
    "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "activity_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "detect_fall": true,
    "detect_aggression": true,
    "detect_intrusion": true,
    "detect_loitering": true,
    "loitering_threshold": 15.0,
    "detect_occupancy": true,
    "occupancy_limit": 5,
    "detect_sleeping": true,
    "detect_walking": true,
    "polygon_points": [
      [100, 150],
      [400, 150],
      [450, 500],
      [80, 500]
    ],
    "created_at": "2026-06-22T17:46:30.987654Z"
  }
}
```

---

### 8. Get Alerts Report (`GET /activity/report`)

Retrieves logged safety, intrusion, and behavior alerts. Supports filtering options.

* **Method:** `GET`
* **URL:** `/activity/report`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Query | *Optional.* Filter reports to a single uploaded media file. |
| `activity_type` | `string` | Query | *Optional.* Filter by alert behavior: `"fall"`, `"aggression"`, `"intrusion"`, `"loitering"`, `"occupancy"`, `"sleeping"`, `"walking"`. |
| `severity` | `string` | Query | *Optional.* Filter by severity: `"info"`, `"low"`, `"medium"`, `"high"`, `"critical"`. |

#### Response (`StandardResponse[List[ActivityAlertResponse]]`)
* **HTTP Status Code:** `200 OK`
* **`data`** Array contains items with the following structure:
  * **`id`** *(UUID)*: Unique identifier of the alert record.
  * **`activity_media_id`** *(UUID)*: Associated source media ID.
  * **`track_id`** *(integer | null)*: Persistent ID of the tracked target/person across frames.
  * **`activity_type`** *(string)*: Type of violation detected (`"fall"`, `"aggression"`, etc.).
  * **`timestamp`** *(float)*: Time offset (in seconds) in the source video where the alert occurred.
  * **`bbox`** *(array[integer] | null)*: Bounding box array coordinates of the event `[x_min, y_min, x_max, y_max]`.
  * **`snapshot_path`** *(string | null)*: Relative server path to the visual snapshot frame capturing the alert.
  * **`severity`** *(string)*: Threat severity level (`"low"`, `"medium"`, `"high"`, `"critical"`).
  * **`created_at`** *(string)*: Datetime when the alert was captured and stored.

#### Example Response
```json
{
  "message": "Retrieved 1 activity alert log(s).",
  "status": 200,
  "data": [
    {
      "id": "d9e8f7a6-b5c4-3d2e-1f0a-9b8c7d6e5f4a",
      "activity_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
      "track_id": 14,
      "activity_type": "intrusion",
      "timestamp": 8.42,
      "bbox": [120, 200, 310, 480],
      "snapshot_path": "uploads/activity/snapshots/d9e8f7a6_intrusion_8.42.jpg",
      "severity": "high",
      "created_at": "2026-06-22T17:45:15.543210Z"
    }
  ]
}
```

---

### 9. Get Alerts Summary (`GET /activity/report/summary`)

Provides aggregated totals of alerts scoped to your tenant. Useful for generating dashboards.

* **Method:** `GET`
* **URL:** `/activity/report/summary`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Query | *Optional.* Filter metrics to a single uploaded media file. |

#### Response (`StandardResponse[ActivityAlertSummary]`)
* **HTTP Status Code:** `200 OK`
* **`data`** contains the summary structure:
  * **`total_alerts`** *(integer)*: Grand total of alerts triggered.
  * **`by_type`** *(object)*: Map of alert counts grouped by behavior type.
  * **`by_severity`** *(object)*: Map of alert counts grouped by severity labels.

#### Example Response
```json
{
  "message": "Activity summary report statistics compiled successfully.",
  "status": 200,
  "data": {
    "total_alerts": 15,
    "by_type": {
      "intrusion": 8,
      "fall": 2,
      "aggression": 1,
      "loitering": 1,
      "occupancy": 0,
      "sleeping": 2,
      "walking": 1
    },
    "by_severity": {
      "info": 3,
      "low": 1,
      "medium": 3,
      "high": 8,
      "critical": 0
    }
  }
}
```
