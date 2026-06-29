# Human Activity & Theft Detection API Documentation

This module provides APIs for uploading media (photos/videos), configuring analysis settings (Region of Interest, detection rules for falling, slipping, loitering, occupancy limits, sleeping, walking), and fetching detected alerts and summary statistics.

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
5. [Get Process Status (`GET /activity/media/{media_id}/process`)](#5-get-process-status-get-activitymediamedia_idprocess)
6. [Get Process History (`GET /activity/media/{media_id}/process/history`)](#6-get-process-history-get-activitymediamedia_idprocesshistory)
7. [Delete Activity Media (`DELETE /activity/media/{media_id}`)](#7-delete-activity-media-delete-activitymediamedia_id)
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
      "filepath": "storage/activity_media/e4f5a6b7-89ab-cdef-0123-456789abcdef.mp4",
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
      "filepath": "storage/activity_media/e4f5a6b7-89ab-cdef-0123-456789abcdef.mp4",
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
    "filepath": "storage/activity_media/e4f5a6b7-89ab-cdef-0123-456789abcdef.mp4",
    "status": "pending",
    "created_at": "2026-06-22T17:45:00.123456Z"
  }
}
```

---

### 4. Process Activity Media (`POST /activity/media/{media_id}/process`)

Triggers or re-triggers frame-by-frame activity detection models on the selected media file using the provided configuration payload settings.

* **Method:** `POST`
* **URL:** `/activity/media/{media_id}/process`
* **Content-Type:** `application/json`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Request Body (`ActivityProcessPayload`)
```json
{
  "interval": 0.033,
  "detect_fall": true,
  "detect_aggression": true,
  "detect_intrusion": true,
  "detect_loitering": true,
  "loitering_threshold": 15.0,
  "detect_occupancy": true,
  "occupancy_limit": 5,
  "detect_sleeping": true,
  "detect_walking": true,
  "selected_activities": null,
  "polygon_points": [
    [100, 150],
    [400, 150],
    [450, 500],
    [80, 500]
  ]
}
```

#### Response (`StandardResponse[ActivityMediaResponse]`)
* **HTTP Status Code:** `200 OK`
* **`data`**:
  * **`id`** *(UUID)*: Unique identifier of the uploaded media source.
  * **`filename`** *(string)*: Name of the uploaded file.
  * **`media_type`** *(string)*: `"photo"` or `"video"`.
  * **`filepath`** *(string)*: Server file path.
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
    "filepath": "storage/activity_media/e4f5a6b7-89ab-cdef-0123-456789abcdef.mp4",
    "status": "processing",
    "created_at": "2026-06-22T17:45:00.123456Z"
  }
}
```

---

### 5. Get Process Status (`GET /activity/media/{media_id}/process`)

Retrieves the current execution status and active configuration details of the media file process.

* **Method:** `GET`
* **URL:** `/activity/media/{media_id}/process`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Response (`StandardResponse[ActivityProcessStatusResponse]`)
* **HTTP Status Code:** `200 OK`
* **`data`**:
  * **`media_id`** *(UUID)*: Unique identifier of the media source.
  * **`status`** *(string)*: Execution status (`"pending"`, `"processing"`, `"completed"`, `"failed"`).
  * **`output_filepath`** *(string | null)*: Path to the processed output video/photo if completed.
  * **`config`** *(object | null)*: Config options used, including polygon coordinates and active flags.

#### Example Response
```json
{
  "message": "Activity process status and configuration retrieved successfully.",
  "status": 200,
  "data": {
    "media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "status": "completed",
    "output_filepath": "storage/activity_media/output_e4f5a6b7-89ab-cdef-0123-456789abcdef.mp4",
    "config": {
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
}
```

---

### 6. Get Process History (`GET /activity/media/{media_id}/process/history`)

Retrieves the history of all detected alerts generated during the media analysis process.

* **Method:** `GET`
* **URL:** `/activity/media/{media_id}/process/history`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | Unique identifier of the target media file. |

#### Response (`StandardResponse[List[ActivityAlertResponse]]`)
* **HTTP Status Code:** `200 OK`
* **`data`**: Array of alert objects detected (identical structure to the standard alerts report).

#### Example Response
```json
{
  "message": "Activity process history retrieved successfully.",
  "status": 200,
  "data": [
    {
      "id": "d9e8f7a6-b5c4-3d2e-1f0a-9b8c7d6e5f4a",
      "activity_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
      "track_id": 14,
      "activity_type": "loitering",
      "timestamp": 18.42,
      "bbox": [120, 200, 310, 480],
      "snapshot_path": "storage/activity_alerts/e4f5a6b7-89ab-cdef-0123-456789abcdef_loitering_track14_18420.jpg",
      "severity": "warning",
      "created_at": "2026-06-22T17:45:15.543210Z"
    }
  ]
}
```

---

### 7. Delete Activity Media (`DELETE /activity/media/{media_id}`)

Soft deletes an uploaded activity media file, including all its associated configurations and alert records.

* **Method:** `DELETE`
* **URL:** `/activity/media/{media_id}`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Path | The unique identifier of the media source to delete. |

#### Response (`StandardResponse[None]`)
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

### 8. Get Alerts Report (`GET /activity/report`)

Retrieves logged safety, loitering, and behavior alerts. Supports filtering options.

* **Method:** `GET`
* **URL:** `/activity/report`

#### Request Parameters
| Parameter | Type | In | Description |
| :--- | :--- | :--- | :--- |
| `media_id` | `UUID` | Query | *Optional.* Filter reports to a single uploaded media file. |
| `activity_type` | `string` | Query | *Optional.* Filter by alert behavior: `"falling"`, `"slipping"`, `"loitering"`, `"occupancy_overlimit"`, `"sleeping"`, `"walking"`. |
| `severity` | `string` | Query | *Optional.* Filter by severity: `"info"`, `"warning"`, `"critical"`. |

#### Response (`StandardResponse[List[ActivityAlertResponse]]`)
* **HTTP Status Code:** `200 OK`
* **`data`** Array contains items with the following structure:
  * **`id`** *(UUID)*: Unique identifier of the alert record.
  * **`activity_media_id`** *(UUID)*: Associated source media ID.
  * **`track_id`** *(integer | null)*: Persistent ID of the tracked target/person across frames.
  * **`activity_type`** *(string)*: Type of violation detected (`"falling"`, `"slipping"`, `"loitering"`, `"occupancy_overlimit"`, `"sleeping"`, `"walking"`).
  * **`timestamp`** *(float)*: Time offset (in seconds) in the source video where the alert occurred.
  * **`bbox`** *(array[integer] | null)*: Bounding box array coordinates of the event `[x_min, y_min, x_max, y_max]`.
  * **`snapshot_path`** *(string | null)*: Relative server path to the visual snapshot frame capturing the alert.
  * **`severity`** *(string)*: Threat severity level (`"info"`, `"warning"`, `"critical"`).
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
      "activity_type": "loitering",
      "timestamp": 18.42,
      "bbox": [120, 200, 310, 480],
      "snapshot_path": "storage/activity_alerts/e4f5a6b7-89ab-cdef-0123-456789abcdef_loitering_track14_18420.jpg",
      "severity": "warning",
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
      "falling": 2,
      "slipping": 0,
      "loitering": 9,
      "occupancy_overlimit": 0,
      "sleeping": 2,
      "walking": 1
    },
    "by_severity": {
      "info": 3,
      "warning": 9,
      "critical": 3
    }
  }
}
```
