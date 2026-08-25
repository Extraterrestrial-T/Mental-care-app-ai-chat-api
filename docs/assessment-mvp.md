# Mental Health Assessment MVP

## Included

- Dedicated `/assessment` page linked from CeCe.
- PHQ-A for ages 12-17 and PHQ-9 for ages 18-25.
- Fixed, versioned question text and deterministic server-side scoring.
- Required safety follow-up when item 9 is positive.
- Contact and consent collected after the screening questions.
- Firestore persistence in `mental_health_assessments` with a review status.

## Required Before Production

1. Corner Health clinical leadership must approve the instruments, wording,
   eligible ages, review ownership, response targets, and escalation protocol.
2. Build an authenticated staff queue for `pending_clinical_review` and
   `requires_immediate_action`; collection without an owned review process is not
   an acceptable production workflow.
3. Add abuse controls and rate limiting to the public submission endpoint.
4. Complete privacy, retention, access-control, audit, and vendor/BAA review for
   assessment data.
5. Confirm whether Corner Health wants direct scheduling at all. Their published
   process may require clinical screening and staff matching before scheduling.

RAAPS is intentionally excluded until the clinic confirms that it has the
necessary license and approves its use.
