# 🎥 Computer Vision Analytics Platform — Backend

> Multi-tenant SaaS platform for AI-powered video analytics. Supports CCTV, IP cameras, RTSP streams, and recorded video with person detection, zone monitoring, intrusion, loitering, occupancy analytics, alerting, and automated reporting.

---

## 📑 Table of Contents

- [Multi-Tenant Architecture](#multi-tenant-saas-architecture)
- [Role Hierarchy](#role-hierarchy)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema — Tenant Isolation](#database-schema--tenant-isolation)
- [Environment Setup](#environment-setup)
- [Storage Configuration](#storage-configuration)
- [Running the Application](#running-the-application)
- [Authentication (JWT)](#authentication-jwt)
- [API Modules & Endpoints](#api-modules--endpoints)
  - [SuperAdmin — Platform Management](#superadmin-apis-apiv1superadmin)
  - [Auth](#1-auth-apiv1auth)
  - [Organization (Tenant)](#2-organization-apiv1org)
  - [Users](#3-users-apiv1users)
  - [Permissions](#4-permissions-apiv1permissions)
  - [Cameras](#5-cameras-apiv1cameras)
  - [Zones](#6-zones-apiv1zones)
  - [Rules](#7-rules-apiv1rules)
  - [Events](#8-events-apiv1events)
  - [Alerts](#9-alerts-apiv1alerts)
  - [Analytics](#10-analytics-apiv1analytics)
  - [Reports](#11-reports-apiv1reports)
  - [Dashboard](#12-dashboard-apiv1dashboard)
- [Subscription Plans](#subscription-plans)
- [Workers](#workers)
- [AI Services](#ai-services)
- [Notification Services](#notification-services)
- [Database Migrations](#database-migrations)
- [API Response Format](#api-response-format)
- [Error Codes](#error-codes)

---

## Multi-Tenant SaaS Architecture

This platform is a **multi-tenant SaaS** system. Every piece of data — cameras, zones, events, users, reports — belongs to a **Tenant (Organization)**. Tenants are fully isolated from each other.

```
┌─────────────────────────────────────────────────────────────┐
│                     PLATFORM LAYER                          │
│                                                             │
│   SuperAdmin  ──────  Manages all Tenants + Subscriptions   │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
   │  Tenant A   │  │  Tenant B   │  │  Tenant C   │
   │ (Org: ABC)  │  │ (Org: XYZ)  │  │ (Org: DEF)  │
   │             │  │             │  │             │
   │  Admin      │  │  Admin      │  │  Admin      │
   │  Operator   │  │  Operator   │  │  Operator   │
   │  Viewer     │  │  Viewer     │  │  Viewer     │
   └─────────────┘  └─────────────┘  └─────────────┘
```

### Key Principles

- Every API request from an Org user is **scoped to their `tenant_id`** automatically via JWT middleware — they can never access another org's data.
- **SuperAdmin** operates at the platform level — above all tenants, with a separate admin portal (`/api/v1/superadmin/`).
- **Admin** is the organization owner — manages their own org's users, cameras, permissions.
- All DB tables (except platform-level ones) include a `tenant_id` foreign key for row-level isolation.

---

## Role Hierarchy

```
SuperAdmin  (Platform Level)
│
│   ── Manages all organizations
│   ── Monitors all tenants
│   ── Manages subscription plans
│   ── Can impersonate any org (read-only audit)
│   ── Creates / suspends / deletes organizations
│
└── Tenant / Organization
    │
    Admin  (Organization Level)
    │
    │   ── Manages their own organization only
    │   ── Creates and manages Operators and Viewers
    │   ── Assigns granular permissions to each user
    │   ── Configures cameras, zones, rules, alerts
    │   ── Manages org notification settings
    │   ── Views org-level analytics and reports
    │
    ├── Operator  (Org User)
    │       ── Controls cameras (start/stop streams)
    │       ── Manages zones and rules
    │       ── Acknowledges events and alerts
    │       ── Views analytics and reports
    │       ── Cannot manage users or org settings
    │
    └── Viewer  (Org User — Read Only)
            ── View dashboard, cameras, events, alerts
            ── View analytics and reports
            ── Cannot modify anything
```

### Role Permission Matrix

| Action | SuperAdmin | Admin | Operator | Viewer |
|---|:---:|:---:|:---:|:---:|
| Manage all organizations | ✅ | ❌ | ❌ | ❌ |
| View all org activity | ✅ | ❌ | ❌ | ❌ |
| Manage subscription plans | ✅ | ❌ | ❌ | ❌ |
| Suspend / delete org | ✅ | ❌ | ❌ | ❌ |
| Manage own org users | ❌ | ✅ | ❌ | ❌ |
| Assign user permissions | ❌ | ✅ | ❌ | ❌ |
| Add / remove cameras | ❌ | ✅ | ❌ | ❌ |
| Configure zones & rules | ❌ | ✅ | ✅ | ❌ |
| Start / stop camera stream | ❌ | ✅ | ✅ | ❌ |
| Acknowledge events/alerts | ❌ | ✅ | ✅ | ❌ |
| View cameras & live feed | ❌ | ✅ | ✅ | ✅ |
| View events & alerts | ❌ | ✅ | ✅ | ✅ |
| View analytics & reports | ❌ | ✅ | ✅ | ✅ |
| Generate / download reports | ❌ | ✅ | ✅ | ❌ |
| Manage alert config | ❌ | ✅ | ❌ | ❌ |
| View dashboard | ❌ | ✅ | ✅ | ✅ |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI |
| Language | Python 3.11+ |
| Database | PostgreSQL (via SQLAlchemy + Alembic) |
| Cache / Session | Redis |
| Task Queue | Celery + Redis Broker |
| Message Streaming | Apache Kafka |
| Storage (local) | Local filesystem (`/storage/`) |
| Storage (production) | AWS S3 / MinIO |
| Auth | JWT (access + refresh tokens) |
| CV / AI | YOLO11, OpenCV, NVIDIA Triton Inference Server |
| Containerization | Docker + Docker Compose |
| Orchestration | Kubernetes |

---

## Project Structure

```
computer_vision_backend/
├── app/
│   ├── modules/
│   │   ├── auth/                   # JWT authentication (all roles)
│   │   ├── superadmin/             # ⭐ SuperAdmin — platform management
│   │   │   ├── model.py
│   │   │   ├── schema.py
│   │   │   ├── service.py
│   │   │   ├── repository.py
│   │   │   └── routes.py
│   │   │
│   │   ├── organizations/          # ⭐ Tenant / Org management
│   │   │   ├── model.py
│   │   │   ├── schema.py
│   │   │   ├── service.py
│   │   │   ├── repository.py
│   │   │   └── routes.py
│   │   │
│   │   ├── subscriptions/          # ⭐ Subscription plans (scaffolded)
│   │   │   ├── model.py
│   │   │   ├── schema.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   │
│   │   ├── permissions/            # ⭐ Granular permission management
│   │   │   ├── model.py
│   │   │   ├── schema.py
│   │   │   ├── service.py
│   │   │   └── routes.py
│   │   │
│   │   ├── users/                  # Org-scoped user management
│   │   ├── cameras/                # Tenant-scoped cameras
│   │   ├── zones/
│   │   ├── rules/
│   │   ├── events/
│   │   ├── alerts/
│   │   ├── analytics/
│   │   ├── reports/
│   │   └── dashboard/
│   │
│   ├── services/
│   │   ├── camera_processors/      # RTSP/stream handlers
│   │   ├── ai/                     # CV inference services
│   │   ├── notifications/          # Email/WhatsApp/SMS
│   │   └── storage/                # S3/MinIO/local storage
│   │
│   ├── configs/
│   ├── database/
│   ├── workers/
│   ├── shared/
│   │   ├── enums/
│   │   │   └── roles.py            # SuperAdmin, Admin, Operator, Viewer
│   │   ├── middleware/
│   │   │   └── tenant_context.py   # Auto-injects tenant_id from JWT
│   │   ├── dependencies/
│   │   │   └── auth.py             # Role guards: require_superadmin, require_admin, etc.
│   │   ├── constants/
│   │   └── exceptions/
│   └── main.py
│
├── requirements.txt
├── .env.example
├── docker-compose.yml
└── Dockerfile
```

---

## Database Schema — Tenant Isolation

Every org-level table includes `tenant_id` for strict data isolation.

```sql
-- Platform level
CREATE TABLE organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    slug        VARCHAR(100) UNIQUE NOT NULL,   -- e.g. "abc-warehouse"
    email       VARCHAR(255) NOT NULL,           -- org admin email
    status      VARCHAR(20) DEFAULT 'active',    -- active | suspended | trial
    plan        VARCHAR(20) DEFAULT 'free',       -- free | basic | professional | enterprise
    plan_expires_at TIMESTAMP,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Users: belong to an org (except superadmin who has no org)
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES organizations(id),   -- NULL for superadmin
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255) UNIQUE NOT NULL,
    password    VARCHAR(255) NOT NULL,
    role        VARCHAR(20) NOT NULL,   -- superadmin | admin | operator | viewer
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Org-level permissions per user
CREATE TABLE user_permissions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES organizations(id) NOT NULL,
    user_id     UUID REFERENCES users(id) NOT NULL,
    permission  VARCHAR(100) NOT NULL,   -- e.g. "cameras.view", "alerts.acknowledge"
    granted     BOOLEAN DEFAULT true
);

-- All resource tables are scoped to tenant_id
-- cameras, zones, rules, events, alerts, reports, analytics...
CREATE TABLE cameras (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES organizations(id) NOT NULL,  -- ← always scoped
    name        VARCHAR(255) NOT NULL,
    ...
);
```

### Tenant Isolation Middleware

All org-user requests automatically inject `tenant_id` from the JWT payload:

```python
# app/shared/middleware/tenant_context.py
# Every DB query for org-level data runs with:
#   WHERE tenant_id = current_user.tenant_id
# SuperAdmin bypasses this for platform-wide queries.
```

---

## Environment Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/computer-vision-backend.git
cd computer-vision-backend
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

`.env.example`:

```env
# --- App ---
APP_ENV=development
APP_SECRET_KEY=your-secret-key
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000

# --- Database ---
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/cv_platform

# --- Redis ---
REDIS_URL=redis://localhost:6379/0

# --- JWT ---
JWT_SECRET_KEY=your-jwt-secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# --- SuperAdmin Bootstrap (seeds on first run) ---
SUPERADMIN_EMAIL=superadmin@cvplatform.com
SUPERADMIN_PASSWORD=SuperSecure@123

# --- Storage: Local (development) ---
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=./storage

# --- Storage: S3 (production) ---
# STORAGE_BACKEND=s3
# AWS_ACCESS_KEY_ID=your-key
# AWS_SECRET_ACCESS_KEY=your-secret
# AWS_S3_BUCKET_NAME=cv-platform-bucket
# AWS_S3_REGION=ap-south-1

# --- Storage: MinIO (production self-hosted) ---
# STORAGE_BACKEND=minio
# MINIO_ENDPOINT=localhost:9000
# MINIO_ACCESS_KEY=minioadmin
# MINIO_SECRET_KEY=minioadmin
# MINIO_BUCKET_NAME=cv-platform
# MINIO_SECURE=false

# --- Kafka ---
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CONSUMER_GROUP=cv-platform-group

# --- Notifications ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your@email.com
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=noreply@cvplatform.com

TWILIO_ACCOUNT_SID=your-sid
TWILIO_AUTH_TOKEN=your-token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_SMS_FROM=+1234567890
```

---

## Storage Configuration

Controlled by the `STORAGE_BACKEND` env variable.

### Local (Development)

```env
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=./storage
```

Files organized as:
```
storage/
└── tenants/
    └── {tenant_id}/          ← isolated per org
        ├── snapshots/
        ├── recordings/
        ├── reports/
        └── thumbnails/
```

### AWS S3 (Production)

```env
STORAGE_BACKEND=s3
AWS_S3_BUCKET_NAME=cv-platform-bucket
```

S3 prefix structure: `tenants/{tenant_id}/snapshots/...`

### MinIO (Self-hosted Production)

```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio.yourdomain.com:9000
MINIO_BUCKET_NAME=cv-platform
MINIO_SECURE=true
```

All three backends use the same unified interface in `app/services/storage/` — no code changes needed when switching.

---

## Running the Application

### Development

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker Compose (Full Stack)

```bash
docker-compose up --build
```

Spins up: FastAPI app, PostgreSQL, Redis, Kafka, MinIO, Celery workers.

### Production

```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

---

## Authentication (JWT)

Dual-token strategy for all roles:

| Token | TTL | Purpose |
|---|---|---|
| `access_token` | 60 minutes | API authorization |
| `refresh_token` | 7 days | Obtain new access token |

### JWT Payload Structure

```json
{
  "sub": "user-uuid",
  "email": "admin@acme.com",
  "role": "admin",
  "tenant_id": "org-uuid",        // null for superadmin
  "tenant_slug": "acme-corp",     // null for superadmin
  "iat": 1700000000,
  "exp": 1700003600
}
```

### Auth Flow

```
POST /api/v1/auth/login
  → returns access_token + refresh_token + role + tenant info

All protected requests:
  Authorization: Bearer <access_token>

Access token expired:
  POST /api/v1/auth/refresh → new access_token

POST /api/v1/auth/logout
  → blacklists refresh_token in Redis
```

---

## API Modules & Endpoints

Base URL: `http://localhost:8000/api/v1`

Swagger UI: `http://localhost:8000/docs`

**Route prefixes by role:**
- `/api/v1/superadmin/...` — SuperAdmin only
- `/api/v1/org/...` — Admin managing their org
- `/api/v1/...` — Org users (Admin / Operator / Viewer, scoped to their tenant)

---

## SuperAdmin APIs `/api/v1/superadmin`

> 🔒 All routes require `role = superadmin`

### Organizations Management

| Method | Endpoint | Description |
|---|---|---|
| GET | `/organizations` | List all organizations (paginated + search) |
| POST | `/organizations` | Create a new organization + auto-create admin user |
| GET | `/organizations/{org_id}` | Get org details, stats, subscription |
| PUT | `/organizations/{org_id}` | Update org details |
| PUT | `/organizations/{org_id}/suspend` | Suspend an organization |
| PUT | `/organizations/{org_id}/activate` | Reactivate a suspended org |
| DELETE | `/organizations/{org_id}` | Permanently delete org + all data |
| GET | `/organizations/{org_id}/users` | List all users in an org |
| GET | `/organizations/{org_id}/activity` | Org activity log (logins, events) |
| GET | `/organizations/{org_id}/stats` | Cameras, events, alerts count for org |

**Request — Create Organization:**
```json
POST /api/v1/superadmin/organizations
{
  "org_name": "ACME Warehouse",
  "org_slug": "acme-warehouse",
  "admin_name": "Rajesh Patel",
  "admin_email": "rajesh@acmewarehouse.com",
  "admin_password": "TempPass@123",
  "plan": "free"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "organization": {
      "id": "org-uuid",
      "name": "ACME Warehouse",
      "slug": "acme-warehouse",
      "status": "active",
      "plan": "free",
      "created_at": "2025-06-01T10:00:00Z"
    },
    "admin_user": {
      "id": "user-uuid",
      "name": "Rajesh Patel",
      "email": "rajesh@acmewarehouse.com",
      "role": "admin"
    }
  }
}
```

### Subscription Management

| Method | Endpoint | Description |
|---|---|---|
| GET | `/subscriptions/plans` | List all available plans |
| PUT | `/organizations/{org_id}/plan` | Change org subscription plan |
| GET | `/organizations/{org_id}/plan` | Get current plan details for an org |

**Request — Change Plan:**
```json
PUT /api/v1/superadmin/organizations/{org_id}/plan
{
  "plan": "professional",
  "expires_at": "2026-06-01T00:00:00Z",
  "notes": "Upgraded after sales call"
}
```

### Platform Monitoring

| Method | Endpoint | Description |
|---|---|---|
| GET | `/stats` | Platform-wide KPIs (total orgs, users, cameras, events) |
| GET | `/activity` | Recent platform activity log |
| GET | `/users` | List all users across all orgs |
| GET | `/health` | System health (DB, Redis, Kafka, storage) |

---

### 1. Auth `/api/v1/auth`

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/login` | Login (any role) — returns tokens + role + tenant | No |
| POST | `/refresh` | Refresh access token | No |
| POST | `/logout` | Logout, blacklist refresh token | Yes |
| POST | `/forgot-password` | Send password reset email | No |
| POST | `/reset-password` | Reset password with token | No |
| POST | `/change-password` | Change own password | Yes |
| GET | `/me` | Get own profile + role + tenant info | Yes |

**Login Request:**
```json
POST /api/v1/auth/login
{
  "email": "rajesh@acmewarehouse.com",
  "password": "TempPass@123"
}
```

**Login Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "user-uuid",
    "name": "Rajesh Patel",
    "email": "rajesh@acmewarehouse.com",
    "role": "admin",
    "tenant_id": "org-uuid",
    "tenant_name": "ACME Warehouse",
    "tenant_slug": "acme-warehouse"
  }
}
```

---

### 2. Organization `/api/v1/org`

> 🔒 `role = admin` — manages own organization only

| Method | Endpoint | Description |
|---|---|---|
| GET | `/profile` | Get own org profile |
| PUT | `/profile` | Update org name, logo, contact info |
| GET | `/subscription` | View current subscription plan + limits |
| GET | `/stats` | Org usage stats (cameras, users, storage used) |
| PUT | `/settings` | Update org-level settings (timezone, notifications) |
| GET | `/activity-log` | Full activity log for the org |

**Response — Org Subscription:**
```json
{
  "plan": "free",
  "status": "active",
  "limits": {
    "max_cameras": "unlimited",
    "max_users": "unlimited",
    "storage_gb": "unlimited",
    "features": ["all"]
  },
  "note": "All features are currently free. Subscription tiers coming soon."
}
```

---

### 3. Users `/api/v1/users`

> 🔒 `admin` — full CRUD. `operator` / `viewer` — read own profile only.
> All queries auto-scoped to `tenant_id` from JWT.

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List all users in org | admin |
| POST | `/` | Create new user (operator or viewer) | admin |
| GET | `/{user_id}` | Get user details | admin |
| PUT | `/{user_id}` | Update user info | admin |
| DELETE | `/{user_id}` | Remove user from org | admin |
| PUT | `/{user_id}/status` | Activate / deactivate user | admin |
| GET | `/{user_id}/permissions` | View user's permissions | admin |
| PUT | `/{user_id}/permissions` | Update user's permissions | admin |
| GET | `/me` | Get own profile | all |
| PUT | `/me` | Update own name / password | all |

**Request — Create User:**
```json
POST /api/v1/users
{
  "name": "Amit Shah",
  "email": "amit@acmewarehouse.com",
  "password": "Temp@1234",
  "role": "operator",
  "permissions": [
    "cameras.view",
    "cameras.stream_control",
    "zones.view",
    "events.view",
    "events.acknowledge",
    "alerts.view",
    "alerts.acknowledge",
    "analytics.view",
    "reports.view"
  ]
}
```

---

### 4. Permissions `/api/v1/permissions`

> Admin assigns granular permissions to Operators and Viewers.

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/list` | Get all available permissions | admin |
| GET | `/users/{user_id}` | Get permissions for a user | admin |
| PUT | `/users/{user_id}` | Set permissions for a user | admin |
| POST | `/users/{user_id}/grant` | Grant a specific permission | admin |
| POST | `/users/{user_id}/revoke` | Revoke a specific permission | admin |

**Available Permissions:**

| Permission Key | Description |
|---|---|
| `cameras.view` | View camera list and details |
| `cameras.stream_control` | Start/stop camera streams |
| `cameras.manage` | Add/edit/delete cameras (admin only by default) |
| `zones.view` | View zones |
| `zones.manage` | Create/edit/delete zones |
| `rules.view` | View rules |
| `rules.manage` | Create/edit/delete rules |
| `events.view` | View events |
| `events.acknowledge` | Acknowledge events |
| `alerts.view` | View alerts |
| `alerts.acknowledge` | Acknowledge/resolve alerts |
| `analytics.view` | View analytics data |
| `reports.view` | View reports |
| `reports.generate` | Generate and download reports |
| `dashboard.view` | View dashboard |

**Request — Set Permissions:**
```json
PUT /api/v1/permissions/users/{user_id}
{
  "permissions": [
    "cameras.view",
    "events.view",
    "events.acknowledge",
    "alerts.view",
    "dashboard.view"
  ]
}
```

---

### 5. Cameras `/api/v1/cameras`

> All data auto-scoped to the requesting user's `tenant_id`.

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List org's cameras | cameras.view |
| POST | `/` | Add new camera | cameras.manage |
| GET | `/{camera_id}` | Get camera details | cameras.view |
| PUT | `/{camera_id}` | Update camera config | cameras.manage |
| DELETE | `/{camera_id}` | Remove camera | cameras.manage |
| POST | `/{camera_id}/test` | Test camera connection | cameras.manage |
| POST | `/{camera_id}/start` | Start stream processing | cameras.stream_control |
| POST | `/{camera_id}/stop` | Stop stream processing | cameras.stream_control |
| GET | `/{camera_id}/snapshot` | Get latest frame | cameras.view |
| GET | `/{camera_id}/status` | Real-time stream status | cameras.view |
| GET | `/{camera_id}/zones` | List camera's zones | zones.view |

**Request — Add Camera:**
```json
POST /api/v1/cameras
{
  "name": "Warehouse Entrance",
  "location": "Gate A",
  "source_type": "rtsp",
  "stream_url": "rtsp://192.168.1.100:554/stream1",
  "username": "admin",
  "password": "camera123",
  "fps": 15,
  "resolution": "1920x1080",
  "analytics_enabled": ["person_detection", "intrusion", "loitering"]
}
```

---

### 6. Zones `/api/v1/zones`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List org's zones | zones.view |
| POST | `/` | Create zone on a camera | zones.manage |
| GET | `/{zone_id}` | Get zone details | zones.view |
| PUT | `/{zone_id}` | Update zone polygon / settings | zones.manage |
| DELETE | `/{zone_id}` | Delete zone | zones.manage |
| GET | `/{zone_id}/occupancy` | Live occupancy for zone | zones.view |
| GET | `/{zone_id}/events` | Events within zone | events.view |

**Request — Create Zone:**
```json
POST /api/v1/zones
{
  "camera_id": "uuid-camera",
  "name": "Restricted Area A",
  "zone_type": "restricted",
  "polygon": [[100,200],[400,200],[400,500],[100,500]],
  "max_occupancy": 5,
  "rules_enabled": ["intrusion", "loitering", "crowd_density"]
}
```

---

### 7. Rules `/api/v1/rules`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List org's rules | rules.view |
| POST | `/` | Create new rule | rules.manage |
| GET | `/{rule_id}` | Get rule details | rules.view |
| PUT | `/{rule_id}` | Update rule | rules.manage |
| DELETE | `/{rule_id}` | Delete rule | rules.manage |
| PUT | `/{rule_id}/toggle` | Enable / disable rule | rules.manage |

**Request — Create Rule:**
```json
POST /api/v1/rules
{
  "zone_id": "uuid-zone",
  "name": "After Hours Intrusion",
  "type": "intrusion",
  "conditions": {
    "time_start": "20:00",
    "time_end": "06:00",
    "days": ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
  },
  "severity": "critical",
  "alert_channels": ["email", "whatsapp"]
}
```

---

### 8. Events `/api/v1/events`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List events (paginated + filtered) | events.view |
| GET | `/{event_id}` | Get event details with snapshot | events.view |
| GET | `/{event_id}/snapshot` | Get event frame snapshot | events.view |
| PUT | `/{event_id}/acknowledge` | Acknowledge event | events.acknowledge |
| DELETE | `/{event_id}` | Delete event | admin |
| GET | `/camera/{camera_id}` | Events by camera | events.view |
| GET | `/zone/{zone_id}` | Events by zone | events.view |

**Query Params:**
```
GET /api/v1/events?
  camera_id=uuid&zone_id=uuid&event_type=intrusion&
  severity=critical&from_date=2025-01-01&to_date=2025-01-31&
  acknowledged=false&page=1&limit=50
```

---

### 9. Alerts `/api/v1/alerts`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List org's alerts | alerts.view |
| GET | `/{alert_id}` | Get alert details | alerts.view |
| PUT | `/{alert_id}/acknowledge` | Acknowledge alert | alerts.acknowledge |
| PUT | `/{alert_id}/resolve` | Resolve alert | alerts.acknowledge |
| DELETE | `/{alert_id}` | Delete alert | admin |
| GET | `/unread/count` | Unread alert count | alerts.view |
| POST | `/test` | Send test notification | admin |
| GET | `/config` | Get org alert config | admin |
| PUT | `/config` | Update org alert config | admin |

---

### 10. Analytics `/api/v1/analytics`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/people-count` | People count over time | analytics.view |
| GET | `/occupancy` | Occupancy trends | analytics.view |
| GET | `/zone-activity` | Activity per zone | analytics.view |
| GET | `/peak-hours` | Peak hour analysis | analytics.view |
| GET | `/traffic-flow` | Entry / exit flow | analytics.view |
| GET | `/heatmap` | Movement heatmap data | analytics.view |
| GET | `/crowd-density` | Crowd density metrics | analytics.view |
| GET | `/dwell-time` | Dwell time per zone | analytics.view |
| GET | `/visitor-flow` | Visitor flow patterns | analytics.view |
| GET | `/summary` | Aggregated summary | analytics.view |

---

### 11. Reports `/api/v1/reports`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/` | List org's reports | reports.view |
| POST | `/generate` | Generate report on demand | reports.generate |
| GET | `/{report_id}` | Get report metadata | reports.view |
| GET | `/{report_id}/download` | Download PDF / XLSX / CSV | reports.generate |
| DELETE | `/{report_id}` | Delete report | admin |
| GET | `/templates` | List 20 available templates | reports.view |
| GET | `/schedules` | List scheduled reports | admin |
| POST | `/schedules` | Create scheduled report | admin |
| PUT | `/schedules/{id}` | Update schedule | admin |
| DELETE | `/schedules/{id}` | Delete schedule | admin |

**Available Report Templates:**

| Template Key | Description |
|---|---|
| `people_counting_report` | Total people count per camera/zone |
| `entry_counting_report` | Entry events over time |
| `exit_counting_report` | Exit events over time |
| `occupancy_analytics_report` | Occupancy trends |
| `visitor_flow_report` | Visitor flow patterns |
| `area_utilization_report` | Zone utilization % |
| `peak_hour_analysis_report` | Busiest hours |
| `intrusion_detection_report` | Intrusion events |
| `restricted_zone_access_report` | Unauthorized zone access |
| `loitering_detection_report` | Loitering incidents |
| `unknown_person_report` | Unidentified person detections |
| `suspicious_activity_report` | Suspicious behaviors |
| `crowd_density_report` | Crowd density over time |
| `congestion_analysis_report` | Congestion hotspots |
| `queue_monitoring_report` | Queue lengths and wait times |
| `gathering_event_report` | Group gathering detections |
| `activity_recognition_report` | Activity classifications |
| `movement_pattern_report` | Movement trajectory analysis |
| `zone_activity_report` | Per-zone activity breakdown |
| `executive_ai_summary_report` | AI-generated executive summary |

---

### 12. Dashboard `/api/v1/dashboard`

| Method | Endpoint | Description | Role |
|---|---|---|---|
| GET | `/summary` | Org-level KPIs | dashboard.view |
| GET | `/live` | Real-time counts across org cameras | dashboard.view |
| GET | `/kpi` | KPI cards (people, events, alerts) | dashboard.view |
| GET | `/occupancy/live` | Live occupancy all zones | dashboard.view |
| GET | `/alerts/recent` | Latest alerts | dashboard.view |
| GET | `/events/recent` | Latest events | dashboard.view |
| GET | `/cameras/status` | Camera online/offline status | dashboard.view |
| GET | `/charts/hourly` | Hourly chart data | dashboard.view |
| GET | `/charts/daily` | Daily chart data | dashboard.view |
| GET | `/heatmap/live` | Live movement heatmap | dashboard.view |

---

## Subscription Plans

> ⚠️ All organizations are currently on the **Free Plan** — all features unlocked, no limits enforced. Subscription enforcement will be added in a future release. The schema and routes are scaffolded and ready.

| Plan | Status | Notes |
|---|---|---|
| `free` | ✅ Active (all orgs) | All features, no limits, no expiry |
| `basic` | 🔜 Scaffolded | To be defined |
| `professional` | 🔜 Scaffolded | To be defined |
| `enterprise` | 🔜 Scaffolded | Custom negotiated |

SuperAdmin can view and change an org's plan via `/api/v1/superadmin/organizations/{org_id}/plan` — but limits are not enforced until the subscription service is activated.

---

## Workers

### Celery Workers

```bash
celery -A app.workers.celery worker --loglevel=info
celery -A app.workers.celery beat --loglevel=info
```

| Worker | Responsibility |
|---|---|
| `report_worker` | Async report generation, PDF/XLSX export |
| `alert_worker` | Alert evaluation and notification dispatch |
| `celery beat` | Cron-based scheduled report triggers |

### Kafka Consumers

```bash
python -m app.workers.kafka.consumer
```

| Topic | Consumer | Purpose |
|---|---|---|
| `cv.detections` | Events consumer | Ingests raw AI detection events |
| `cv.alerts` | Alerts consumer | Triggers alert evaluation |
| `cv.analytics` | Analytics consumer | Feeds analytics aggregation |

---

## AI Services

Located in `app/services/ai/`:

| Service | File | Description |
|---|---|---|
| Person Detection | `person_detection.py` | YOLO11-based people detection + counting |
| Face Recognition | `face_recognition.py` | Known/unknown person identification |
| Occupancy | `occupancy.py` | Zone occupancy tracking |
| Intrusion | `intrusion.py` | Restricted zone breach detection |
| Loitering | `loitering.py` | Dwell-time based loitering detection |

Production inference via **NVIDIA Triton Inference Server**. Development uses `ultralytics` / `OpenCV` directly.

---

## Notification Services

Located in `app/services/notifications/`:

| Service | File | Provider |
|---|---|---|
| Email | `email.py` | SMTP (Gmail / SendGrid) |
| WhatsApp | `whatsapp.py` | Twilio WhatsApp Business API |
| SMS | `sms.py` | Twilio SMS |

---

## Database Migrations

```bash
alembic init app/database/migrations
alembic revision --autogenerate -m "add_organizations_table"
alembic upgrade head
alembic downgrade -1
```

---

## API Response Format

**Success:**
```json
{
  "success": true,
  "data": { ... },
  "message": "Operation successful",
  "meta": { "page": 1, "limit": 50, "total": 243 }
}
```

**Error:**
```json
{
  "success": false,
  "error": {
    "code": "FORBIDDEN",
    "message": "You do not have permission to access this resource",
    "details": null
  }
}
```

---

## Error Codes

| Code | HTTP | Description |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid JWT token |
| `FORBIDDEN` | 403 | Insufficient role or permission |
| `NOT_FOUND` | 404 | Resource not found |
| `VALIDATION_ERROR` | 422 | Invalid request body/params |
| `TENANT_MISMATCH` | 403 | Attempt to access another org's data |
| `ORG_SUSPENDED` | 403 | Organization is suspended |
| `CAMERA_OFFLINE` | 503 | Camera stream unreachable |
| `CAMERA_NOT_FOUND` | 404 | Camera ID does not exist |
| `ZONE_OVERLAP` | 409 | Zone polygon overlaps existing zone |
| `STORAGE_ERROR` | 500 | File upload/download failure |
| `INFERENCE_ERROR` | 500 | AI model inference failure |
| `REPORT_GENERATION_FAILED` | 500 | Report generation error |
| `DUPLICATE_EMAIL` | 409 | Email already registered |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password |
| `TOKEN_EXPIRED` | 401 | JWT access token expired |
| `REFRESH_TOKEN_INVALID` | 401 | Refresh token invalid or blacklisted |
| `PERMISSION_DENIED` | 403 | User lacks required permission key |

---

## License

Proprietary — Computer Vision Analytics Platform © 2025
