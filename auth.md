# Authentication API Documentation

## Base URL
```
http://localhost:8000
```
All endpoints are prefixed with `/auth`.

---

## Global Response Envelope
Every successful response follows this structure:
```json
{
  "message": "<human readable description>",
  "status": <http status code>,
  "data": { ... }
}
```
* `message` – short description of the operation outcome.
* `status` – HTTP status code (e.g., 200, 201).
* `data` – the payload specific to the endpoint (may be `null`).

---

## Endpoints

### 1. Register a new user (tenant‑only)
* **Method:** `POST`
* **URL:** `/auth/register`
* **Description:** Creates a user. If a `tenant_id` is supplied, the user is linked to that tenant; otherwise a new tenant is created automatically.
* **Request Body** (`application/json`):
```json
{
  "email": "user@example.com",
  "password": "StrongPass123",
  "first_name": "John",
  "last_name": "Doe",
  "tenant_id": "<optional-tenant-uuid>"
}
```
* **Response (`201 Created`):**
```json
{
  "message": "Registration successful",
  "status": 201,
  "data": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {
      "id": "<uuid>",
      "first_name": "John",
      "last_name": "Doe",
      "email": "user@example.com",
      "role": "admin",
      "tenant_id": "<tenant-uuid>"
    }
  }
}
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"StrongPass123","first_name":"John","last_name":"Doe","tenant_id":"<tenant-uuid>"}'
```
---

### 2. Login
* **Method:** `POST`
* **URL:** `/auth/login`
* **Description:** Authenticates a user and returns JWT tokens.
* **Request Body:**
```json
{
  "email": "user@example.com",
  "password": "StrongPass123"
}
```
* **Response (`200 OK`):**
```json
{
  "message": "Login successful",
  "status": 200,
  "data": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {
      "id": "<uuid>",
      "first_name": "John",
      "last_name": "Doe",
      "email": "user@example.com",
      "role": "admin",
      "tenant_id": "<tenant-uuid>"
    }
  }
}
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"StrongPass123"}'
```
---

### 3. Refresh Tokens
* **Method:** `POST`
* **URL:** `/auth/refresh`
* **Description:** Issues new access and refresh tokens using a valid refresh token.
* **Request Body:**
```json
{
  "refresh_token": "<refresh_jwt>"
}
```
* **Response (`200 OK`):**
```json
{
  "message": "Token refreshed",
  "status": 200,
  "data": {
    "access_token": "<new_jwt>",
    "refresh_token": "<new_jwt>",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {
      "id": "<uuid>",
      "first_name": "John",
      "last_name": "Doe",
      "email": "user@example.com",
      "role": "admin",
      "tenant_id": "<tenant-uuid>"
    }
  }
}
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_jwt>"}'
```
---

### 4. Get Current User Profile
* **Method:** `GET`
* **URL:** `/auth/me`
* **Description:** Retrieves the profile of the authenticated user.
* **Headers:**
```
Authorization: Bearer <access_token>
```
* **Response (`200 OK`):**
```json
{
  "message": "User profile retrieved",
  "status": 200,
  "data": {
    "id": "<uuid>",
    "first_name": "John",
    "last_name": "Doe",
    "email": "user@example.com",
    "role": "admin",
    "tenant_id": "<tenant-uuid>"
  }
}
```
* **cURL example:**
```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <access_token>"
```
---

### 5. Change Password
* **Method:** `POST`
* **URL:** `/auth/change-password`
* **Description:** Allows an authenticated user to change their password.
* **Headers:**
```
Authorization: Bearer <access_token>
```
* **Request Body:**
```json
{
  "old_password": "CurrentPass123",
  "new_password": "NewStrongPass456"
}
```
* **Response (`200 OK`):**
```json
{
  "message": "Password updated successfully",
  "status": 200,
  "data": null
}
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/change-password \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"old_password":"CurrentPass123","new_password":"NewStrongPass456"}'
```
---

### 6. Logout
* **Method:** `POST`
* **URL:** `/auth/logout`
* **Description:** Stateless logout – client should discard tokens.
* **Headers:**
```
Authorization: Bearer <access_token>
```
* **Response (`200 OK`):**
```json
{
  "message": "Successfully logged out",
  "status": 200,
  "data": null
}
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer <access_token>"
```
---

## Error Handling
All error responses are wrapped in the same envelope:
```json
{
  "message": "<error description>",
  "status": <http status code>,
  "data": null
}
```
Typical status codes:
* `400` – Bad request / validation error
* `401` – Unauthorized (invalid token)
* `404` – Not found (e.g., user does not exist)
* `500` – Internal server error

---

*Prepared for frontend developers to quickly integrate authentication flows.*
