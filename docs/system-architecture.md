# System Architecture and User Flows

These diagrams describe the implemented Django application and its typical
deployment. Mermaid diagrams render in GitHub and compatible Markdown viewers.

## System architecture

```mermaid
flowchart TB
    Browser["Customer / Staff / Admin browser"]
    CDN["CDN assets: Bootstrap, Flatpickr, Chart.js"]
    Proxy["Nginx reverse proxy<br/>TLS termination"]
    Django["Gunicorn<br/>Django WSGI application"]
    MW["Django middleware<br/>Security · Sessions · CSRF · Auth · Messages"]
    Templates["Templates + static UI<br/>HTML · CSS · JavaScript"]
    WhiteNoise["WhiteNoise<br/>collected static assets"]
    Accounts["accounts app<br/>Email login · roles · profiles"]
    Vehicles["vehicles app<br/>Catalog · locations · images · maintenance"]
    BookingViews["bookings app<br/>Views · JSON availability API"]
    Services["Booking services<br/>Availability · Pricing · Reservations · Lifecycle"]
    Dashboard["dashboard app<br/>Operations · reports · CSV"]
    Core["core app<br/>Role access · policy settings · audit log"]
    MySQL[("MySQL 8<br/>users · fleet · reservations · payments · audit")]
    Media[("Persistent media storage<br/>uploads · WebP thumbnails")]
    SMTP["SMTP / console email backend"]
    Cron["Scheduler<br/>send_reminders management command"]

    Browser -->|HTTPS requests| Proxy
    CDN -.-> Browser
    Proxy -->|Forwarded host and HTTPS headers| Django
    Django --> MW
    MW --> Templates
    Templates --> WhiteNoise
    MW --> Accounts
    MW --> Vehicles
    MW --> BookingViews
    MW --> Dashboard
    Accounts --> MySQL
    Vehicles --> MySQL
    Vehicles --> Media
    BookingViews --> Services
    Services --> MySQL
    Services --> Vehicles
    Services --> Core
    Dashboard --> MySQL
    Dashboard --> Services
    Core --> MySQL
    Accounts --> SMTP
    Services --> SMTP
    Cron --> Django
    Cron --> SMTP
```

### Request and booking boundaries

- The browser uses Django-rendered pages, ordinary form posts, and the
  read-only availability endpoints.
- Django middleware applies security headers, session/authentication handling,
  CSRF checks, and message handling before application views.
- Views perform request validation and authorization, while reservation,
  availability, pricing, cancellation, and lifecycle rules live in service
  modules.
- Reservation creation is transactional: it locks the vehicle row and checks
  availability again before saving the reservation and its price snapshot.
- MySQL stores application records. Uploaded images and their generated
  thumbnails live in persistent media storage; WhiteNoise serves collected
  static files.
- The production Nginx sample terminates HTTPS and forwards
  `X-Forwarded-Proto` to Django. Deployments must use trusted proxy
  configuration and persistent storage for media.

## Customer user flow

```mermaid
flowchart TD
    Start([Open rental site]) --> Browse["Browse home or vehicle catalog"]
    Browse --> Dates{"Search by rental dates?"}
    Dates -->|Yes| Search["Enter pickup and return"]
    Dates -->|No| Catalog["Browse / filter catalog"]
    Search --> Results["Show vehicles available for dates"]
    Catalog --> Detail["Open vehicle details"]
    Results --> Detail
    Detail --> Auth{"Signed in as customer?"}
    Auth -->|No| Login["Register or sign in"]
    Login --> Return["Return to booking flow"]
    Auth -->|Yes| Licence{"Profile and license valid through return?"}
    Return --> Licence
    Licence -->|No| EditProfile["Complete or update profile"]
    EditProfile --> Licence
    Licence -->|Yes| Request["Choose dates and locations"]
    Request --> Check["Server validates request and availability"]
    Check -->|Unavailable / invalid| Request
    Check -->|Available| Draft["Save booking draft in session"]
    Draft --> Review["Review quote: rental · discount · tax · deposit"]
    Review --> Confirm{"Confirm reservation?"}
    Confirm -->|No| Browse
    Confirm -->|Yes| Atomic["Atomic create; lock vehicle; recheck availability"]
    Atomic -->|Conflict / validation error| Results
    Atomic --> Payment["Choose mock card or pay at pickup"]
    Payment --> Confirmation["View confirmation and reference"]
    Confirmation --> Manage["My bookings: details · receipt · book again"]
    Manage --> Change{"Modify or cancel?"}
    Change -->|Modify| Modify["Apply cutoff and availability rules"]
    Change -->|Cancel| Cancel["Show policy fee; cancel if allowed"]
    Modify --> Manage
    Cancel --> Manage
```

## Staff and administrator user flow

```mermaid
flowchart TD
    SignIn["Staff/admin signs in"] --> Role{"Role check"}
    Role -->|Customer or guest| Denied["Redirect to sign-in or deny access"]
    Role -->|Staff| StaffHome["Staff dashboard"]
    Role -->|Admin| AdminHome["Admin dashboard"]
    StaffHome --> Reservations["Search and review reservations"]
    StaffHome --> Vehicles["View fleet and update vehicle status"]
    StaffHome --> Customers["Search and view customer history"]
    AdminHome --> Reservations
    AdminHome --> Vehicles
    AdminHome --> Customers
    AdminHome --> FleetAdmin["Create/edit/retire vehicles<br/>Manage images and maintenance"]
    AdminHome --> People["Manage customers and staff access"]
    AdminHome --> Policies["Update pricing and booking policies"]
    AdminHome --> Reports["Reports, charts, and CSV export"]
    AdminHome --> Audit["Review audit log"]
    Reservations --> Status{"Current reservation state"}
    Status -->|Pending| Confirm["Confirm or cancel"]
    Status -->|Confirmed| Pickup["Record odometer and fuel at pickup"]
    Status -->|Active| Return["Record return, fuel, damage, late fee"]
    Status -->|Completed / Cancelled| History["View reservation history"]
    Confirm --> AuditEvent["Record applicable changes in audit log"]
    Pickup --> AuditEvent
    Return --> AuditEvent
    FleetAdmin --> AuditEvent
    People --> AuditEvent
    Policies --> AuditEvent
```

## Main application URLs

| Area | URL prefix | Typical use |
|---|---|---|
| Public home | `/` | Search rental dates and see featured vehicles |
| Accounts | `/accounts/` | Register, login, profile, password reset |
| Vehicle catalog | `/vehicles/` | Browse, filter, and inspect vehicles |
| Booking API | `/api/` | Availability quote and booked-date data |
| Customer bookings | `/bookings/` | Create, review, manage, and print reservations |
| Staff/admin dashboard | `/dashboard/` | Fleet, lifecycle, customers, and reports |
| Django admin | `/admin/` | Django administration for authorized staff |
