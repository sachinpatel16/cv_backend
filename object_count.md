# Generic Object Count & Tracking API Documentation

This document describes the API endpoints for the **Generic Object Count & Tracking** module (`objectcount`). This module supports on-demand analysis where you upload media first and trigger analysis runs with customized tracking settings.

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

1. [Upload Media](#1-upload-media) (`POST /objectcount/media`)
2. [Trigger Object Analysis](#2-trigger-object-analysis) (`POST /objectcount/media/{media_id}/analyze`)
3. [List Object Count Media](#3-list-object-count-media) (`GET /objectcount/media`)
4. [Get Object Count Media Details](#4-get-object-count-media-details) (`GET /objectcount/media/{media_id}`)
5. [Get Object Track Results](#5-get-object-track-results) (`GET /objectcount/media/{media_id}/results`)
6. [Delete Object Count Media](#6-delete-object-count-media) (`DELETE /objectcount/media/{media_id}`)

---

## Endpoint Details

### 1. Upload Media
Uploads one or more photos or videos to be tracked. Media is initially saved in a `"pending"` state. You must trigger analysis separately (Step 2).

* **URL:** `/objectcount/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (One or more photo or video files)
  * **Form Data (Form fields):**
    * `media_type`: `string` (`"photo"` or `"video"`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/objectcount/media" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@v2.mp4" \
  -F "media_type=video"
```

#### Example Response (`201 Created`):
```json
{
  "message": "Successfully uploaded 1 media file(s).",
  "status": 201,
  "data": [
    {
      "id": "f357b226-fe93-49c3-98a0-243094f04c39",
      "filename": "v2.mp4",
      "filepath": "storage/objectcount_media/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
      "processed_filepath": null,
      "media_type": "video",
      "status": "pending",
      "classify_gender": false,
      "classify_vehicle": false,
      "classes_to_track": null,
      "total_objects_count": null,
      "peak_objects_count": null,
      "average_objects_count": null,
      "video_duration_seconds": null,
      "report_summary": null,
      "created_at": "2026-06-17T12:35:22.710401Z"
    }
  ]
}
```

> [!NOTE]
> Uploading media only saves the raw file to disk and registers it in the database. No background tasks or models are run at this stage.

---

### 2. Trigger Object Analysis
Triggers a customized background YOLO + BoT-SORT + InsightFace analysis task on a previously uploaded media record.

* **URL:** `/objectcount/media/{media_id}/analyze`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record to analyze)
* **Request JSON Body Fields:**
  * `classes_to_track`: `string[]` (Optional. List of COCO classes to filter for tracking, e.g., `["person", "car", "bus"]`. If null, tracks all supported COCO categories.)
  * `classify_gender`: `boolean` (Optional. If `true`, classifies head crops of tracked people as `Male`/`Female` via InsightFace. Default: `false`)
  * `classify_vehicle`: `boolean` (Optional. If `false`, maps all vehicle classes like `car`, `truck`, `bus`, `motorcycle`, and `bicycle` to a single category `"vehicle"` to minimize tracker count. Default: `false`)
  * `confidence_threshold`: `float` (Optional. YOLO detection confidence threshold. Default: `0.35`)
  * `min_track_frames`: `integer` (Optional. Minimum number of frames a track must be active to be counted in report. Default: `100`)
  * `track_buffer`: `integer` (Optional. Number of frames to keep a lost track in memory. Default: `150`)
  * `gmc_method`: `string` (Optional. Global Motion Compensation method to correct camera motion in tracking, e.g., `"none"`, `"ortho"`, `"aff_sift"`, `"ecc"`. Default: `"none"`)
  * `reid_classes`: `string[]` (Optional. List of COCO classes to apply ReID feature extraction to. Default: `["person"]`)
  * `imgsz`: `integer` (Optional. Frame size/resolution for YOLO detection. Default: `480`)
  * `entry_exit_report`: `boolean` (Optional. Enables counting crossings in both directions relative to a defined line. Default: `false`)
  * `line_coords`: `integer[][]` (Optional. Line coordinates defined as a list of two points, e.g., `[[100, 200], [300, 400]]`. If `entry_exit_report` is enabled but `line_coords` is not defined, it defaults to a horizontal line in the middle of the video.)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/objectcount/media/f357b226-fe93-49c3-98a0-243094f04c39/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "classes_to_track": ["person", "car"],
    "classify_gender": true,
    "classify_vehicle": true,
    "confidence_threshold": 0.35,
    "min_track_frames": 2,
    "track_buffer": 30,
    "gmc_method": "none",
    "reid_classes": ["person"],
    "imgsz": 480,
    "entry_exit_report": true,
    "line_coords": [[0, 360], [1280, 360]]
  }'
```

#### Example Response (`200 OK`):
```json
{
  "message": "Object tracking and classification analysis triggered successfully.",
  "status": 200,
  "data": {
    "id": "f357b226-fe93-49c3-98a0-243094f04c39",
    "filename": "v2.mp4",
    "filepath": "storage/objectcount_media/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
    "processed_filepath": null,
    "media_type": "video",
    "status": "processing",
    "classify_gender": true,
    "classify_vehicle": true,
    "classes_to_track": [
      "person",
      "car"
    ],
    "total_objects_count": null,
    "peak_objects_count": null,
    "average_objects_count": null,
    "video_duration_seconds": null,
    "report_summary": null,
    "progress_percentage": 0,
    "created_at": "2026-06-17T12:35:22.710401Z"
  }
}
```

> [!NOTE]
> Triggering analysis clears any previous track results for this media and launches a Celery worker. The status transitions to `"processing"`. Once tracking finishes, it transitions to `"completed"` or `"failed"`.

---

### 3. List Object Count Media
Retrieves all uploaded object count media items scoped to your active tenant.

* **URL:** `/objectcount/media`
* **Method:** `GET`
* **Headers:** Cookie authentication required

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/objectcount/media" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 media items.",
  "status": 200,
  "data": [
    {
      "id": "f357b226-fe93-49c3-98a0-243094f04c39",
      "filename": "v2.mp4",
      "filepath": "storage/objectcount_media/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
      "processed_filepath": "storage/objectcount_outputs/processed_f357b226-fe93-49c3-98a0-243094f04c39.mp4",
      "media_type": "video",
      "status": "completed",
      "classify_gender": true,
      "classify_vehicle": true,
      "classes_to_track": [
        "person",
        "car"
      ],
      "total_objects_count": 12,
      "peak_objects_count": 8,
      "average_objects_count": 5.42,
      "video_duration_seconds": 11.23,
      "report_summary": {
        "total_unique_objects": 12,
        "peak_objects_count": 8,
        "average_objects_count": 5.42,
        "unique_counts": {
          "person": 7,
          "car": 5
        },
        "gender_breakdown": {
          "male": 4,
          "female": 2,
          "unknown": 1
        },
        "line_crossing_analytics": {
          "line_coords": [[0, 360], [1280, 360]],
          "total_entries": 4,
          "total_exits": 2,
          "class_breakdown": {
            "person": {"entry": 3, "exit": 1},
            "car": {"entry": 1, "exit": 1}
          }
        }
      },
      "progress_percentage": 100,
      "created_at": "2026-06-17T12:35:22.710401Z"
    }
  ]
}
```

---

### 4. Get Object Count Media Details
Retrieves detailed metrics, status, configuration options, and associated individual tracking results of a single media item.

* **URL:** `/objectcount/media/{media_id}`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/objectcount/media/f357b226-fe93-49c3-98a0-243094f04c39" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Object count media details retrieved successfully.",
  "status": 200,
  "data": {
    "id": "f357b226-fe93-49c3-98a0-243094f04c39",
    "filename": "v2.mp4",
    "filepath": "storage/objectcount_media/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
    "processed_filepath": "storage/objectcount_outputs/processed_f357b226-fe93-49c3-98a0-243094f04c39.mp4",
    "media_type": "video",
    "status": "completed",
    "classify_gender": true,
    "classify_vehicle": true,
    "classes_to_track": [
      "person",
      "car"
    ],
    "total_objects_count": 12,
    "peak_objects_count": 8,
    "average_objects_count": 5.42,
    "video_duration_seconds": 11.23,
    "report_summary": {
      "total_unique_objects": 12,
      "peak_objects_count": 8,
      "average_objects_count": 5.42,
      "unique_counts": {
        "person": 7,
        "car": 5
      },
      "gender_breakdown": {
        "male": 4,
        "female": 2,
        "unknown": 1
      }
    },
    "progress_percentage": 100,
    "created_at": "2026-06-17T12:35:22.710401Z",
    "results": [
      {
        "id": "d5482310-0fac-419b-a010-8b9a7b9ef83b",
        "media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
        "track_id": 1,
        "class_name": "person",
        "gender": "Male",
        "first_frame": 0,
        "last_frame": 120,
        "total_frames": 105,
        "start_time": 0.0,
        "end_time": 4.0,
        "created_at": "2026-06-17T12:37:05.122452Z"
      },
      {
        "id": "e5482310-0fac-419b-a010-8b9a7b9ef83c",
        "media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
        "track_id": 2,
        "class_name": "car",
        "gender": null,
        "first_frame": 30,
        "last_frame": 240,
        "total_frames": 210,
        "start_time": 1.0,
        "end_time": 8.0,
        "created_at": "2026-06-17T12:37:05.122452Z"
      }
    ]
  }
}
```

> [!TIP]
> The `processed_filepath` points to the video stream featuring HUD dashboard analytics and bounding boxes. It can be viewed in the browser or video player via:
> `http://localhost:8000/storage/objectcount_outputs/processed_f357b226-fe93-49c3-98a0-243094f04c39.mp4`

---

### 5. Get Object Track Results
Retrieves only the list of individual object tracking results (including start frame, end frame, duration, class name, and optional gender labels) for a specific media source.

* **URL:** `/objectcount/media/{media_id}/results`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/objectcount/media/f357b226-fe93-49c3-98a0-243094f04c39/results" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 2 track result(s) for this media.",
  "status": 200,
  "data": [
    {
      "id": "d5482310-0fac-419b-a010-8b9a7b9ef83b",
      "media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
      "track_id": 1,
      "class_name": "person",
      "gender": "Male",
      "first_frame": 0,
      "last_frame": 120,
      "total_frames": 105,
      "start_time": 0.0,
      "end_time": 4.0,
      "created_at": "2026-06-17T12:37:05.122452Z"
    },
    {
      "id": "e5482310-0fac-419b-a010-8b9a7b9ef83c",
      "media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
      "track_id": 2,
      "class_name": "car",
      "gender": null,
      "first_frame": 30,
      "last_frame": 240,
      "total_frames": 210,
      "start_time": 1.0,
      "end_time": 8.0,
      "created_at": "2026-06-17T12:37:05.122452Z"
    }
  ]
}
```

---

### 6. Delete Object Count Media
Soft-deletes a media record and its tracked results from the database, and physically deletes the source video/photo and its processed tracking video from storage.

* **URL:** `/objectcount/media/{media_id}`
* **Method:** `DELETE`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record to delete)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/objectcount/media/f357b226-fe93-49c3-98a0-243094f04c39" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Object count media and associated tracking results deleted successfully.",
  "status": 200,
  "data": null
}
```
