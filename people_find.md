# People Find & Face Recognition API Documentation

This document describes the API endpoints for the **People Search & Face Recognition** module (`peoplefind`). 

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

1. [Upload & Index Event Media](#1-upload--index-event-media) (`POST /peoplefind/media`)
2. [List Event Media](#2-list-event-media) (`GET /peoplefind/media`)
3. [Search by Reference Selfie](#3-search-by-reference-selfie) (`POST /peoplefind/search`)
4. [Search Specific Video On-Demand](#4-search-specific-video-on-demand) (`POST /peoplefind/search-video`)
5. [Get Search Session History](#5-get-search-session-history) (`GET /peoplefind/sessions/history`)
6. [Get Search Session Matches](#6-get-search-session-matches) (`GET /peoplefind/sessions/{session_id}`)
7. [Get Search Session Status](#7-get-search-session-status) (`GET /peoplefind/sessions/{session_id}/status`)
8. [Delete Single Event Media](#8-delete-single-event-media) (`DELETE /peoplefind/media/{media_id}`)
9. [Bulk Delete All Event Media](#9-bulk-delete-all-event-media) (`DELETE /peoplefind/media`)

---

## Endpoint Details

### 1. Upload & Index Event Media
Uploads multiple photos or videos to the database catalog and performs face extraction & embedding indexing scoped to your tenant.

* **URL:** `/peoplefind/media`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (One or more photo or video files)
  * **Form Data (Form fields):**
    * `media_type`: `string` (`"photo"` or `"video"`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peoplefind/media" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@DSC_0022.JPG" \
  -F "media_type=photo"
```

#### Example Response (`201 Created`):
```json
{
  "message": "Successfully processed 1 media file(s).",
  "status": 201,
  "data": [
    {
      "id": "8c36171a-6dac-4004-b4a2-6c54fd22a0e5",
      "filename": "DSC_0022.JPG",
      "media_type": "photo",
      "filepath": "storage/media_sources/ed9e1efb-3152-4a36-b940-037ddbfb36e3.jpg",
      "status": "completed",
      "created_at": "2026-06-11T13:39:45.564000Z"
    }
  ]
}
```

> [!TIP]
> To render the uploaded image on the frontend, combine the backend's root URL with the returned `filepath`:
> `http://localhost:8000/storage/media_sources/ed9e1efb-3152-4a36-b940-037ddbfb36e3.jpg`

---

### 2. List Event Media
Retrieves all non-deleted event photos and videos scoped to your tenant.

* **URL:** `/peoplefind/media`
* **Method:** `GET`
* **Headers:** Cookie authentication required

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplefind/media" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 2 media sources.",
  "status": 200,
  "data": [
    {
      "id": "8c36171a-6dac-4004-b4a2-6c54fd22a0e5",
      "filename": "DSC_0022.JPG",
      "media_type": "photo",
      "filepath": "storage/media_sources/ed9e1efb-3152-4a36-b940-037ddbfb36e3.jpg",
      "status": "completed",
      "created_at": "2026-06-11T13:39:45.564000Z"
    },
    {
      "id": "e5b2f038-fce6-44c7-90b0-5eafd7df984b",
      "filename": "DSC_0011.JPG",
      "media_type": "photo",
      "filepath": "storage/media_sources/36e6d352-3d06-4181-aec3-4355cb929100.jpg",
      "status": "completed",
      "created_at": "2026-06-11T13:39:31.618360Z"
    }
  ]
}
```

---

### 3. Search by Reference Selfie
Uploads a profile picture/selfie, extracts the main face vector, and immediately searches all indexed tenant photos and videos.

* **URL:** `/peoplefind/search`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Files (Form fields):**
    * `file`: `File` (A clear reference selfie image)
  * **Form Data (Form fields):**
    * `threshold`: `float` (Optional, default `0.45`. Matching similarity threshold from `0.0` to `1.0`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peoplefind/search" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@my_selfie.png" \
  -F "threshold=0.50"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Selfie search completed successfully.",
  "status": 200,
  "data": {
    "id": "77f7de7a-42c2-4824-bfbe-d45ff033bb20",
    "job_id": "77f7de7a-42c2-4824-bfbe-d45ff033bb20",
    "selfie_path": "storage/selfies/88ff6e6b-a2c3-4d7a-8fbb-5e662919aa7e.png",
    "threshold": 0.50,
    "status": "completed",
    "created_at": "2026-06-12T12:00:00Z",
    "results": [
      {
        "id": "e0b82df2-cc05-4c07-b649-11c5e933cbdd",
        "session_id": "77f7de7a-42c2-4824-bfbe-d45ff033bb20",
        "similarity": 0.765,
        "bbox": [120, 80, 240, 260],
        "timestamp": null,
        "is_confirmed": null,
        "media_source": {
          "id": "8c36171a-6dac-4004-b4a2-6c54fd22a0e5",
          "filename": "DSC_0022.JPG",
          "media_type": "photo",
          "filepath": "storage/media_sources/ed9e1efb-3152-4a36-b940-037ddbfb36e3.jpg",
          "status": "completed",
          "created_at": "2026-06-11T13:39:45.564Z"
        }
      }
    ]
  }
}
```

---

### 4. Search Specific Video On-Demand
Submits a background job (Celery task) to search inside a specific video for occurrences of the provided selfie.

* **URL:** `/peoplefind/search-video`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Request Parameters:**
  * **Form Data (Form fields):**
    * `video_id`: `string (UUID)` (The database ID of the video to search in)
    * `threshold`: `float` (Optional, default `0.45`. Minimum matching threshold)
  * **Files (Form fields):**
    * `file`: `File` (Reference selfie image)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peoplefind/search-video" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "video_id=2a3b4c5d-6e7f-8a9b-0c1d-2e3f4a5b6c7d" \
  -F "file=@my_selfie.png" \
  -F "threshold=0.45"
```

#### Example Response (`202 Accepted`):
```json
{
  "message": "Video search task submitted successfully in the background.",
  "status": 202,
  "data": {
    "id": "ee5e54d8-790f-488f-b98a-232145b597a1",
    "job_id": "ee5e54d8-790f-488f-b98a-232145b597a1",
    "selfie_path": "storage/selfies/33f21edb-3152-4a36-b940-037ddbfb36e3.png",
    "threshold": 0.45,
    "status": "pending",
    "created_at": "2026-06-12T12:05:00Z",
    "results": []
  }
}
```

---

### 5. Get Search Session History
Retrieves previous search sessions history scoped by tenant.
* For `admin` and `superadmin` roles, it retrieves all sessions in the tenant namespace.
* For `operator` and `viewer` roles, it retrieves only their own search sessions history.

* **URL:** `/peoplefind/sessions/history`
* **Method:** `GET`
* **Headers:** Cookie authentication required

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplefind/sessions/history" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 search session(s) in history.",
  "status": 200,
  "data": [
    {
      "id": "ee5e54d8-790f-488f-b98a-232145b597a1",
      "selfie_path": "storage/selfies/33f21edb-3152-4a36-b940-037ddbfb36e3.png",
      "threshold": 0.45,
      "status": "completed",
      "created_at": "2026-06-12T12:05:00Z",
      "user": {
        "id": "3f82e88a-2253-4b69-873b-f458ff62bb7a",
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "role": "admin"
      },
      "total_matches": 1,
      "matched_images": [
        "storage/media_sources/88ff6e6b-a2c3-4d7a-8fbb-5e662919aa7e.mp4"
      ]
    }
  ]
}
```

---

### 6. Get Search Session Matches
Retrieves all matching media results for a previously submitted/completed search session, sorted by similarity.

* **URL:** `/peoplefind/sessions/{session_id}`
* **Method:** `GET`
* **Path Parameters:**
  * `session_id`: `string (UUID)` (The ID of the search session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplefind/sessions/ee5e54d8-790f-488f-b98a-232145b597a1" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 matches for this search session.",
  "status": 200,
  "data": [
    {
      "id": "e0b82df2-cc05-4c07-b649-11c5e933cbdd",
      "session_id": "ee5e54d8-790f-488f-b98a-232145b597a1",
      "similarity": 0.824,
      "bbox": [200, 150, 310, 280],
      "timestamp": 45.5,
      "media_source": {
        "id": "2a3b4c5d-6e7f-8a9b-0c1d-2e3f4a5b6c7d",
        "filename": "event_recording.mp4",
        "media_type": "video",
        "filepath": "storage/media_sources/88ff6e6b-a2c3-4d7a-8fbb-5e662919aa7e.mp4",
        "status": "completed",
        "created_at": "2026-06-11T13:30:00Z"
      }
    }
  ]
}
```

> [!NOTE]
> For matches inside videos, `timestamp` represents the elapsed time (in seconds) from the beginning of the video where the match occurred.

---

### 7. Get Search Session Status
Fetches the status and detailed metadata of a search session (useful for tracking on-demand background search jobs).

* **URL:** `/peoplefind/sessions/{session_id}/status`
* **Method:** `GET`
* **Path Parameters:**
  * `session_id`: `string (UUID)` (The ID/job_id of the search session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peoplefind/sessions/ee5e54d8-790f-488f-b98a-232145b597a1/status" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Session status retrieved successfully.",
  "status": 200,
  "data": {
    "id": "ee5e54d8-790f-488f-b98a-232145b597a1",
    "job_id": "ee5e54d8-790f-488f-b98a-232145b597a1",
    "selfie_path": "storage/selfies/33f21edb-3152-4a36-b940-037ddbfb36e3.png",
    "threshold": 0.45,
    "status": "completed",
    "created_at": "2026-06-12T12:05:00Z",
    "results": [
      {
        "id": "e0b82df2-cc05-4c07-b649-11c5e933cbdd",
        "session_id": "ee5e54d8-790f-488f-b98a-232145b597a1",
        "similarity": 0.824,
        "bbox": [200, 150, 310, 280],
        "timestamp": 45.5,
        "media_source": {
          "id": "2a3b4c5d-6e7f-8a9b-0c1d-2e3f4a5b6c7d",
          "filename": "event_recording.mp4",
          "media_type": "video",
          "filepath": "storage/media_sources/88ff6e6b-a2c3-4d7a-8fbb-5e662919aa7e.mp4",
          "status": "completed",
          "created_at": "2026-06-11T13:30:00Z"
         }
      }
    ]
  }
}
```

> [!NOTE]
> The `status` field in the response returns `"pending"` during execution, and transitions to `"completed"` or `"failed"` upon task finalization.

---

### 8. Delete Single Event Media
Soft-deletes a single media item, removes its associated index face embeddings, and deletes the physical file from the server storage.

* **URL:** `/peoplefind/media/{media_id}`
* **Method:** `DELETE`
* **Path Parameters:**
  * `media_id`: `string (UUID)` (ID of the media to delete)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/peoplefind/media/8c36171a-6dac-4004-b4a2-6c54fd22a0e5" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Media source and associated face embeddings deleted successfully.",
  "status": 200,
  "data": null
}
```

---

### 9. Bulk Delete All Event Media
Soft-deletes all media sources and index face embeddings for the active tenant namespace, and deletes all physical files from disk.

* **URL:** `/peoplefind/media`
* **Method:** `DELETE`

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/peoplefind/media" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Successfully deleted 4 media source(s) and all associated face embeddings.",
  "status": 200,
  "data": null
}
```
