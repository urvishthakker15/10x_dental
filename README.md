# 10x Dental — Recall Outreach Engine

A stateful Python CLI that identifies overdue patients, enrolls a paced weekly
cohort, and advances a three-touch email sequence through Resend. SQLite keeps
the system idempotent across recurring runs. Delivery is dry-run by default.

Part A to Part C analysis (single document):
[Final Take-Home Submission](FINAL_TAKE_HOME_SUBMISSION.md)

## How it works

Each invocation:

1. validates and joins `patients.csv` and `appointments.csv`;
2. detects new future bookings and cancels remaining touches;
3. creates the current week's plan once, using the Part B 90% / 5% / 5% mix;
4. sends only messages currently due; and
5. persists decisions, attempts, cooldowns, and provider IDs in SQLite.

First touches are spread across 8am, 2pm, and 7pm over seven days. Follow-ups
are scheduled for Days 8 and 21. The engine can be run three times daily from
cron without recomputing or losing prior state.

## Codebase map

| File | Responsibility |
| --- | --- |
| `recall_engine/cli.py` | Commands, arguments, safe-mode selection, and output |
| `recall_engine/eligibility.py` | CSV validation and patient-level recall derivation |
| `recall_engine/engine.py` | Pacing, enrollment, suppression, sequence transitions, and idempotency |
| `recall_engine/database.py` | SQLite schema and transactions |
| `recall_engine/templates.py` | Segment-specific text and HTML email rendering |
| `recall_engine/delivery.py` | Dry-run and Resend delivery adapters |
| `recall_engine/models.py` | Typed records passed between layers |

Detailed writeups:

- [Part A — data analysis](docs/part_a_analysis.md)
- [Part B — selection and pacing](docs/part_b_selection_and_pacing.md)
- [Part C — communication strategy](docs/part_c_communication_strategy.md)
- [Part D — system design and live-send proof](docs/part_d_system_design.md)

## Reproducing the analysis

All reported numbers come from committed Python scripts grouped by purpose:

| Folder | Contents |
| --- | --- |
| `analysis/overall_data_analysis/` | Source profiling, timezone validation, visit-type checks, and the patient-level last-visit derivation |
| `analysis/part_a/` | Overdue-rate, current-overdue-share, retention, and supporting demographic analyses |
| `analysis/part_b/` | Backlog/inflow calculations and the 12–24 month pacing simulations |

Run scripts from the repository root; `python <script_path> --help` lists the
CSV and date arguments. Reproducible output under `analysis/**/output/` is
excluded from Git.

## Setup

Python 3.9 or newer is required. SQLite and the dry-run path use only the
standard library.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
[ -f .env ] || cp .env.example .env
python -m recall_engine init-db
```

Run `source .venv/bin/activate` again whenever you open a new terminal. On
Windows PowerShell, activate it with `.venv\\Scripts\\Activate.ps1`.

For real delivery, set these local `.env` values:

```env
RESEND_API_KEY=replace_with_your_key
EMAIL_FROM=Recall Outreach <onboarding@resend.dev>
```

Use a sender on a verified domain for ordinary external recipients. `.env`,
SQLite databases, and the supplied assignment CSVs are ignored by Git.

## Run safely

This command creates the weekly plan and logs due email without sending it:

```bash
python3 -m recall_engine run \
  --patients /path/to/patients.csv \
  --appointments /path/to/appointments.csv \
  --dry-run \
  --practice-name "10x Dental" \
  --booking-link "https://example.com/book" \
  --unsubscribe-link "https://example.com/unsubscribe"
```

Dry-run does not mark a message as sent, so it can be inspected repeatedly.
Use `--as-of 2026-08-20T08:00:00-07:00` for a reproducible historical run.

## Send one controlled test

Real delivery requires `--send`. Redirect and limit the run when demonstrating
with an inbox you control:

```bash
python3 -m recall_engine run \
  --patients /path/to/patients.csv \
  --appointments /path/to/appointments.csv \
  --send \
  --recipient-override your-email@example.com \
  --delivery-limit 1 \
  --practice-name "10x Dental" \
  --booking-link "https://example.com/book" \
  --unsubscribe-link "https://example.com/unsubscribe"
```

The live delivery screenshot is in the [Part D writeup](docs/part_d_system_design.md).

## Operate it

```bash
python3 -m recall_engine status
python3 -m recall_engine pause
python3 -m recall_engine resume
python3 -m recall_engine suppress --patient-id PT-00001 --reason opted_out
```

Example production schedule after validating dry-run behavior:

```cron
0 8,14,19 * * * cd /path/to/repo && /usr/bin/python3 -m recall_engine run --patients /secure/patients.csv --appointments /secure/appointments.csv --practice-name "10x Dental" --booking-link "https://example.com/book" --unsubscribe-link "https://example.com/unsubscribe" --send >> /var/log/recall-engine.log 2>&1
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `RESEND_API_KEY` | None | Required only with `--send` |
| `EMAIL_FROM` | None | Required only with `--send` |
| `RECALL_TIME_ZONE` | `America/Los_Angeles` | Local due-date and send-slot calculations |
| `WEEKLY_ENROLLMENT_CAPACITY` | `100` | Weekly enrollment ceiling |

## Tests

Test configuration is declared in `pyproject.toml`:

```bash
python3 -m unittest discover -s tests -v
```

The same suite also runs under pytest after `python3 -m pip install -e '.[test]'`.

## Assumptions

| Assumption | Rationale |
| --- | --- |
| `is_active = true` and `status = Active` are authoritative. Missing provider or status blocks enrollment. | The export is treated as the practice’s active roster. Guessing ownership or lifecycle state could send inappropriate outreach. |
| A future non-cancelled appointment immediately suppresses outreach. Otherwise, recall age comes from the latest completed past visit. | Someone already returning should not receive overdue reminders; cancelled and incomplete appointments are not evidence of a visit. |
| “Overdue” means more than six calendar months, not 180 days. | This follows the business wording and handles unequal month lengths. |
| Every completed appointment category counts toward recall cadence. | The synthetic visit labels do not contain reliable clinical detail, so the system treats any completed visit as continued engagement without calling it a cleaning. |
| Patients without a completed visit or future booking are not labeled overdue. | The data cannot distinguish new patients from people whose history predates the export. A separate 5% weekly prospecting allocation reaches this lower-confidence group. |
| Missing birth dates remain `Unknown`; they do not block outreach. | Age is unnecessary for recall eligibility, and patient ID has no meaningful relationship with age. Missing gender is used only as `Other` in aggregate analysis. |
| UTC timestamps are the ordering source; calendar decisions use `America/Los_Angeles` by default. | The timezone column is empty, while UTC and wall-clock values strongly match Pacific time. The timezone remains configurable. |
| Conversion means booking after outreach, not completing the appointment. | Booking is the immediate outcome this engine can observe; attendance is a separate downstream metric. |
| Planning assumes 10% conversion and a ceiling of 100 enrollments per week. | That implies about 10 bookings per week versus 103.3 historical completed appointments per week; production would confirm real provider capacity before retaining the ceiling. |
| The first sequence uses three email touches on Days 0, 8, and 21, followed by a 90-day cooldown. | This balances visibility with patient experience. A fourth touch should be tested against incremental bookings and unsubscribes. |

## Next steps and time-boxed scope cuts

### What I would do next

- Ingest booking events and replies, turn clear responses into verified patient
  outcomes, and route ambiguous replies to staff.
- Measure bookings, completed visits, unsubscribes, complaints, and delivery
  health by segment and touch; use controlled tests to improve copy and timing.
- Use verified relocation responses as one input when evaluating new practice
  locations, while accounting for the self-selected sample.
- Move SQLite to Postgres, schedule planning with EventBridge, queue sends in
  SQS, store secrets securely, and add retries, dashboards, and alerts.
- Add basic authenticated staff tools, carefully approved seasonal campaigns,
  and AI-assisted drafting limited to verified facts and human review.
- Tune send volume and worker concurrency from appointment capacity, queue
  depth, resource use, and provider limits.

### Scope intentionally cut for this take-home

- The implementation is a scheduled CLI; UI, authentication, and staff
  administration are omitted.
- CSV polling stands in for booking webhooks and source-system integrations,
  leaving a documented race window between exports.
- Outreach is email-only. SMS and phone outreach require separate consent,
  preference, and compliance handling.
- Templates and timing live in code; there is no campaign editor, approval
  workflow, reply classifier, or experimentation platform.
- Booking links, availability, insurance information, practice updates, and
  the unsubscribe endpoint require verified production integrations. Sample
  URLs are placeholders; opt-outs can be demonstrated with `suppress`.
- SQLite is local-only; cloud infrastructure, deployment automation, paging,
  and dashboards are proposed rather than provisioned.
- The input contract requires only fields the engine uses; unused fields such
  as `phone` and `broken` remain optional.
- Tests target eligibility, segmentation, state transitions, and idempotency,
  not exhaustive integration or load coverage.
