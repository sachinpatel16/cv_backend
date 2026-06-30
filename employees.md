# Employee Registry & Attendance Module API Documentation

This document describes the API endpoints for the **Employee Registry & Attendance** module (`employees`). This module provides tools to register employees, update profiles with face recognition embeddings, filter attendance logs by date ranges, mark attendance via group photos, and upload standalone check-in/check-out videos.

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

### Core Employee Profiles
1. [Register New Employee](#1-register-new-employee) (`POST /employees`)
2. [List Registered Employees](#2-list-registered-employees) (`GET /employees`)
3. [Get Employee Profile Details](#3-get-employee-profile-details) (`GET /employees/{employee_id}`)
4. [Update Employee Profile](#4-update-employee-profile) (`PUT /employees/{employee_id}`)
5. [Delete Employee Profile](#5-delete-employee-profile) (`DELETE /employees/{employee_id}`)

### Attendance Logging & Analytics
6. [Get Attendance by Date Range](#6-get-attendance-by-date-range) (`GET /employees/attendance`)
7. [Get Session Employee Attendance](#7-get-session-employee-attendance) (`GET /employees/sessions/{session_id}/attendance`)
8. [Mark Group Photo Attendance](#8-mark-group-photo-attendance) (`POST /employees/attendance/photo`)

### Standalone Video Attendance
9. [Upload Attendance Videos](#9-upload-attendance-videos) (`POST /employees/attendance/video/upload`)
10. [List Attendance Uploads](#10-list-attendance-uploads) (`GET /employees/attendance/video/uploads`)
11. [Delete Attendance Upload](#11-delete-attendance-upload) (`DELETE /employees/attendance/video/uploads/{video_id}`)
12. [Process Attendance Videos](#12-process-attendance-videos) (`POST /employees/attendance/video/process`)
13. [List Attendance Sessions](#13-list-attendance-sessions) (`GET /employees/attendance/video/sessions`)
14. [Get Attendance Session Details](#14-get-attendance-session-details) (`GET /employees/attendance/video/sessions/{session_id}`)
15. [Stream Attendance Video](#15-stream-attendance-video) (`GET /employees/attendance/video/sessions/{session_id}/video`)

---

## Endpoint Details

### 1. Register New Employee
Registers a new employee, uploads their registration photo, extracts face recognition embeddings, and registers them.

* **URL:** `/employees`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Role Allowed:** `admin`
* **Request Parameters (Form fields):**
  * `first_name`: `string` (Required. Employee first name)
  * `last_name`: `string` (Required. Employee last name)
  * `employee_code`: `string` (Required. Unique employee badge/ID code)
  * `file`: `File` (Required. Clear portrait/selfie photo file of the employee)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/employees" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "first_name=John" \
  -F "last_name=Doe" \
  -F "employee_code=EMP101" \
  -F "file=@john_doe.jpg"
```

#### Example Response (`201 Created`):
```json
{
  "message": "Employee registered successfully.",
  "status": 201,
  "data": {
    "id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
    "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
    "first_name": "John",
    "last_name": "Doe",
    "employee_code": "EMP101",
    "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
    "is_active": true,
    "created_at": "2026-06-23T07:15:33.452618Z"
  }
}
```

---

### 2. List Registered Employees
Lists all active registered employees in the tenant namespace.

* **URL:** `/employees`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/employees" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Successfully retrieved 1 employee(s).",
  "status": 200,
  "data": [
    {
      "id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
      "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
      "first_name": "John",
      "last_name": "Doe",
      "employee_code": "EMP101",
      "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
      "is_active": true,
      "created_at": "2026-06-23T07:15:33.452618Z"
    }
  ]
}
```

---

### 3. Get Employee Profile Details
Retrieves details of a single employee.

* **URL:** `/employees/{employee_id}`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `employee_id`: `UUID` (The unique ID of the employee)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/employees/b34e5a99-df8c-4f91-872e-dcdbc47c617b" \
  -H "accept: application/json"
```

---

### 4. Update Employee Profile
Updates an employee's profile info. If a new photo file is provided, face recognition embeddings are automatically re-extracted.

* **URL:** `/employees/{employee_id}`
* **Method:** `PUT`
* **Content-Type:** `multipart/form-data`
* **Role Allowed:** `admin`
* **URL Path Variables:**
  * `employee_id`: `UUID` (The unique ID of the employee to update)
* **Request Parameters (Form fields - all optional):**
  * `first_name`: `string`
  * `last_name`: `string`
  * `employee_code`: `string`
  * `file`: `File` (New selfie/portrait picture)

#### Example Request (cURL):
```bash
curl -X PUT "http://localhost:8000/api/v1/employees/b34e5a99-df8c-4f91-872e-dcdbc47c617b" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "first_name=Johnny"
```

---

### 5. Delete Employee Profile
Soft deletes an employee profile and clears their image from local storage.

* **URL:** `/employees/{employee_id}`
* **Method:** `DELETE`
* **Role Allowed:** `admin`
* **URL Path Variables:**
  * `employee_id`: `UUID` (The unique ID of the employee to delete)

#### Example Request (cURL):
```bash
curl -X DELETE "http://localhost:8000/api/v1/employees/b34e5a99-df8c-4f91-872e-dcdbc47c617b" \
  -H "accept: application/json"
```

---

### 6. Get Attendance by Date Range
Retrieves consolidated attendance records for all employees within a custom start and end date range.

* **URL:** `/employees/attendance`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **Query Parameters:**
  * `start_date`: `date` (Required. Format: `YYYY-MM-DD`)
  * `end_date`: `date` (Required. Format: `YYYY-MM-DD`)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/employees/attendance?start_date=2026-06-01&end_date=2026-06-30" \
  -H "accept: application/json"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Retrieved 1 attendance logs between 2026-06-01 and 2026-06-30.",
  "status": 200,
  "data": [
    {
      "id": "ea107620-ef78-4b6d-98d2-eca5ff482dbe",
      "session_id": "55fa00f0-7bae-450a-86df-a73ac220fbe4",
      "employee": {
        "id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
        "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
        "first_name": "John",
        "last_name": "Doe",
        "employee_code": "EMP101",
        "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
        "is_active": true,
        "created_at": "2026-06-23T07:15:33.452618Z"
      },
      "first_seen": 6.73,
      "last_seen": 21.23,
      "occurrence_count": 1,
      "employee_entry_timestamp": "2026-06-23T07:04:03.689218Z",
      "employee_exit_timestamp": "2026-06-23T07:04:23.123456Z",
      "created_at": "2026-06-23T07:04:03.700115Z",
      "dwell_time": 19.43
    }
  ]
}
```

---

### 7. Get Session Employee Attendance
Retrieves the employee check-in logs computed specifically during a single People Analytics video processing run.

* **URL:** `/employees/sessions/{session_id}/attendance`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the processing session)

#### Example Request (cURL):
```bash
curl -X GET "http://localhost:8000/api/v1/employees/sessions/55fa00f0-7bae-450a-86df-a73ac220fbe4/attendance" \
  -H "accept: application/json"
```

---

### 8. Mark Group Photo Attendance
Processes an uploaded group photo, detects all faces inside it, matches them against the tenant's employees, and marks them present for the day. It returns the annotated image showing boxes and employee names.

* **URL:** `/employees/attendance/photo`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Role Allowed:** `admin`
* **Request Parameters (Form fields):**
  * `file`: `File` (Required. Group photo file)
  * `similarity_threshold`: `float` (Optional. Cosine threshold for matching. Default: `0.85`, range: `0.5` to `1.0`)
  * `confidence_threshold`: `float` (Optional. YOLO face/person detection threshold. Default: `0.3`, range: `0.1` to `1.0`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/employees/attendance/photo" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@team_photo.jpg" \
  -F "similarity_threshold=0.85" \
  -F "confidence_threshold=0.3"
```

#### Example Response (`200 OK`):
```json
{
  "message": "Attendance marked for 1 employee(s).",
  "status": 200,
  "data": {
    "annotated_image_path": "storage/group_attendance_outputs/e6235884-1bfa-42f3-93e3-35898bcdc3de/team_photo_annotated.jpg",
    "attendance_logs": [
      {
        "id": "ca107620-ef78-4b6d-98d2-eca5ff482dcc",
        "session_id": null,
        "employee": {
          "id": "b34e5a99-df8c-4f91-872e-dcdbc47c617b",
          "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
          "first_name": "John",
          "last_name": "Doe",
          "employee_code": "EMP101",
          "photo_path": "storage/employee_registrations/e6235884-1bfa-42f3-93e3-35898bcdc3de/b34e5a99_portrait.jpg",
          "is_active": true,
          "created_at": "2026-06-23T07:15:33.452618Z"
        },
        "first_seen": 0.0,
        "last_seen": 0.0,
        "occurrence_count": 1,
        "employee_entry_timestamp": "2026-06-23T07:22:15.000000Z",
        "employee_exit_timestamp": "2026-06-23T07:22:15.000000Z",
        "created_at": "2026-06-23T07:22:15.312111Z",
        "dwell_time": 0.0
      }
    ]
  }
}
```

---

### 9. Upload Attendance Videos
Uploads standalone check-in/check-out video files specifically for marking employee attendance.

* **URL:** `/employees/attendance/video/upload`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Role Allowed:** `admin`
* **Request Parameters:**
  * **Files (Form fields):**
    * `files`: `File[]` (Select up to 10 video files to upload)

---

### 10. List Attendance Uploads
Lists all uploaded standalone attendance videos for the active user.

* **URL:** `/employees/attendance/video/uploads`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

---

### 11. Delete Attendance Upload
Deletes the uploaded attendance video and physical file.

* **URL:** `/employees/attendance/video/uploads/{video_id}`
* **Method:** `DELETE`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `video_id`: `UUID` (The unique ID of the uploaded video)

---

### 12. Process Attendance Videos
Creates sessions and schedules celery background tasks to process employee attendance tracking for a list of uploaded check-in/check-out videos.

* **URL:** `/employees/attendance/video/process`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Role Allowed:** `admin`
* **Request JSON Body Fields:**
  * `videos`: `Array[Object]` (Required)
    * `video_path`: `string` (Required. Path returned by upload API e.g. `"storage/employee_attendance_inputs/..."`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/v1/employees/attendance/video/process" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "videos": [
      {
        "video_path": "storage/employee_attendance_inputs/e555b489-b357-470d-abd9-33648e6aec50/c4faf388-984c-49c4-8fe4-ed4b52d0731d.mp4"
      }
    ]
  }'
```

#### Example Response (`202 Accepted`):
```json
{
  "message": "Successfully registered and started processing for 1 session(s).",
  "status": 202,
  "data": [
    {
      "id": "99fa00f0-7bae-450a-86df-a73ac220fbe4",
      "tenant_id": "e6235884-1bfa-42f3-93e3-35898bcdc3de",
      "video_name": "c4faf388-984c-49c4-8fe4-ed4b52d0731d.mp4",
      "video_path": "storage/employee_attendance_inputs/e555b489-b357-470d-abd9-33648e6aec50/c4faf388-984c-49c4-8fe4-ed4b52d0731d.mp4",
      "output_video_path": null,
      "status": "pending",
      "line_start": null,
      "line_end": null,
      "similarity_threshold": 0.85,
      "confidence_threshold": 0.3,
      "unique_person_count": null,
      "total_person_count": null,
      "first_time_visitor_count": null,
      "peak_occupancy": null,
      "average_occupancy": null,
      "entry_count": null,
      "exit_count": null,
      "occupancy_timeline": null,
      "created_at": "2026-06-23T07:25:12.122111Z",
      "completed_at": null
    }
  ]
}
```

---

### 13. List Attendance Sessions
Lists all video attendance runs created by the user.

* **URL:** `/employees/attendance/video/sessions`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)

---

### 14. Get Attendance Session Details
Retrieves configuration settings and run status of an attendance video session.

* **URL:** `/employees/attendance/video/sessions/{session_id}`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the attendance session)

---

### 15. Stream Attendance Video
Streams the final processed/annotated attendance video containing bounding boxes and employee names overlays.

* **URL:** `/employees/attendance/video/sessions/{session_id}/video`
* **Method:** `GET`
* **Role Allowed:** `viewer` (or above)
* **URL Path Variables:**
  * `session_id`: `UUID` (The unique ID of the session)

---

## Frontend Integration Guidelines

### 1. Register Employee Form
* Provide inputs for `first_name`, `last_name`, and `employee_code` text fields, and a file drag-and-drop/input field restricted to common image types (`.jpg`, `.jpeg`, `.png`).
* Send the payload as a `multipart/form-data` request.

### 2. Attendance Date Range Filtering
* Implement a Date Picker component allowing the selection of a `start_date` and `end_date`.
* Restrict picker values to not exceed today's date.
* Fetch attendance logs on value change using `/employees/attendance?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` and render the results in a searchable table.

### 3. Group Photo Attendance UI
* Provide a clean upload modal where the user can choose a group photo.
* Add adjustment sliders for settings:
  * **Similarity Threshold:** Slider from `0.5` to `1.0` (step `0.01`). Default `0.85`.
  * **Confidence Threshold:** Slider from `0.1` to `1.0` (step `0.05`). Default `0.30`.
* Upon submitting, show a loading spinner.
* **Rendering Response:**
  * Display the annotated team photo returned in the `annotated_image_path` variable (e.g. `http://localhost:8000/storage/group_attendance_outputs/...`).
  * Render a table of all successfully checked-in employees returned in the `attendance_logs` list.

### 4. Standalone Video Attendance
* Standalone check-in videos undergo background processing just like People Analytics sessions.
* Show progress bars during upload.
* Implement status polling against `/employees/attendance/video/sessions/{session_id}` to check for completion before displaying metrics.
