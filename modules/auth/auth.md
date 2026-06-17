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

## Cookie-Based JWT Flow (How to get and use the Access Token)

Our backend uses **Cookie-Based JWT Authentication** for enhanced security. This has two key differences from header-based token flows:

1. **Where the Token is Returned**:
   When you successfully register (`POST /auth/register`) or login (`POST /auth/login`), the tokens are **not** in the JSON response payload. Instead, they are returned in the HTTP Response Headers as secure, `HttpOnly` cookies:
   ```http
   Set-Cookie: access_token=<JWT_TOKEN_VALUE>; HttpOnly; Path=/; SameSite=Lax; Max-Age=3600
   Set-Cookie: refresh_token=<REFRESH_TOKEN_VALUE>; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800
   ```

2. **How to Use the Token**:
   * **In Browsers (Frontend integration)**: The browser automatically handles storing and sending these cookies with every subsequent request. You do not need to write any JavaScript to store the token in `localStorage` or inject it into headers. (Make sure your frontend HTTP client is configured to include credentials, e.g. `credentials: 'include'` in Fetch, or `withCredentials: true` in Axios).
   * **For API Clients / Mobile Apps (cURL, Postman, etc.)**: You can pass the token in one of two ways:
     - **As a Cookie Header** (Recommended): `Cookie: access_token=<JWT_TOKEN_VALUE>`
     - **As an Authorization Header** (Fallback): `Authorization: Bearer <JWT_TOKEN_VALUE>`

---

## Endpoints

### 1. Register a new user (tenant‑only)
* **Method:** `POST`
* **URL:** `/auth/register`
* **Description:** Creates a user. Sets `access_token` and `refresh_token` as HTTP-only cookies in the browser. If a `tenant_id` is supplied, the user is linked to that tenant; otherwise a new tenant is created automatically.
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
    "id": "<uuid>",
    "first_name": "John",
    "last_name": "Doe",
    "email": "user@example.com",
    "role": "admin",
    "tenant_id": "<tenant-uuid>"
  }
}
```
* **Response Headers:**
```
Set-Cookie: access_token=<access_jwt>; HttpOnly; Path=/; SameSite=Lax; Max-Age=3600
Set-Cookie: refresh_token=<refresh_jwt>; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800
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
* **Description:** Authenticates a user and sets `access_token` and `refresh_token` as HTTP-only cookies in the browser.
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
    "id": "<uuid>",
    "first_name": "John",
    "last_name": "Doe",
    "email": "user@example.com",
    "role": "admin",
    "tenant_id": "<tenant-uuid>"
  }
}
```
* **Response Headers:**
```
Set-Cookie: access_token=<access_jwt>; HttpOnly; Path=/; SameSite=Lax; Max-Age=3600
Set-Cookie: refresh_token=<refresh_jwt>; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800
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
* **Description:** Issues new access and refresh tokens. Reads the current refresh token from the browser cookie and sets updated cookies.
* **Request Cookies:**
```
refresh_token=<refresh_jwt>
```
* **Response (`200 OK`):**
```json
{
  "message": "Token refreshed",
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
* **Response Headers:**
```
Set-Cookie: access_token=<access_jwt>; HttpOnly; Path=/; SameSite=Lax; Max-Age=3600
Set-Cookie: refresh_token=<refresh_jwt>; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/refresh --cookie "refresh_token=<refresh_jwt>"
```
---

### 4. Get Current User Profile
* **Method:** `GET`
* **URL:** `/auth/me`
* **Description:** Retrieves the profile of the authenticated user.
* **Authentication:**
Reads the `access_token` cookie automatically. Falls back to `Authorization: Bearer <access_token>` header if cookie is missing.
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
curl http://localhost:8000/auth/me --cookie "access_token=<access_token>"
```
---

### 5. Change Password
* **Method:** `POST`
* **URL:** `/auth/change-password`
* **Description:** Allows an authenticated user to change their password.
* **Authentication:**
Reads the `access_token` cookie automatically. Falls back to `Authorization: Bearer <access_token>` header if cookie is missing.
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
  --cookie "access_token=<access_token>" \
  -d '{"old_password":"CurrentPass123","new_password":"NewStrongPass456"}'
```
---

### 6. Logout
* **Method:** `POST`
* **URL:** `/auth/logout`
* **Description:** Deletes the authentication cookies on the browser client.
* **Authentication:**
Reads the `access_token` cookie automatically. Falls back to `Authorization: Bearer <access_token>` header if cookie is missing.
* **Response (`200 OK`):**
```json
{
  "message": "Successfully logged out",
  "status": 200,
  "data": null
}
```
* **Response Headers:**
```
Set-Cookie: access_token=; Max-Age=0; Path=/
Set-Cookie: refresh_token=; Max-Age=0; Path=/
```
* **cURL example:**
```bash
curl -X POST http://localhost:8000/auth/logout --cookie "access_token=<access_token>"
```
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
