# People Count & Video Tracking API Documentation

This document describes the API endpoints for the **People Count & Video Tracking** module (`peoplecount`). This module relies on the centralized **Gallery** module for uploading and storing raw files.

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
2. [Trigger People Analysis](#2-trigger-people-analysis) (`POST /peoplecount/analyze`)
3. [List People Count Media](#3-list-people-count-media) (`GET /peoplecount/media`)
4. [Get People Count Media Details](#4-get-people-count-media-details) (`GET /peoplecount/media/{media_id}`)
5. [Get Person Track Results](#5-get-person-track-results) (`GET /peoplecount/media/{media_id}/results`)
6. [Delete People Count Media](#6-delete-people-count-media) (`DELETE /peoplecount/media/{media_id}`)

---

## Endpoint Details

### 1. Upload Media (Gallery)
Uploads one or more photos or videos to the centralized gallery. This returns a `gallery_media_id` (indicated as `id` in the response) which is used to trigger analysis in Step 2.

* **URL:** `/gallery/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`

#### Example Response (`201 Created`):
```json
{
  "message": "Successfully uploaded 1 media file(s) to the gallery.",
  "status": 201,
  "data": [
    {
      "id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
      "filename": "revideo.mp4",
      "filepath": "storage/gallery/3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4",
      "processed_filepath": null,
      "media_type": "video",
      "status": "completed",
      "created_at": "2026-06-15T09:35:22.710401Z"
    }
  ]
}
```

---

### 2. Trigger People Analysis
Triggers a background YOLO + ByteTrack people counting and visual tracking analysis on a previously uploaded gallery media item.

* **URL:** `/peoplecount/analyze`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Request JSON Body Fields:**
  * `gallery_media_id`: `UUID` (Required. The unique ID of the gallery media item to analyze)
  * `min_track_frames`: `integer` (Optional. Minimum number of frames a track must be active to be counted. Default: `300`)
  * `track_buffer`: `integer` (Optional. Number of frames to keep a lost track in memory. Default: `150`)
  * `confidence_threshold`: `float` (Optional. YOLO detection confidence threshold. Default: `0.35`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peoplecount/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "gallery_media_id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
    "min_track_frames": 300,
    "track_buffer": 150,
    "confidence_threshold": 0.35
  }'
```

#### Example Response (`200 OK`):
```json
{
  "message": "People counting and tracking triggered successfully.",
  "status": 200,
  "data": {
    "id": "e8a129ef-69b4-449f-b5fb-cc3396a09101",
    "gallery_media_id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
    "status": "processing",
    "total_people_count": null,
    "peak_people_count": null,
    "average_people_count": null,
    "video_duration_seconds": null,
    "filename": "revideo.mp4",
    "filepath": "storage/gallery/3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4",
    "processed_filepath": null,
    "media_type": "video",
    "created_at": "2026-06-15T09:35:22.710401Z"
  }
}
```

---

### 3. List People Count Media
Retrieves all people count analysis sessions scoped to your active tenant.

* **URL:** `/peoplecount/media`
* **Method:** `GET`

---

### 4. Get People Count Media Details
Retrieves detailed metrics and status of a people count analysis session, including track results.

* **URL:** `/peoplecount/media/{media_id}`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the analysis session)

#### Example Response (`200 OK`):
```json
{
  "message": "People count media details retrieved successfully.",
  "status": 200,
  "data": {
    "id": "e8a129ef-69b4-449f-b5fb-cc3396a09101",
    "gallery_media_id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
    "status": "completed",
    "total_people_count": 8,
    "peak_people_count": 5,
    "average_people_count": 3.2,
    "video_duration_seconds": 15.0,
    "filename": "revideo.mp4",
    "filepath": "storage/gallery/3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4",
    "processed_filepath": "storage/gallery/processed_3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4",
    "media_type": "video",
    "created_at": "2026-06-15T09:35:22.710401Z",
    "results": [
      {
        "id": "9a6efca2-69b4-449f-b5fb-cc3396a09ef1",
        "media_id": "e8a129ef-69b4-449f-b5fb-cc3396a09101",
        "track_id": 1,
        "class_name": "person",
        "first_frame": 10,
        "last_frame": 340,
        "total_frames": 330,
        "start_time": 0.33,
        "end_time": 11.33,
        "created_at": "2026-06-15T09:37:00.123452Z"
      }
    ]
  }
}
```

---

### 5. Get Person Track Results
Retrieves only the list of individual object tracking results (including start frame, end frame, duration, class name, and start/end times) for a specific session.

* **URL:** `/peoplecount/media/{media_id}/results`
* **Method:** `GET`

---

### 6. Delete People Count Media
Soft-deletes the analysis session record and its tracked results from the database, and physically deletes the processed tracking video from storage.

* **URL:** `/peoplecount/media/{media_id}`
* **Method:** `DELETE`
