# People Count & Video Tracking API Documentation

This document describes the API endpoints for the **People Count & Video Tracking** module (`peoplecount`).

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

1. [Upload & Count Media](#1-upload--count-media) (`POST /peoplecount/media`)
2. [List People Count Media](#2-list-people-count-media) (`GET /peoplecount/media`)
3. [Get People Count Media Details](#3-get-people-count-media-details) (`GET /peoplecount/media/{media_id}`)
4. [Get Person Track Results](#4-get-person-track-results) (`GET /peoplecount/media/{media_id}/results`)
5. [Delete People Count Media](#5-delete-people-count-media) (`DELETE /peoplecount/media/{media_id}`)

---

## Endpoint Details

### 1. Upload & Count Media
Uploads one or more photos or videos and starts the background YOLO + ByteTrack people counting and visual tracking processes scoped to your tenant.

* **URL:** `/peoplecount/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (One or more photo or video files)
  * **Form Data (Form fields):**
    * `media_type`: `string` (`"photo"` or `"video"`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peoplecount/media" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@revideo.mp4" \
  -F "media_type=video"
```

#### Example Response (`201 Created`):
```json
{
  "message": "Successfully queued 1 media file(s) for people counting.",
  "status": 201,
  "data": [
    {
      "id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
      "filename": "revideo.mp4",
      "filepath": "storage/peoplecount_media/8c795caf-7521-4b20-b3de-ad86a5fff9e3.mp4",
      "processed_filepath": null,
      "media_type": "video",
      "status": "processing",
      "total_people_count": null,
      "peak_people_count": null,
      "average_people_count": null,
      "video_duration_seconds": null,
      "created_at": "2026-06-15T09:35:22.710401Z"
    }
  ]
}
```

> [!NOTE]
> When a video is uploaded, a background worker is kicked off to execute YOLO detection and ByteTrack tracking. During tracking, the status will show `"processing"`. Once finished, the status transitions to `"completed"` or `"failed"`.

---

### 2. List People Count Media
Retrieves all uploaded people count media items scoped to your active tenant.

* **URL:** `/peoplecount/media`
* **Method:** `GET`
* **Headers:** Cookie authentication required

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplecount/media" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 media items.",
  "status": 200,
  "data": [
    {
      "id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
      "filename": "revideo.mp4",
      "filepath": "storage/peoplecount_media/8c795caf-7521-4b20-b3de-ad86a5fff9e3.mp4",
      "processed_filepath": "storage/peoplecount_outputs/processed_3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4",
      "media_type": "video",
      "status": "completed",
      "total_people_count": 8,
      "peak_people_count": 9,
      "average_people_count": 7.082,
      "video_duration_seconds": 30.06,
      "created_at": "2026-06-15T09:35:22.710401Z"
    }
  ]
}
```

---

### 3. Get People Count Media Details
Retrieves detailed metrics, status, and associated track results of a single people count media file.

* **URL:** `/peoplecount/media/{media_id}`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplecount/media/3ffc67a9-69b4-449f-b5fb-cc3396a09842" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "People count media details retrieved successfully.",
  "status": 200,
  "data": {
    "id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
    "filename": "revideo.mp4",
    "filepath": "storage/peoplecount_media/8c795caf-7521-4b20-b3de-ad86a5fff9e3.mp4",
    "processed_filepath": "storage/peoplecount_outputs/processed_3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4",
    "media_type": "video",
    "status": "completed",
    "total_people_count": 8,
    "peak_people_count": 9,
    "average_people_count": 7.082,
    "video_duration_seconds": 30.06,
    "created_at": "2026-06-15T09:35:22.710401Z",
    "results": [
      {
        "id": "a5482310-0fac-419b-a010-8b9a7b9ef83a",
        "media_id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
        "track_id": 1,
        "class_name": "person",
        "first_frame": 0,
        "last_frame": 901,
        "total_frames": 760,
        "start_time": 0.0,
        "end_time": 30.03,
        "created_at": "2026-06-15T09:37:05.122452Z"
      }
    ]
  }
}
```

> [!TIP]
> The `processed_filepath` points to the annotated video showing bounding boxes and tracked IDs. It can be loaded directly in the browser:  
> `http://localhost:8000/storage/peoplecount_outputs/processed_3ffc67a9-69b4-449f-b5fb-cc3396a09842.mp4`

---

### 4. Get Person Track Results
Retrieves only the list of individual person tracking results and their visibility details (start frame, end frame, duration) for a specific media source.

* **URL:** `/peoplecount/media/{media_id}/results`
* **Method:** `GET`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplecount/media/3ffc67a9-69b4-449f-b5fb-cc3396a09842/results" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 8 track result(s) for this media.",
  "status": 200,
  "data": [
    {
      "id": "a5482310-0fac-419b-a010-8b9a7b9ef83a",
      "media_id": "3ffc67a9-69b4-449f-b5fb-cc3396a09842",
      "track_id": 1,
      "class_name": "person",
      "first_frame": 0,
      "last_frame": 901,
      "total_frames": 760,
      "start_time": 0.0,
      "end_time": 30.03,
      "created_at": "2026-06-15T09:37:05.122452Z"
    }
  ]
}
```

---

### 5. Delete People Count Media
Soft-deletes a media record, its tracked results from the database, and physically deletes the source video/photo and its processed output tracking video from the storage directory.

* **URL:** `/peoplecount/media/{media_id}`
* **Method:** `DELETE`
* **URL Path Variables:**
  * `media_id`: `UUID` (The unique ID of the media record)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/peoplecount/media/3ffc67a9-69b4-449f-b5fb-cc3396a09842" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "People count media and associated tracking results deleted successfully.",
  "status": 200,
  "data": null
}
```
