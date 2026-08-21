# Part D — System design and implementation

## Architecture

The deliverable is a scheduled Python CLI backed by SQLite. A server is not
required: cron invokes the same idempotent command three times daily, and every
run rebuilds current recall facts from the latest CSV exports before acting on
persisted outreach state.

```text
patients.csv + appointments.csv
              │
              ▼
     validate and derive recall state
              │
              ├── cancel sequences with a new booking
              ▼
       weekly paced enrollment
              │
              ▼
        SQLite message queue
              │
              ▼
      dry-run log or Resend API
```

SQLite stores patients, weekly pacing windows, enrollments, three scheduled
touches per enrollment, suppressions, cooldowns, and delivery attempts. The
database is the system's memory; repeat runs do not recreate an existing weekly
plan or resend a message already marked `sent`.

## State transitions

```text
eligible ──enroll──> active
                       ├── future booking detected ──> booked
                       ├── opt-out/suppression ──────> cancelled
                       └── third touch sent ─────────> completed_no_response
                                                          │
                                                   90-day cooldown
                                                          │
                                                          ▼
                                                   recontact eligible
```

Each message moves from `pending` to `sending` to `sent`. The transition into
`sending` is atomic. Every message receives a globally unique key that is saved
with it; if a process stops after claiming the message, a later run releases
the stale claim and retries with that same Resend idempotency key.

After a booking, the patient remains suppressed until that appointment becomes
a completed visit. They can enter a new recall cycle only when that later visit
itself becomes more than six months old and nothing new is booked.

## Booking timing and race limitation

Every scheduled run ingests the newest appointment export and cancels pending
touches for patients with a future non-cancelled booking. Eligibility is checked
again immediately before each email is claimed.

CSV polling cannot eliminate the small interval between the last export and the
email API call. A production integration would consume booking webhooks and
cancel pending messages immediately. The polling approach is the explicit
time-boxed limitation for this take-home dataset.

## Safety and operations

- Delivery is dry-run unless `--send` is supplied.
- A live demonstration can redirect one due message to a controlled inbox with
  `--recipient-override` and `--delivery-limit 1`.
- `pause` blocks both planning and delivery while preserving all SQLite state.
- Manual suppression persists an opt-out and cancels remaining touches.
- The supplied dataset and all local databases are ignored by Git.

## Real email demonstration

On 2026-08-20, the final verification run sent exactly one controlled email
through Resend using `--recipient-override` and `--delivery-limit 1`. It used
the latest Hot-segment copy, including the derived months since last visit.
Resend returned a provider message ID, and the engine persisted the message as
`sent`. No synthetic dataset address received email.

![Live email delivered through Resend](assets/resend_live_email.png)

## Core tests

The unit suite uses temporary CSV fixtures, isolated SQLite databases, and a
fake email sender. It verifies:

- overdue, future-booked, inactive, missing-provider/status, no-history, and
  cancelled-future eligibility cases;
- exact Hot, Warm, Cold, and Very Cold calendar-month boundaries;
- month-count personalization, including clamped month-end dates;
- one enrollment plan per week;
- no repeat delivery after a successful touch;
- booking conversion and cancellation of remaining touches;
- durable opt-out suppression and blocked re-enrollment; and
- final-touch completion with a 90-day cooldown.

Run it with:

```bash
python3 -m unittest discover -s tests -v
```

Current result: **9 tests passed**.

## What I would do with more time

- **Use real-time booking data.** I would replace CSV polling with a practice-
  management integration and booking webhook so outreach stops as soon as a
  patient schedules.
- **Move the local system to managed infrastructure.** Postgres would replace
  SQLite, EventBridge would run the planner, and SQS would feed due emails to
  Lambda or ECS workers. Postgres would still own the Day 8 and Day 21 schedule;
  SQS would buffer delivery work and prevent bursts.
- **Secure configuration.** Practice links and settings would come from trusted
  configuration, while Resend and database credentials would live in AWS
  Secrets Manager with least-privilege access.
- **Add monitoring and alerts.** I would track delivery failures, retries,
  queue age, missed runs, bookings, unsubscribes, and results by segment and
  touch. CloudWatch would alert the on-call team when delivery health or the
  scheduled pipeline falls outside its normal range.
- **Build basic staff tools.** A small authenticated interface would show the
  backlog, active sequences, outcomes, delivery health, and pause/resume
  controls without requiring direct CLI or database access.
- **Learn from results.** I would compare conversion and unsubscribe rates
  across segments, templates, touch counts, and send times, then adjust the
  copy and pacing using those results.
- **Tune capacity from real usage.** CPU, memory, queue depth, provider limits,
  and appointment availability would determine worker concurrency and daily
  send volume rather than relying permanently on the take-home defaults.
