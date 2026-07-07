# Smoking Detection API Documentation

This document describes the API endpoints for the **Smoking Detection** module (`smokingdetect`). This module relies on the centralized **Gallery** module for storing and uploading raw videos.

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

1. [Upload Media (Gallery)](#1-upload-media-gallery) (`POST /gallery/media`)
2. [Trigger Smoking Analysis](#2-trigger-smoking-analysis) (`POST /smokingdetect/analyze`)
3. [Get Session History](#3-get-session-history) (`GET /smokingdetect/sessions/history`)
4. [Get Session Events](#4-get-session-events) (`GET /smokingdetect/sessions/{session_id}`)
5. [Get Session Status](#5-get-session-status) (`GET /smokingdetect/sessions/{session_id}/status`)
6. [Stream Annotated Video](#6-stream-annotated-video) (`GET /smokingdetect/sessions/{session_id}/video`)
7. [Delete Session](#7-delete-session) (`DELETE /smokingdetect/sessions/{session_id}`)

---

## Endpoint Details

### 1. Upload Media (Gallery)
Uploads video files to the centralized gallery. This returns a `gallery_media_id` (indicated as `id` in the response) which is used to trigger analysis in Step 2.

* **URL:** `/gallery/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`

---

### 2. Trigger Smoking Analysis
Dispatches a background Celery task to run the multi-signal AI smoking detection pipeline (cigarettes, lit tips, smoke plumes) on a gallery video.

* **URL:** `/smokingdetect/analyze`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Request JSON Body Fields:**
  * `gallery_media_id`: `UUID` (Required. The unique ID of the gallery video item to analyze)
  * `interval`: `float` (Optional, default `1.0`. Frame sampling rate in seconds)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/smokingdetect/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "gallery_media_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
    "interval": 2.0
  }'
```

#### Example Response (`202 Accepted`):
```json
{
  "message": "Smoking detection job submitted successfully.",
  "status": 202,
  "data": {
    "id": "c7a8b9c0-1234-5678-abcd-ef0123456789",
    "gallery_media_id": "a4d36eb8-3df0-4b31-8f55-27a9228d4cb2",
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
> This endpoint kicks off an asynchronous Celery task and immediately returns `202 Accepted` with the new session details. You must poll `/sessions/{session_id}/status` to track execution.

---

### 3. Get Session History
Retrieves previous smoking detection sessions scoped by tenant.

* **URL:** `/smokingdetect/sessions/history`
* **Method:** `GET`

---

### 4. Get Session Events
Retrieve all detected smoking events for a completed session, ordered by timestamp.

* **URL:** `/smokingdetect/sessions/{session_id}`
* **Method:** `GET`

---

### 5. Get Session Status
Poll the processing status of a smoking detection session. Returns the full session object including events once the job completes.

* **URL:** `/smokingdetect/sessions/{session_id}/status`
* **Method:** `GET`

---

### 6. Stream Annotated Video
Stream the annotated output video produced by the smoking detection analysis.

* **URL:** `/smokingdetect/sessions/{session_id}/video`
* **Method:** `GET`

---

### 7. Delete Session
Soft deletes a smoking detection session and its associated event records, and removes the annotated video/frames from disk storage.

* **URL:** `/smokingdetect/sessions/{session_id}`
* **Method:** `DELETE`
