# Face Analytics & Attendance Module API Documentation

This document describes the API endpoints for the **Face Analytics & Attendance** module (`faceanalytics`). This module provides tools to upload CCTV footage, run background face-tracking and re-identification (ReID) tasks, detect facial occlusions (e.g. masks, hands) to ensure data quality, track unique visitors, and automatically log employee attendance with precise dwell times.

## General API Information
* **Base URL:** `http://localhost:8000/api/v1`
* **Authentication:** Cookie-based JWT. The HTTP request must include the `access_token` cookie.
* **Response Envelope:** All APIs return a standard envelope structure:
  ```json
  {
    "message": "A descriptive message",
    "status": 200,
    "data": ...
  }
  ```

---

## Endpoint Index

1. [Upload Batch CCTV Footage](#1-upload-batch-cctv-footage) (`POST /faceanalytics/upload`)
2. [List Uploaded Videos](#2-list-uploaded-videos) (`GET /faceanalytics/uploads`)
3. [Delete Uploaded Video](#3-delete-uploaded-video) (`DELETE /faceanalytics/uploads/{video_id}`)
4. [Process Batch Sessions](#4-process-batch-sessions) (`POST /faceanalytics/process`)
5. [List Analytics Sessions](#5-list-analytics-sessions) (`GET /faceanalytics/sessions`)
6. [Get Session Details](#6-get-session-details) (`GET /faceanalytics/sessions/{session_id}`)
7. [Get Session Detected People](#7-get-session-detected-people) (`GET /faceanalytics/sessions/{session_id}/people`)
8. [Stream/Download Annotated Video](#8-streamdownload-annotated-video) (`GET /faceanalytics/sessions/{session_id}/video`)
9. [Delete Analytics Session](#9-delete-analytics-session) (`DELETE /faceanalytics/sessions/{session_id}`)
10. [Get Cross-Video Visitor Analytics](#10-get-cross-video-visitor-analytics) (`GET /faceanalytics/visitors`)

---

## Endpoint Details

### 1. Upload Batch CCTV Footage
Uploads up to 10 raw CCTV video files for face analysis. Files are uploaded and stored on disk, ready to be selected for processing.

* **URL:** `/faceanalytics/upload`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Role Allowed:** `admin`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (Select up to 10 video files to upload)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/faceanalytics/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@office_entrance.mp4"
```

#### Example Response (`202 Accepted`):
```json
{
  "message": "Successfully uploaded 1 video file(s).",
  "status": 202,
  "data": [
    {
      "id": "e555b489-b357-470d-abd9-33648e6aec50",
      "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
      "original_name": "office_entrance.mp4",
      "saved_path": "storage/face_analytics_inputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_file_name.mp4",
      "created_at": "2026-06-26T11:16:42.123456Z"
    }
  ]
}
```

---

### 2. List Uploaded Videos
Retrieves all uploaded videos registered under the active tenant.

* **URL:** `/faceanalytics/uploads`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/faceanalytics/uploads" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Successfully retrieved 1 uploaded video(s).",
  "status": 200,
  "data": [
    {
      "id": "e555b489-b357-470d-abd9-33648e6aec50",
      "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
      "original_name": "office_entrance.mp4",
      "saved_path": "storage/face_analytics_inputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_file_name.mp4",
      "created_at": "2026-06-26T11:16:42.123456Z"
    }
  ]
}
```

---

### 3. Delete Uploaded Video
Wipes the uploaded video metadata and physically deletes the source file from storage.

* **URL:** `/faceanalytics/uploads/{video_id}`
* **Method:** `DELETE`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `video_id`: `UUID` (The unique ID of the uploaded video)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/faceanalytics/uploads/e555b489-b357-470d-abd9-33648e6aec50" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Uploaded video and physical file deleted successfully.",
  "status": 200,
  "data": null
}
```

---

### 4. Process Batch Sessions
Creates processing sessions and schedules celery background tasks to analyze selected uploaded videos. You can customize face detection and similarity matching thresholds.

* **URL:** `/faceanalytics/process`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Role Allowed:** `admin`
* **Request JSON Body Fields:**
  * `videos`: `Array[Object]` (Required. Array of videos to process)
    * `video_path`: `string` (Required. Path returned by upload API e.g. `"storage/face_analytics_inputs/..."`)
    * `similarity_threshold`: `float` (Optional. Per-video ReID cosine similarity threshold override. Must be between `0.5` and `1.0`. Default: `0.70`)
    * `confidence_threshold`: `float` (Optional. Per-video face detection confidence threshold override. Must be between `0.1` and `1.0`. Default: `0.3`)
  * `similarity_threshold`: `float` (Optional. Global fallback similarity threshold. Default: `0.70`)
  * `confidence_threshold`: `float` (Optional. Global fallback confidence threshold. Default: `0.3`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/faceanalytics/process" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "videos": [
      {
        "video_path": "storage/face_analytics_inputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_file_name.mp4",
        "similarity_threshold": 0.75,
        "confidence_threshold": 0.35
      }
    ],
    "similarity_threshold": 0.70,
    "confidence_threshold": 0.3
  }'
```

#### Example Response (`202 Accepted`):
```json
{
  "message": "Successfully registered and started processing for 1 session(s).",
  "status": 202,
  "data": [
    {
      "id": "55fa00f0-7bae-450a-86df-a73ac220fbe4",
      "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
      "video_name": "office_entrance.mp4",
      "video_path": "storage/face_analytics_inputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_file_name.mp4",
      "output_video_path": null,
      "status": "pending",
      "similarity_threshold": 0.75,
      "confidence_threshold": 0.35,
      "unique_person_count": null,
      "total_person_count": null,
      "first_time_visitor_count": null,
      "first_time_visitors": null,
      "peak_occupancy": null,
      "average_occupancy": null,
      "occupancy_timeline": null,
      "created_at": "2026-06-26T11:16:42.123456Z",
      "completed_at": null
    }
  ]
}
```

---

### 5. List Analytics Sessions
Retrieves all video analytics runs scoped to the active tenant.

* **URL:** `/faceanalytics/sessions`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/faceanalytics/sessions" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 session(s).",
  "status": 200,
  "data": [
    {
      "id": "55fa00f0-7bae-450a-86df-a73ac220fbe4",
      "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
      "video_name": "office_entrance.mp4",
      "video_path": "storage/face_analytics_inputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_file_name.mp4",
      "output_video_path": "storage/face_analytics_outputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_annotated.mp4",
      "status": "completed",
      "similarity_threshold": 0.75,
      "confidence_threshold": 0.35,
      "unique_person_count": 5,
      "total_person_count": 12,
      "employee_count": 1,
      "visitor_count": 4,
      "first_time_visitor_count": 1,
      "first_time_visitors": [
        {
          "identity_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
          "photo_path": "storage/visitor_crops/crop_visitor_1.jpg",
          "first_seen": 15.40,
          "last_seen": 45.80,
          "dwell_time": 30.40
        }
      ],
      "detected_employees": [
        {
          "id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
          "first_name": "John",
          "last_name": "Doe",
          "employee_code": "EMP101",
          "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
          "first_seen": 12.50,
          "last_seen": 25.00,
          "dwell_time": 12.50
        }
      ],
      "peak_occupancy": 3,
      "average_occupancy": 1.8,
      "occupancy_timeline": [
        { "timestamp": 0.0, "count": 0 },
        { "timestamp": 5.0, "count": 1 },
        { "timestamp": 10.0, "count": 2 }
      ],
      "created_at": "2026-06-26T11:16:42.123456Z",
      "completed_at": "2026-06-26T11:18:42.123456Z"
    }
  ]
}
```

---

### 6. Get Session Details
Retrieves execution metrics, visitor logs, and occupancy charts data for a specific session.

* **URL:** `/faceanalytics/sessions/{session_id}`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the face analytics session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/faceanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Session details retrieved successfully.",
  "status": 200,
  "data": {
    "id": "55fa00f0-7bae-450a-86df-a73ac220fbe4",
    "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
    "video_name": "office_entrance.mp4",
    "video_path": "storage/face_analytics_inputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_file_name.mp4",
    "output_video_path": "storage/face_analytics_outputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/unique_annotated.mp4",
    "status": "completed",
    "similarity_threshold": 0.75,
    "confidence_threshold": 0.35,
    "unique_person_count": 5,
    "total_person_count": 12,
    "employee_count": 1,
    "visitor_count": 4,
    "first_time_visitor_count": 1,
    "first_time_visitors": [
      {
        "identity_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "photo_path": "storage/visitor_crops/crop_visitor_1.jpg",
        "first_seen": 15.40,
        "last_seen": 45.80,
        "dwell_time": 30.40
      }
    ],
    "detected_employees": [
      {
        "id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
        "first_name": "John",
        "last_name": "Doe",
        "employee_code": "EMP101",
        "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
        "first_seen": 12.50,
        "last_seen": 25.00,
        "dwell_time": 12.50
      }
    ],
    "peak_occupancy": 3,
    "average_occupancy": 1.8,
    "occupancy_timeline": [
      { "timestamp": 0.0, "count": 0 },
      { "timestamp": 5.0, "count": 1 },
      { "timestamp": 10.0, "count": 2 }
    ],
    "created_at": "2026-06-26T11:16:42.123456Z",
    "completed_at": "2026-06-26T11:18:42.123456Z"
  }
}
```

---

### 7. Get Session Detected People
Retrieves all unique individuals (both registered employees and anonymous visitor identity crops) detected during analysis of the session.

* **URL:** `/faceanalytics/sessions/{session_id}/people`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/faceanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4/people" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Successfully retrieved 2 detected person(s).",
  "status": 200,
  "data": [
    {
      "identity_id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
      "type": "employee",
      "name": "John Doe",
      "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
      "first_seen": 12.50,
      "last_seen": 25.00,
      "dwell_time": 12.50
    },
    {
      "identity_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "type": "visitor",
      "name": "Visitor #f47a",
      "photo_path": "storage/visitor_crops/crop_visitor_1.jpg",
      "first_seen": 15.40,
      "last_seen": 45.80,
      "dwell_time": 30.40
    }
  ]
}
```

---

### 8. Stream/Download Annotated Video
Streams or downloads the output annotated video file containing tracked face bounding boxes, HUD overlay, and classification tags.

* **URL:** `/faceanalytics/sessions/{session_id}/video`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/faceanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4/video" \
  --output annotated_faces.mp4
```

#### Example Response (`200 OK`):
Returns the raw binary video file stream (`video/mp4`).

---

### 9. Delete Analytics Session
Deletes the session and physically wipes its input video, output annotated video, and visitor facial crop files from server disk storage.

* **URL:** `/faceanalytics/sessions/{session_id}`
* **Method:** `DELETE`
* **Role Allowed:** `admin`
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session to delete)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/faceanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Analytics session and physical video files deleted successfully.",
  "status": 200,
  "data": null
}
```

---

### 10. Get Cross-Video Visitor Analytics
Aggregates visitor suite analytics across all sessions for the active tenant. Provides high-level metrics for unique counts, repeat frequencies, and growth rates.

* **URL:** `/faceanalytics/visitors`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/faceanalytics/visitors" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Cross-video visitor analytics calculated successfully.",
  "status": 200,
  "data": {
    "total_unique_people": 15,
    "repeat_visitors_count": 4,
    "repeat_visitor_rate": 26.67,
    "new_visitors_this_month": 5
  }
}
```
