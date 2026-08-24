# Current Chat Agent Flow

This diagram reflects the current LangGraph and WebSocket booking implementation.

```mermaid
flowchart TD
    A[User message] --> B[Read message and apply explicit corrections]
    B --> C{Short closing thanks?}
    C -- Yes --> D[Final acknowledgement]
    D --> Z([End / wait for next message])
    C -- No --> E{Intent and urgency classification}

    E -- Clinic inquiry --> F[RAG website search]
    F --> G[Answer from clinic information]
    G --> Z

    E -- Conversation --> H[Supportive non-clinical response]
    H --> Z

    E -- Critical, no booking request --> I[Urgent safety guidance]
    I --> Z

    E -- Booking, including urgent + booking --> J[Extract volunteered intake facts]
    J --> K{Age eligible?}
    K -- Missing --> L[Ask age]
    L --> K
    K -- No --> M[Explain eligibility and allow correction]
    M --> Z
    K -- Yes --> N{Feels safe now?}
    N -- Missing --> O[Ask safety question]
    O --> N
    N -- No --> P[Urgent guidance and acknowledgement]
    P --> Q{Continue non-emergency booking?}
    Q -- No --> Z
    Q -- Yes --> R[Collect missing intake answers]
    N -- Yes --> R
    R --> S[One contact-details form]
    S --> T[Emit booking UI once]
    T --> U[Show calendar-connected doctors]
    U --> V[Choose date and available time]
    V --> W[Confirm and create appointment]
    W --> X[Mark booking completed]
    X --> Z

    B -. Corrected age .-> J
```

Calendar connection health is maintained separately from the chat graph by
`carecoordinator-calendar-health.timer`. It runs the maintenance container
approximately every 15 minutes and updates each doctor's connection status.
