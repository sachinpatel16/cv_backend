# Generic Object Count & Tracking API Documentation

This document describes the API endpoints for the **Generic Object Count & Tracking** module (`objectcount`). This module supports on-demand analysis where you upload media first to the centralized gallery and trigger analysis runs with customized tracking settings.

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
2. [Trigger Object Analysis](#2-trigger-object-analysis) (`POST /objectcount/analyze`)
3. [List Object Count Media](#3-list-object-count-media) (`GET /objectcount/media`)
4. [Get Object Count Media Details](#4-get-object-count-media-details) (`GET /objectcount/media/{media_id}`)
5. [Get Object Track Results](#5-get-object-track-results) (`GET /objectcount/media/{media_id}/results`)
6. [Delete Object Count Media](#6-delete-object-count-media) (`DELETE /objectcount/media/{media_id}`)

---

## Endpoint Details

### 1. Upload Media (Gallery)
Uploads one or more photos or videos to the centralized gallery. This returns a `gallery_media_id` (indicated as `id` in the response) which is used to trigger analysis in Step 2.

* **URL:** `/gallery/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (One or more photo or video files)
  * **Form Data (Form fields):**
    * `media_type`: `string` (`"photo"` or `"video"`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/gallery/media" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@v2.mp4" \
  -F "media_type=video"
```

#### Example Response (`201 Created`):
```json
{
  "message": "Successfully uploaded 1 media file(s) to the gallery.",
  "status": 201,
  "data": [
    {
      "id": "f357b226-fe93-49c3-98a0-243094f04c39",
      "filename": "v2.mp4",
      "filepath": "storage/gallery/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
      "processed_filepath": null,
      "media_type": "video",
      "status": "completed",
      "created_at": "2026-06-17T12:35:22.710401Z"
    }
  ]
}
```

---

### 2. Trigger Object Analysis
Triggers a customized background YOLO + BoT-SORT + InsightFace analysis task on a previously uploaded gallery media item.

* **URL:** `/objectcount/analyze`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Request JSON Body Fields:**
  * `gallery_media_id`: `UUID` (Required. The unique ID of the gallery media item to analyze)
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
  * `device`: `string` (Optional. Execution device: `"cpu"` or `"cuda"`. Default: `null` for auto-detect)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/objectcount/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "gallery_media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
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
    "line_coords": [[0, 360], [1280, 360]],
    "device": "cpu"
  }'
```

#### Example Response (`200 OK`):
```json
{
  "message": "Object tracking and classification analysis triggered successfully.",
  "status": 200,
  "data": {
    "id": "a97b2126-fe93-49c3-98a0-243094f04c32",
    "gallery_media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
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
    "filename": "v2.mp4",
    "filepath": "storage/gallery/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
    "processed_filepath": null,
    "media_type": "video",
    "progress_percentage": 0,
    "created_at": "2026-06-17T12:35:22.710401Z"
  }
}
```

> [!NOTE]
> Triggering analysis clears any previous track results for this analysis session and launches a Celery worker. The status transitions to `"processing"`. Once tracking finishes, it transitions to `"completed"` or `"failed"`.

---

### 3. List Object Count Media
Retrieves all object count analysis sessions scoped to your active tenant.

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
      "id": "a97b2126-fe93-49c3-98a0-243094f04c32",
      "gallery_media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
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
      "filename": "v2.mp4",
      "filepath": "storage/gallery/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
      "processed_filepath": "storage/gallery/processed_f357b226-fe93-49c3-98a0-243094f04c39.mp4",
      "media_type": "video",
      "progress_percentage": 100,
      "created_at": "2026-06-17T12:35:22.710401Z"
    }
  ]
}
```

---

### 4. Get Object Count Media Details
Retrieves detailed metrics, status, configuration options, and associated individual tracking results of a single analysis session.

* **URL:** `/objectcount/media/{media_id}`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the analysis session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/objectcount/media/a97b2126-fe93-49c3-98a0-243094f04c32" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Object count media details retrieved successfully.",
  "status": 200,
  "data": {
    "id": "a97b2126-fe93-49c3-98a0-243094f04c32",
    "gallery_media_id": "f357b226-fe93-49c3-98a0-243094f04c39",
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
    "filename": "v2.mp4",
    "filepath": "storage/gallery/f357b226-fe93-49c3-98a0-243094f04c39.mp4",
    "processed_filepath": "storage/gallery/processed_f357b226-fe93-49c3-98a0-243094f04c39.mp4",
    "media_type": "video",
    "progress_percentage": 100,
    "created_at": "2026-06-17T12:35:22.710401Z",
    "results": [
      {
        "id": "d5482310-0fac-419b-a010-8b9a7b9ef83b",
        "media_id": "a97b2126-fe93-49c3-98a0-243094f04c32",
        "track_id": 1,
        "class_name": "person",
        "gender": "Male",
        "first_frame": 0,
        "last_frame": 120,
        "total_frames": 105,
        "start_time": 0.0,
        "end_time": 4.0,
        "created_at": "2026-06-17T12:37:05.122452Z"
      }
    ]
  }
}
```

> [!TIP]
> The `processed_filepath` points to the video stream featuring HUD dashboard analytics and bounding boxes. It is stored directly under the shared gallery:
> `http://localhost:8000/storage/gallery/processed_f357b226-fe93-49c3-98a0-243094f04c39.mp4`

---

### 5. Get Object Track Results
Retrieves the list of individual object tracking results (including start frame, end frame, duration, class name, and optional gender labels) for a specific session.

* **URL:** `/objectcount/media/{media_id}/results`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the analysis session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/objectcount/media/a97b2126-fe93-49c3-98a0-243094f04c32/results" \
  -H "accept: application/json"
```

---

### 6. Delete Object Count Media
Soft-deletes the analysis session record and its tracked results from the database, and physically deletes the processed tracking video from storage. (To delete the raw file, delete it from the `/gallery/media` API).

* **URL:** `/objectcount/media/{media_id}`
* **Method:** `DELETE`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the analysis session to delete)

#### Example Response (`200 OK`):
```json
{
  "message": "Object count media and associated tracking results deleted successfully.",
  "status": 200,
  "data": null
}
```
