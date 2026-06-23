# Smoking Detection API Documentation

This document describes the API endpoints for the **Smoking Detection** module (`smokingdetect`).

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

1. [Upload & Analyze Video](#1-upload--analyze-video) (`POST /smokingdetect/upload`)
2. [Get Session History](#2-get-session-history) (`GET /smokingdetect/sessions/history`)
3. [Get Session Events](#3-get-session-events) (`GET /smokingdetect/sessions/{session_id}`)
4. [Get Session Status](#4-get-session-status) (`GET /smokingdetect/sessions/{session_id}/status`)
5. [Stream Annotated Video](#5-stream-annotated-video) (`GET /smokingdetect/sessions/{session_id}/video`)

---

## Endpoint Details

### 1. Upload & Analyze Video
Uploads a video to run the multi-signal AI smoking detection pipeline (analyzing cigarettes, lit tips, and smoke plumes) in the background.

* **URL:** `/smokingdetect/upload`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Files (Form fields):**
    * `file`: `File` (The MP4 or compatible video file to be analyzed)
  * **Form Data (Form fields):**
    * `interval`: `float` (Optional, default `1.0`. Frame sampling rate in seconds)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/smokingdetect/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@security_cam_hallway.mp4" \
  -F "interval=2.0"
```

#### Example Response (`202 Accepted`):
```json
{
  "message": "Smoking detection job submitted successfully.",
  "status": 202,
  "data": {
    "id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
    "job_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
    "status": "pending",
    "overall_status": null,
    "video_out_path": null,
    "interval": 2.0,
    "created_at": "2026-06-22T05:30:00Z",
    "events": []
  }
}
```

> [!NOTE]
> This endpoint kicks off an asynchronous Celery task and immediately returns `202 Accepted` with the new session details. You must poll `/sessions/{session_id}/status` to track execution and obtain final outputs.

---

### 2. Get Session History
Retrieves previous smoking detection sessions scoped by tenant.
* For `admin` and `superadmin` roles, it retrieves all sessions in the tenant namespace.
* For `operator` and `viewer` roles, it retrieves only their own submitted sessions.

* **URL:** `/smokingdetect/sessions/history`
* **Method:** `GET`
* **Headers:** Cookie authentication required

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/smokingdetect/sessions/history" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 smoking detection session(s).",
  "status": 200,
  "data": [
    {
      "id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
      "status": "completed",
      "overall_status": "smoking_confirmed",
      "interval": 2.0,
      "created_at": "2026-06-22T05:30:00Z",
      "total_events": 4,
      "user": {
        "id": "3f82e88a-2253-4b69-873b-f458ff62bb7a",
        "email": "operator@company.com",
        "role": "operator"
      }
    }
  ]
}
```

---

### 3. Get Session Events
Retrieves all detected smoking events for a completed session, sorted chronologically by timestamp.

* **URL:** `/smokingdetect/sessions/{session_id}`
* **Method:** `GET`
* **Path Parameters:**
  * `session_id`: `string (UUID)` (The ID of the smoking detection session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/smokingdetect/sessions/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 2 smoking event(s) for this session.",
  "status": 200,
  "data": [
    {
      "id": "b3e211da-7f88-410a-9d9c-df591d3ba750",
      "session_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
      "timestamp": 12.5,
      "person_id": 1,
      "status": "smoking_confirmed",
      "score": 95,
      "cig_detected": true,
      "tip_detected": true,
      "smoke_detected": true,
      "tip_ratio": 0.88,
      "smoke_area": 1250.5,
      "person_box": [120, 80, 240, 480],
      "cig_box": [180, 200, 195, 215],
      "frame_path": "storage/smoking_detection/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/frames/smoke_12.500s.jpg"
    },
    {
      "id": "e0b51ac2-540c-48c0-bc66-88bfda13cd22",
      "session_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
      "timestamp": 14.5,
      "person_id": 1,
      "status": "holding",
      "score": 40,
      "cig_detected": true,
      "tip_detected": false,
      "smoke_detected": false,
      "tip_ratio": 0.0,
      "smoke_area": 0.0,
      "person_box": [122, 82, 242, 482],
      "cig_box": [182, 202, 197, 217],
      "frame_path": "storage/smoking_detection/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/frames/smoke_14.500s.jpg"
    }
  ]
}
```

> [!TIP]
> The `frame_path` returned for events contains the relative path to the specific extracted frame. To display this frame on the frontend:
> `http://localhost:8000/storage/smoking_detection/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/frames/smoke_12.500s.jpg`

---

### 4. Get Session Status
Polls the execution status and detailed metadata of a smoking detection session.

* **URL:** `/smokingdetect/sessions/{session_id}/status`
* **Method:** `GET`
* **Path Parameters:**
  * `session_id`: `string (UUID)` (The session ID/job ID)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/smokingdetect/sessions/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/status" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Session status retrieved successfully.",
  "status": 200,
  "data": {
    "id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
    "job_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
    "status": "completed",
    "overall_status": "smoking_confirmed",
    "video_out_path": "storage/smoking_detection/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/footage/smoking_detection.mp4",
    "interval": 2.0,
    "created_at": "2026-06-22T05:30:00Z",
    "events": [
      {
        "id": "b3e211da-7f88-410a-9d9c-df591d3ba750",
        "session_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
        "timestamp": 12.5,
        "person_id": 1,
        "status": "smoking_confirmed",
        "score": 95,
        "cig_detected": true,
        "tip_detected": true,
        "smoke_detected": true,
        "tip_ratio": 0.88,
        "smoke_area": 1250.5,
        "person_box": [120, 80, 240, 480],
        "cig_box": [180, 200, 195, 215],
        "frame_path": "storage/smoking_detection/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/frames/smoke_12.500s.jpg"
      }
    ]
  }
}
```

> [!NOTE]
> The `status` field returns `"pending"`, `"processing"`, `"completed"`, or `"failed"`.
> The `overall_status` field returns the highest level classification observed during the session: `"smoking_confirmed"`, `"smoking_likely"`, `"holding"`, or `"clean"`.

---

### 5. Stream Annotated Video
Returns the compiled, annotated output video containing visual indicators (bounding boxes, labels, and timestamps) of detected events.

* **URL:** `/smokingdetect/sessions/{session_id}/video`
* **Method:** `GET`
* **Path Parameters:**
  * `session_id`: `string (UUID)` (The ID of the completed session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/smokingdetect/sessions/a4d36eb8-3df0-4b31-8f55-27a9228d4cb2/video" \
  -o annotated_output.mp4
```

#### Example Response (`200 OK`):
*Returns a binary MP4 file stream (`video/mp4`).*

> [!TIP]
> While you can stream the video through this API, for direct browser playback (e.g. inside an HTML `<video>` tag), it is often easier and more reliable (avoiding cross-origin session/credential issues) to load the statically served path directly:
> `http://localhost:8000/storage/smoking_detection/{session_id}/footage/smoking_detection.mp4`

> [!CAUTION]
> Requesting this endpoint before the session status becomes `"completed"` will result in a `409 Conflict` error.
