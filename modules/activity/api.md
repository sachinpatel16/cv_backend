# Human Activity & Theft Detection API Documentation

This module provides APIs for configuring safety and security parameters (Region of Interest polygon, detection rules for falling, slipping, loitering thresholds, occupancy limits, sleeping, walking) on a gallery media item, triggering background pose and behavior tracking, and fetching alerts and summary statistics.

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

---

## Endpoint Index

1. [Upload Media (Gallery)](#1-upload-media-gallery) (`POST /gallery/media`)
2. [Process Activity Media](#2-process-activity-media) (`POST /activity/process`)
3. [Get Process Status](#3-get-process-status) (`GET /activity/process/{gallery_media_id}`)
4. [Get Process History](#4-get-process-history) (`GET /activity/process/{gallery_media_id}/history`)
5. [Get Alerts Report](#5-get-alerts-report) (`GET /activity/report`)
6. [Get Alerts Summary](#6-get-alerts-summary) (`GET /activity/report/summary`)

---

## Endpoint Details

### 1. Upload Media (Gallery)
Uploads raw video/photo files to the shared gallery. This returns a `gallery_media_id` (represented as `id` in the JSON response) to configure and analyze.

* **URL:** `/gallery/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`

---

### 2. Process Activity Media
Triggers background activity and behavior detection on a gallery media item using customized configuration.

* **Method:** `POST`
* **URL:** `/activity/process`
* **Content-Type:** `application/json`

#### Request Body (`ActivityProcessPayload`)
```json
{
  "gallery_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
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

#### Example Response
```json
{
  "message": "Activity detection tracking started successfully.",
  "status": 200,
  "data": {
    "id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "filename": "security_cam_entrance.mp4",
    "filepath": "storage/gallery/security_cam_entrance.mp4",
    "processed_filepath": null,
    "media_type": "video",
    "status": "processing",
    "created_at": "2026-06-22T17:45:00.123456Z"
  }
}
```

---

### 3. Get Process Status
Retrieves execution status and active config settings of the media file process.

* **Method:** `GET`
* **URL:** `/activity/process/{gallery_media_id}`

#### Example Response
```json
{
  "message": "Activity process status and configuration retrieved successfully.",
  "status": 200,
  "data": {
    "gallery_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
    "status": "completed",
    "processed_filepath": "storage/activity_media/output_e4f5a6b7-89ab-cdef-0123-456789abcdef.mp4",
    "config": {
      "id": "c1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c",
      "gallery_media_id": "e4f5a6b7-89ab-cdef-0123-456789abcdef",
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
      ],
      "created_at": "2026-06-22T17:45:01.000000Z"
    }
  }
}
```

---

### 4. Get Process History
Retrieves historical safety alerts and intrusion violations detected for a specific media item.

* **Method:** `GET`
* **URL:** `/activity/process/{gallery_media_id}/history`

---

### 5. Get Alerts Report
Retrieves all safety/theft alerts across the active tenant. Can filter by `gallery_media_id`, alert type, and severity.

* **Method:** `GET`
* **URL:** `/activity/report`

---

### 6. Get Alerts Summary
Generates aggregated status metrics (total alerts, breakdown by type, breakdown by severity) for the active tenant.

* **Method:** `GET`
* **URL:** `/activity/report/summary`
