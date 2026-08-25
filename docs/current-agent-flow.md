# Current Chat and Assessment Flow

This reflects the conversational-first LangGraph, the secondary booking branch,
and the separate deterministic screening page.

```mermaid
flowchart TD
    A[User message] --> B[Read message and apply corrections]
    B --> C{Explicitly stop booking?}
    C -- Yes --> D[Clear booking state and return to conversation]
    C -- No --> E{Safety and intent routing}

    E -- Immediate risk --> F[Urgent human safety guidance]
    F --> Z([Wait for next message])

    E -- Clinic or service question --> G[RAG website search]
    G --> H[Direct clinic answer]
    H --> Z

    E -- Emotional support or conversation --> I[Supportive non-clinical response]
    I --> Z

    E -- Mental health assessment --> J[Offer separate check-in page]
    J --> K[Age selects PHQ-A or PHQ-9]
    K --> L[Deterministic questions and scoring]
    L --> M{Item 9 positive?}
    M -- Yes --> N[Required ASQ safety follow-up]
    M -- No --> O[Contact and consent]
    N --> O
    O --> P[Versioned Firestore record for staff review]
    P --> Z

    E -- Explicit booking --> Q[Show approved calendar-connected clinicians]
    Q --> R[User selects clinician]
    R --> S[Collect age and safety check]
    S --> T{Eligible and safe to continue?}
    T -- No --> U[Safety or alternate-support guidance]
    U --> Z
    T -- Yes --> V[Collect intake and one contact form]
    V --> W[Show selected clinician calendar]
    W --> X[Confirm appointment]
    X --> Z
```

## Operational Boundaries

- The LLM may route and converse, but it does not alter screening questions,
  calculate scores, diagnose, or decide the screening safety level.
- A booking decline clears the current booking thread, including paused forms.
- Only clinicians with `published_on_website=true`,
  `accepting_online_bookings=true`, `is_demo!=true`, and a healthy calendar are
  shown in the public booking UI.
- `carecoordinator-calendar-health.timer` maintains calendar connection status
  separately from both user workflows.
- Screening submissions require a clinic-owned staff review queue and escalation
  policy before production launch. The public page explicitly states that it is
  not monitored as an emergency service.
