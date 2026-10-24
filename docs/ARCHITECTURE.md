# LeaseDesk — Architecture

Diagrams render on GitHub. Three levels: system context, container/component,
and the runtime sequence for the exception path.

---

## 1. High level — system context

```mermaid
flowchart TB
    subgraph sources["External sources"]
        PDF["Lease PDFs<br/>+ amendments"]
        MAIL["Email threads<br/>(facilities, landlord)"]
        INV["Landlord invoices"]
        BANK["Bank / AP feed"]
    end

    subgraph leasedesk["LeaseDesk"]
        ING["Ingestion"]
        ORCH["Orchestrator"]
        ENGINE["Accounting Engine<br/>(deterministic)"]
        STORE[("Store +<br/>Audit Trail")]
    end

    subgraph people["People"]
        AP["AP clerk"]
        CTRL["Controller"]
    end

    GL["General Ledger<br/>(NetSuite / SAP)"]

    PDF --> ING
    MAIL --> ING
    INV --> ING
    BANK --> ING
    ING --> ORCH
    ORCH <--> ENGINE
    ORCH <--> STORE
    ENGINE --> STORE
    STORE --> CTRL
    CTRL -->|"sign-off"| STORE
    STORE -.->|"ready_to_post"| GL
    AP -.->|"pays rent"| BANK

    classDef det fill:#1f6f43,stroke:#0d3d24,color:#fff
    classDef llm fill:#8a4b1f,stroke:#5c2f12,color:#fff
    class ENGINE det
    class ORCH llm
```

**Read it as:** everything enters through ingestion, the orchestrator decides
which agent runs, the engine does all arithmetic, and nothing reaches the GL
without a controller's signature.

---

## 2. Container level — what runs where

```mermaid
flowchart LR
    subgraph fe["Frontend — Next.js 15 + Tailwind + shadcn/ui"]
        DASH["Dashboard"]
        LIST["Leases list"]
        EXC["Exception detail<br/>(the money screen)"]
        AUDIT["Audit trail"]
    end

    subgraph be["Backend — FastAPI (Python 3.11)"]
        API["REST + SSE layer"]
        ORCH["Orchestrator<br/>(state machine)"]
        subgraph agents["Agents"]
            EX["Extractor"]
            RE["Reconciliation"]
            IN["Investigation"]
        end
        ENG["leasedesk/<br/>schedule · reconcile · remeasure"]
    end

    DB[("SQLite<br/>(dev) / Postgres")]
    FILES[("Document store<br/>(local fs)")]
    CLAUDE["Claude API<br/>claude-opus-5-5"]
    SEARCH["Elastic<br/>(document search)"]

    DASH --> API
    LIST --> API
    EXC -->|"SSE"| API
    AUDIT --> API

    API --> ORCH
    ORCH --> EX
    ORCH --> RE
    ORCH --> IN
    EX --> CLAUDE
    IN --> CLAUDE
    IN --> SEARCH
    EX --> ENG
    RE --> ENG
    IN --> ENG
    ENG --> DB
    ORCH --> DB
    API --> FILES

    classDef det fill:#1f6f43,stroke:#0d3d24,color:#fff
    class ENG det
```

### Why FastAPI and not Next.js API routes

The accounting engine is already written and tested in Python. Wrapping it in
FastAPI costs about two hours. Reimplementing ASC 842 amortization in
TypeScript costs a day and throws away the test suite. **Do not rewrite the
engine.**

---

## 3. Low level — the exception path

The demo flow, end to end. This is the sequence to rehearse.

```mermaid
sequenceDiagram
    autonumber
    participant Bank
    participant API as FastAPI
    participant Orch as Orchestrator
    participant Rec as Reconciliation
    participant Inv as Investigation
    participant Claude
    participant Eng as Engine
    participant DB
    participant UI as Exception screen
    participant Ctrl as Controller

    Bank->>API: POST /ingest/payment ($17,400, Jul 2026)
    API->>Orch: PaymentReceived
    Orch->>Rec: check(schedule_v1, payment)
    Rec->>DB: read active schedule
    DB-->>Rec: expected $19,626.65
    Rec-->>Orch: variance −$2,226.65
    Orch->>DB: create Exception(exc_014_jul)
    Note over UI: Store 14 turns amber on the dashboard

    Ctrl->>UI: opens exception
    UI->>API: POST /exceptions/exc_014_jul/investigate
    API-->>UI: SSE: searching documents…
    API->>Orch: ExceptionCreated
    Orch->>Inv: investigate(exception, corpus)
    Inv->>Claude: find_amendment(variance, [eml, pdf…])
    Claude-->>Inv: FoundAmendment + quote + confidence 0.94
    API-->>UI: SSE: found 2026-06-18 amendment
    Inv->>Eng: remeasure(lease, effective=2026-07-01)
    Eng-->>Inv: Δliability +$443,255.70, entries[]
    Inv->>DB: InvestigationResult + schedule_v2 + proposed entries
    API-->>UI: SSE: complete

    UI->>Ctrl: before/after schedules + entries + source quote
    Ctrl->>API: POST /exceptions/exc_014_jul/approve
    API->>DB: schedule_v2 active, entries ready_to_post
    API->>DB: AuditEvent(human_approved=true)
    API-->>UI: status balanced
    Note over UI: Store 14 turns green
```

---

## 4. Low level — orchestrator state machine

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Extracting: DocumentReceived
    Extracting --> Scheduling: terms extracted
    Scheduling --> Balanced: schedule built
    Idle --> Reconciling: PaymentReceived
    Reconciling --> Balanced: match
    Reconciling --> Exception: mismatch
    Exception --> Investigating: investigate()
    Investigating --> PendingReview: evidence + entries
    Investigating --> Escalated: no explanation found
    Investigating --> Escalated: confidence < 0.7
    PendingReview --> Balanced: controller approves
    PendingReview --> Escalated: controller rejects
    Escalated --> Investigating: new document arrives
    Balanced --> Reconciling: next payment
```

`Escalated` is a first-class state, not an error path. Show it in the demo.

---

## 5. Data model

```mermaid
erDiagram
    LEASE ||--o{ RENT_STEP : has
    LEASE ||--o{ AMENDMENT : has
    LEASE ||--o{ SCHEDULE : has
    LEASE ||--o{ PAYMENT_EVENT : receives
    LEASE ||--o{ EXCEPTION : raises
    SCHEDULE ||--o{ SCHEDULE_PERIOD : contains
    AMENDMENT ||--o{ RENT_STEP : revises
    EXCEPTION ||--|| INVESTIGATION : explained_by
    INVESTIGATION ||--o{ EVIDENCE : cites
    INVESTIGATION ||--o{ JOURNAL_LINE : proposes
    EVIDENCE }o--|| DOCUMENT : from
    AMENDMENT }o--|| DOCUMENT : sourced_from

    LEASE {
        string lease_id PK
        string location
        string lessor
        date commencement
        date end_date
        float discount_rate
        string classification
        string status
    }
    SCHEDULE {
        string schedule_id PK
        int version
        date effective_from
        bool active
        float opening_liability
        float opening_rou
    }
    SCHEDULE_PERIOD {
        date period
        float payment
        float interest
        float liability_open
        float liability_close
        float rou_close
        float straight_line_cost
    }
    EXCEPTION {
        string exception_id PK
        date period
        float expected
        float actual
        string status
    }
    INVESTIGATION {
        string investigation_id PK
        string root_cause
        float confidence
        bool explains_variance
    }
    EVIDENCE {
        string doc_id FK
        string quote
        date doc_date
    }
    JOURNAL_LINE {
        string account
        float debit
        float credit
        string state
    }
    AUDIT_EVENT {
        string event_id PK
        datetime ts
        string actor
        string action
        string lease_id
        bool human_approved
    }
```

`AUDIT_EVENT` has no foreign keys by design — it is append-only and must
survive anything being deleted or superseded.

---

## 6. API surface

Build in this order. The first four are the demo.

| # | Method | Path | Returns | Needed by |
| --- | --- | --- | --- | --- |
| 1 | `GET` | `/api/leases` | Portfolio list with status | Dashboard, Leases |
| 2 | `GET` | `/api/exceptions` | Open exceptions | Dashboard |
| 3 | `GET` | `/api/exceptions/{id}` | Exception + investigation + entries + schedules | Exception screen |
| 4 | `POST` | `/api/exceptions/{id}/approve` | New status | Sign-off |
| 5 | `POST` | `/api/exceptions/{id}/investigate` | **SSE** event stream | The timeline |
| 6 | `GET` | `/api/leases/{id}/schedule?version=` | Schedule rows | Before/after view |
| 7 | `GET` | `/api/audit?lease_id=` | Audit events | Audit trail |
| 8 | `POST` | `/api/ingest/payment` | Match result | Live payment demo |
| 9 | `POST` | `/api/ingest/document` | Extracted terms | Live upload demo |

### SSE event shape

```json
{"stage": "searching",  "message": "Searching 1,284 documents…"}
{"stage": "found",      "doc_id": "eml_20260618", "quote": "Base rent reduced to $17,400 per month effective July 1, 2026.", "confidence": 0.94}
{"stage": "remeasured", "liability_delta": 443255.70, "rou_delta": 443255.70}
{"stage": "complete",   "entries": 4, "balanced": true}
```

Four events is enough for a timeline that feels alive. Do not over-engineer it.

---

## 7. Frontend structure

```
web/
├── app/
│   ├── page.tsx                      # Dashboard
│   ├── leases/page.tsx               # Portfolio list
│   ├── leases/[id]/page.tsx          # Lease detail + schedule
│   ├── exceptions/[id]/page.tsx      # THE MONEY SCREEN
│   └── audit/page.tsx                # Audit trail
├── components/
│   ├── MetricTile.tsx                # Active leases, open exceptions, STP %
│   ├── StatusBadge.tsx               # balanced | exception | pending_review
│   ├── InvestigationTimeline.tsx     # consumes SSE
│   ├── ScheduleDiff.tsx              # before/after, side by side
│   ├── JournalEntryTable.tsx         # debits/credits + balance assertion
│   ├── EvidenceCard.tsx              # quote + source doc + confidence
│   └── AgentActivityFeed.tsx         # three agents, last action each
└── lib/api.ts                        # typed fetch wrappers
```

**Build `ScheduleDiff` and `JournalEntryTable` against hardcoded JSON first.**
They are the two components the demo lives on; they must not be blocked waiting
for the API.

---

## 8. Deployment for demo day

Keep it local. Do not deploy.

| Concern | Decision |
| --- | --- |
| Where it runs | `localhost` — two terminals, FastAPI on :8000, Next on :3000 |
| Why not deployed | Venue Wi-Fi is the single most common demo failure |
| Network dependency | Only the Claude API, and only on `--live` / investigate |
| Offline fallback | Stored-amendment path needs no network at all |
| Backup | Recorded video on disk by H12 |

Run the whole demo once with Wi-Fi off and know exactly which step breaks.
