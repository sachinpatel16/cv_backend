# CCTV People Analytics Module API Documentation

This document describes the API endpoints for the **CCTV People Analytics** module (`peopleanalytics`). This module provides tools to upload CCTV footage, run background tracking and line-crossing tasks, view real-time occupancy timelines, and display detailed reports on visitor statistics and detected individuals.

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

1. [Upload Batch CCTV Footage](#1-upload-batch-cctv-footage) (`POST /peopleanalytics/upload`)
2. [List Uploaded Videos](#2-list-uploaded-videos) (`GET /peopleanalytics/uploads`)
3. [Delete Uploaded Video](#3-delete-uploaded-video) (`DELETE /peopleanalytics/uploads/{video_id}`)
4. [Process Batch Sessions](#4-process-batch-sessions) (`POST /peopleanalytics/process`)
5. [List Analytics Sessions](#5-list-analytics-sessions) (`GET /peopleanalytics/sessions`)
6. [Get Session Details](#6-get-session-details) (`GET /peopleanalytics/sessions/{session_id}`)
7. [Get Session Detected People](#7-get-session-detected-people) (`GET /peopleanalytics/sessions/{session_id}/people`)
8. [Stream/Download Annotated Video](#8-streamdownload-annotated-video) (`GET /peopleanalytics/sessions/{session_id}/video`)
9. [Delete Analytics Session](#9-delete-analytics-session) (`DELETE /peopleanalytics/sessions/{session_id}`)
10. [Get Cross-Video Visitor Analytics](#10-get-cross-video-visitor-analytics) (`GET /peopleanalytics/visitors`)

---

## Endpoint Details

### 1. Upload Batch CCTV Footage
Uploads up to 10 raw CCTV video files for analysis. Files are uploaded and stored in a pending state, ready to be selected for processing.

* **URL:** `/peopleanalytics/upload`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Role Allowed:** `admin`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (Select up to 10 video files to upload)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peopleanalytics/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@office_cctv.mp4"
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
      "original_name": "office_cctv.mp4",
      "saved_path": "storage/people_analytics_inputs/e555b489-b357-470d-abd9-33648e6aec50/office_cctv.mp4",
      "created_at": "2026-06-23T06:40:15.123456Z"
    }
  ]
}
```

---

### 2. List Uploaded Videos
Retrieves all uploaded videos registered under the active tenant.

* **URL:** `/peopleanalytics/uploads`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peopleanalytics/uploads" \
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
      "original_name": "office_cctv.mp4",
      "saved_path": "storage/people_analytics_inputs/e555b489-b357-470d-abd9-33648e6aec50/office_cctv.mp4",
      "created_at": "2026-06-23T06:40:15.123456Z"
    }
  ]
}
```

---

### 3. Delete Uploaded Video
Wipes the uploaded video metadata and physically deletes the source file from storage.

* **URL:** `/peopleanalytics/uploads/{video_id}`
* **Method:** `DELETE`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `video_id`: `UUID` (The unique ID of the uploaded video)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/peopleanalytics/uploads/e555b489-b357-470d-abd9-33648e6aec50" \
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
Creates processing sessions and schedules celery background workers to analyze selected uploaded videos. You can customize coordinates for the entry/exit line, detection thresholds, and selectively toggle computer vision modules.

* **URL:** `/peopleanalytics/process`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Role Allowed:** `admin`
* **Request JSON Body Fields:**
  * `videos`: `Array[Object]` (Required. Array of videos to process)
    * `gallery_media_id`: `string` (Required. UUID of the gallery media item to process)
    * `line_start`: `[integer, integer]` (Optional. Coordinates `[x, y]` of line start for this specific video)
    * `line_end`: `[integer, integer]` (Optional. Coordinates `[x, y]` of line end for this specific video)
    * `similarity_threshold`: `float` (Optional. Local similarity matching override. Default: `0.85`)
    * `confidence_threshold`: `float` (Optional. Local YOLO confidence threshold override. Default: `0.3`)
    * `track_employees`: `boolean` (Optional. Local override to track employee attendance)
    * `register_new_visitors`: `boolean` (Optional. Local override to register unrecognized faces as new visitors)
    * `track_repeat_visitors`: `boolean` (Optional. Local override to recognize repeat visitors)
    * `line_crossing_analysis`: `boolean` (Optional. Local override to track line crossings)
    * `track_occupancy`: `boolean` (Optional. Local override to track occupancy)
  * `line_start`: `[integer, integer]` (Optional. Global fallback start coordinates `[x, y]`)
  * `line_end`: `[integer, integer]` (Optional. Global fallback end coordinates `[x, y]`)
  * `similarity_threshold`: `float` (Optional. Global fallback similarity threshold. Default: `0.85`)
  * `confidence_threshold`: `float` (Optional. Global fallback confidence threshold. Default: `0.3`)
  * `track_employees`: `boolean` (Optional. Global fallback default to track employee attendance. Default: `true`)
  * `register_new_visitors`: `boolean` (Optional. Global fallback default to register new visitors. Default: `true`)
  * `track_repeat_visitors`: `boolean` (Optional. Global fallback default to track repeat visitors. Default: `true`)
  * `line_crossing_analysis`: `boolean` (Optional. Global fallback default to run line crossing. Default: `true`)
  * `track_occupancy`: `boolean` (Optional. Global fallback default to track occupancy. Default: `true`)

#### UI Execution Parameters & Frontend Component Logic

Developers can display these 5 checkboxes/toggles in the UI when initiating video processing. Here is how the selection changes what results are saved and how the UI should conditionally display dashboard widgets when viewing the completed session:

| Toggle Switch / Parameter | Recommended UI Label | Description | Dependent UI Metrics & Components |
| :--- | :--- | :--- | :--- |
| `track_employees` | **Track Employee Attendance** | Runs face recognition against employee database to log check-ins. | Show/Hide the **Employee Attendance list** in results. If disabled, employee metrics show as `N/A`. |
| `register_new_visitors` | **Register New Visitors** | Saves unrecognized faces as new visitors in database. | Show/Hide the **First-Time Visitors** count and photo crop feed. If disabled, new visitors aren't registered. |
| `track_repeat_visitors` | **Recognize Repeat Visitors** | Compares faces to historical visitor list to trace repeat visits. | Show/Hide **Repeat Visitor Rate** card and repeat counts. |
| `line_crossing_analysis` | **Line Crossing Analysis** | Counts people crossing the line (Entry/Exit counts). | Show/Hide **Entry Count** (In) and **Exit Count** (Out) stats cards. Draws crossing line overlays on video canvas. |
| `track_occupancy` | **Track Occupancy Timeline** | Tracks person count over time to build timeline graph. | Show/Hide the **Live Occupancy Timeline Line Chart** and **Peak/Average Occupancy** stats cards. |

> **Note on Dwell Time & Unique People Counts:**
> - **Unique People Count** and individual **Dwell Times** depend entirely on face recognition. If `track_employees`, `register_new_visitors`, and `track_repeat_visitors` are ALL disabled, the Unique People counter widget will display as `N/A`, and individual dwell time timelines will not be shown.
> - **Line Crossing Event Logs:** Detailed per-person crossing log tables can only populate if face recognition is enabled (since logs require an identity ID). If face recognition is disabled but line crossing is enabled, only overall Entry/Exit counts are saved; the detailed per-person timeline table should be hidden in the UI.

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/peopleanalytics/process" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "videos": [
      {
        "gallery_media_id": "e555b489-b357-470d-abd9-33648e6aec50",
        "line_start": [22, 517],
        "line_end": [1237, 698],
        "track_employees": true,
        "register_new_visitors": false,
        "track_repeat_visitors": false,
        "line_crossing_analysis": true,
        "track_occupancy": true
      }
    ],
    "similarity_threshold": 0.85,
    "confidence_threshold": 0.3,
    "track_employees": true,
    "register_new_visitors": true,
    "track_repeat_visitors": true,
    "line_crossing_analysis": true,
    "track_occupancy": true
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
      "video_name": "office_cctv.mp4",
      "video_path": "storage/people_analytics_inputs/e555b489-b357-470d-abd9-33648e6aec50/office_cctv.mp4",
      "output_video_path": null,
      "status": "pending",
      "line_start": [22, 517],
      "line_end": [1237, 698],
      "similarity_threshold": 0.85,
      "confidence_threshold": 0.3,
      "track_employees": true,
      "register_new_visitors": false,
      "track_repeat_visitors": false,
      "line_crossing_analysis": true,
      "track_occupancy": true,
      "unique_person_count": null,
      "total_person_count": null,
      "first_time_visitor_count": null,
      "peak_occupancy": null,
      "average_occupancy": null,
      "entry_count": null,
      "exit_count": null,
      "occupancy_timeline": null,
      "created_at": "2026-06-23T06:56:56.319559Z",
      "completed_at": null
    }
  ]
}
```

---

### 5. List Analytics Sessions
Lists all video analytics runs (completed, pending, processing, or failed) configured for the tenant.

* **URL:** `/peopleanalytics/sessions`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peopleanalytics/sessions" \
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
      "video_name": "office_cctv.mp4",
      "video_path": "storage/people_analytics_inputs/e555b489-b357-470d-abd9-33648e6aec50/office_cctv.mp4",
      "output_video_path": "storage/people_analytics_outputs/e555b489-b357-470d-abd9-33648e6aec50/55fa00f0_annotated.mp4",
      "status": "completed",
      "line_start": [22, 517],
      "line_end": [1237, 698],
      "similarity_threshold": 0.85,
      "confidence_threshold": 0.3,
      "unique_person_count": 18,
      "total_person_count": 23,
      "first_time_visitor_count": 18,
      "peak_occupancy": 9,
      "average_occupancy": 7.31,
      "entry_count": 3,
      "exit_count": 1,
      "occupancy_timeline": [
        {"time_sec": 0.0, "occupancy": 8},
        {"time_sec": 1.0, "occupancy": 8},
        {"time_sec": 2.0, "occupancy": 9}
      ],
      "created_at": "2026-06-23T06:56:56.319559Z",
      "completed_at": "2026-06-23T07:04:03.697262Z"
    }
  ]
}
```

---

### 6. Get Session Details
Retrieves configuration settings, run statuses, and aggregated metrics of a single analytics session.

* **URL:** `/peopleanalytics/sessions/{session_id}`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peopleanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4" \
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
    "video_name": "office_cctv.mp4",
    "video_path": "storage/people_analytics_inputs/e555b489-b357-470d-abd9-33648e6aec50/office_cctv.mp4",
    "output_video_path": "storage/people_analytics_outputs/e555b489-b357-470d-abd9-33648e6aec50/55fa00f0_annotated.mp4",
    "status": "completed",
    "line_start": [22, 517],
    "line_end": [1237, 698],
    "similarity_threshold": 0.85,
    "confidence_threshold": 0.3,
    "unique_person_count": 18,
    "total_person_count": 23,
    "first_time_visitor_count": 18,
    "peak_occupancy": 9,
    "average_occupancy": 7.31,
    "entry_count": 3,
    "exit_count": 1,
    "occupancy_timeline": [
      {"time_sec": 0.0, "occupancy": 8},
      {"time_sec": 1.0, "occupancy": 8},
      {"time_sec": 2.0, "occupancy": 9}
    ],
    "created_at": "2026-06-23T06:56:56.319559Z",
    "completed_at": "2026-06-23T07:04:03.697262Z"
  }
}
```

---

### 7. Get Session Detected People
Retrieves a detailed list of unique visitors or employees detected during the session.

* **URL:** `/peopleanalytics/sessions/{session_id}/people`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peopleanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4/people" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Successfully retrieved 2 detected person(s).",
  "status": 200,
  "data": [
    {
      "identity_id": "75a8ec6f-a7ae-4bea-811a-8510802a251f",
      "type": "visitor",
      "name": "Visitor #75a8",
      "photo_path": "storage/visitor_crops/e555b489-b357-470d-abd9-33648e6aec50/72082d11-8ad6-4903-8e23-5d593530c697.jpg",
      "first_seen": 25.77,
      "last_seen": 27.13,
      "dwell_time": 1.36
    },
    {
      "identity_id": "af8de4bd-eb8e-4934-a43f-f705b580fd2f",
      "type": "visitor",
      "name": "Visitor #af8d",
      "photo_path": "storage/visitor_crops/e555b489-b357-470d-abd9-33648e6aec50/bb8de4bd-eb8e-4934-a43f-f705b580f555.jpg",
      "first_seen": 5.23,
      "last_seen": 14.85,
      "dwell_time": 9.62
    }
  ]
}
```

---

### 8. Stream/Download Annotated Video
Streams the final processed/annotated video file featuring bounding boxes, counting lines, and statistics overlays.

* **URL:** `/peopleanalytics/sessions/{session_id}/video`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peopleanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4/video" \
  -H "accept: application/json" \
  -o annotated_video.mp4
```

---

### 9. Delete Analytics Session
Deletes a session and wipes both input video file and processed annotated output files from disk.

* **URL:** `/peopleanalytics/sessions/{session_id}`
* **Method:** `DELETE`
* **Role Allowed:** `admin`
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/peopleanalytics/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4" \
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
Aggregates analytics dashboard statistics across all runs for the tenant.

* **URL:** `/peopleanalytics/visitors`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/peopleanalytics/visitors" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Cross-video visitor analytics calculated successfully.",
  "status": 200,
  "data": {
    "total_unique_people": 142,
    "repeat_visitors_count": 38,
    "repeat_visitor_rate": 26.76,
    "new_visitors_this_month": 45
  }
}
```

---

## Frontend Integration Guidelines

### 1. File Uploading
* Utilize standard `<input type="file" multiple>` or drag-and-drop zones.
* Restrict batch sizes to a maximum of 10 files per request.
* Display progress bars during the multi-part upload stage.

### 2. Interactive Line Drawing Interface
To let users set custom line coordinates:
* Render the first frame of the video inside an HTML5 `<canvas>` wrapper.
* Capture user click/drag events to establish a line with starting point $(X_1, Y_1)$ and ending point $(X_2, Y_2)$.
* **Scaling Aspect Ratio:** Since coordinates are resolved on the backend using the video's original resolution (e.g. 1920x1080), ensure you scale the canvas coordinate points to match the video's actual height/width dimensions, rather than the browser window size:
  $$\text{Scale Factor } X = \frac{\text{Video Actual Width}}{\text{Canvas Display Width}}$$
  $$\text{Scale Factor } Y = \frac{\text{Video Actual Height}}{\text{Canvas Display Height}}$$
* Send the scaled coordinates as `line_start` and `line_end` in the JSON request body.

### 3. Task Status Polling
* When initiating a run, display the status as `"pending"` or `"processing"`.
* Implement standard polling (`setInterval` running every 3–5 seconds) against `/peopleanalytics/sessions/{session_id}` to retrieve updated statuses.
* Stop polling once the status changes to `"completed"` or `"failed"`.

### 4. Occupancy Timeline Charting
* Parse the `occupancy_timeline` list `[{"time_sec": 0.0, "occupancy": 8}, ...]` from the completed session details.
* Map these values to a continuous Line Chart (using a library like Recharts or Chart.js) with `time_sec` on the X-axis and `occupancy` on the Y-axis.

### 5. Media Stream Player
* Provide an HTML5 `<video>` tag or custom player to stream the processed video:
  ```html
  <video controls width="100%">
    <source src="http://localhost:8000/api/v1/peopleanalytics/sessions/{session_id}/video" type="video/mp4">
    Your browser does not support the video tag.
  </video>
  ```
