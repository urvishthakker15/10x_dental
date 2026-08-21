# Recall Outreach Engine — Take-Home Submission

This document consolidates Parts A–C; Part D setup and evidence are in the
repository README and `docs/part_d_system_design.md`.

## Contents

1. Part A — Data analysis
2. Part B — Selection and pacing algorithm
3. Part C — Email sequence
4. Next steps and time-boxed scope cuts

## Part A — Data Analysis

### Purpose and reproducibility

All figures are reproducible from `analysis/part_a/` and
`analysis/overall_data_analysis/`; the source CSVs are excluded from Git.

### Assumptions and definitions

| Decision | Rule | Rationale |
| --- | --- | --- |
| Analysis date | Use the date the script runs, with an optional `as_of_date` override that is printed in the output. | Operational runs need the current date; the override reproduces historical results. |
| Future appointment | Any future appointment that is not cancelled means the patient is already booked. | This is the brief’s stated rule; a booked patient should not be labeled overdue for outreach. |
| Last completed visit | If no qualifying future booking exists, use the latest completed past appointment. | Cancelled and broken appointments are not evidence that care occurred. |
| Overdue threshold | More than six calendar months, rather than 180 days. | “Six months” is the business definition and calendar arithmetic handles variable month lengths correctly. |
| No usable history | Do not label patients with neither a completed past visit nor a future booking as overdue. Report them separately. | Their history may be incomplete or they may be new/no-show patients; “overdue for cleaning” would be an unsupported claim. |
| Visit type | Count every completed appointment category when measuring recall cadence. | A visit of any category is treated as continued engagement with the practice; the export does not contain reliable clinical detail to infer whether cleaning also occurred. |
| Patient lifecycle | Treat `is_active = true` as authoritative; do not infer deactivation, mortality, or relocation from appointment gaps. | The assignment supplies an active roster, and lifecycle rules belong in the source practice-management system. |

### Data-quality observations

Initial profiling found 5,999 patient rows and 61,736 appointment rows.

- `appointments.time_zone` is blank for 100% of rows. The relationship
  between `start_time` and `wall_start_time` has UTC−08:00 winter and
  UTC−07:00 summer offsets; 61,734 of 61,736 wall-clock values match an
  `America/Los_Angeles` conversion.
- `appointments.operatory` is missing in 202 rows (0.33%); it is not needed
  for recall eligibility.
- `patients.birth_date` is missing in 146 rows (2.43%), while `gender`,
  `provider`, and `status` are each missing in only a handful of rows.
- `patients.deactivation_reason` is blank for every row, consistent with the
  file being active-only.
- Birth-date missingness appears in every 1,000-patient-ID range
  (1.90%–3.20%), so it does not point to one isolated historical import. It
  is higher among male records (3.15%) than female records (1.66%), and
  Provider A (2.51%) than Provider B (0.30%), but these dimensions do not
  determine recall eligibility.
- Patient ID is not a useful proxy for age: mean age varies only from 48.1 to
  50.2 across the six 1,000-ID cohorts, and the Pearson correlation between
  numeric patient ID and age is 0.006.
- One patient has a missing provider and one has a missing status. Both will
  be handled separately. Three patients have missing gender.
- There are 21 synthetic `visit_type` labels, but each maps to exactly one of
  the five supplied `visit_category` values: hygiene, other, exam,
  restorative, or emergency. No visit type spans multiple categories.

### Data-quality handling decisions

| Observation | Decision | Rationale |
| --- | --- | --- |
| `time_zone` is blank in every row, while wall-clock times strongly match Pacific Time behavior. | Store/order by UTC `start_time`; apply `America/Los_Angeles` for calendar-based recall dates. | This preserves the source-of-truth timestamp while aligning “today” and six-month due dates with practice-local time. |
| Birth date is missing for 146 patients and patient ID is not predictive of age. | Retain missing values as `Unknown age`; do not impute or exclude these patients from outreach. | Birth date is not required for recall eligibility, and imputation would manufacture unsupported demographic data for a material cohort. |
| One patient has a missing provider. | Exclude from outreach enrollment and record the exclusion. | We must not infer a provider: outreach appearing to come from the wrong clinician creates patient-trust and provider-relationship risk. |
| One patient has a missing status. | Exclude from outreach enrollment and record the exclusion. | Status is an operational eligibility field; withholding is safer than inventing a value. |
| Three patients have missing gender. | Map to `Other` for aggregate analysis only; do not use gender in eligibility or email copy. | This avoids forcing an unsupported binary value and has no effect on outreach logic. |
| `visit_type` is synthetic, while `visit_category` is a supplied stable grouping. | Use the five `visit_category` values as the reduced taxonomy; do not create a second manual mapping from labels. | The data validates this choice: every one of the 21 labels maps one-to-one to a category. It avoids treating a synthetic label as clinical truth. |
| A future `General Visit` is categorized as `other`, not `hygiene`. | Treat it as a future booking that suppresses outreach, but do not relabel it as a cleaning. | The brief explicitly says any future non-cancelled appointment means the patient is already returning. Calling `other` a cleaning would add an unsupported clinical assumption. |

#### Monitoring boundary

The engine reports exclusion counts but does not implement alerting. Production
would alert when missing-provider or missing-status rates materially exceed
their established baseline.

### Derived last-visit status (required first step)

The patient-level recall table joins both CSVs. Its
`effective_last_visit_date` is the nearest future non-cancelled booking when
one exists; otherwise it is the latest completed past visit. This prevents a
patient who is already booked from being labeled overdue.

#### Handling the no-completed-history cohort

The export cannot distinguish a new patient from someone whose history
predates the export or who now uses another practice. We therefore do not infer
the reason and assign `history_status` only when the effective date is blank:

| History status | Definition | Count |
| --- | --- | ---: |
| `no_appointment_records` | The patient has no appointment rows in this export. | 1,689 |
| `appointment_records_but_no_completed_or_future_booking` | The patient has appointment records, but none is a completed past visit or a future non-cancelled booking. | 28 |
| `not_applicable` | The patient has an effective last-visit date. | 4,282 |

The first two cohorts are not enrolled in the standard cleaning recall
sequence and are reported for operational review.

### 1. At what rate do patients become overdue?

> Once a patient is on a healthy recall cadence, how often do they slip past
> 6 months before their next visit?

#### Analysis and interpretation

We define a healthy recall cadence as two consecutive completed appointments
within six calendar months. Once a patient reaches that cadence, each later
appointment interval is an opportunity to either stay on schedule or slip past
six months.

For one patient, slipping on the first appointment after reaching healthy
cadence is a 1 / 1 (100%) lapse rate. A patient who never slips after reaching
healthy cadence has a 0% lapse rate. For the practice-level result, we combine
all slipped post-cadence appointments and divide them by all observed
post-cadence appointment opportunities.

A patient can return to healthy cadence after a lapse. That creates a new
healthy-cadence episode and is intentionally counted again: if they later slip
again, both episodes contribute to the aggregate rate.

#### Methodology

1. Group appointments by patient and order them by date.
2. Include completed past appointments; exclude cancelled, broken, and other
   non-completed past appointments. A future non-cancelled booking is used as
   the known next appointment for the final interval.
3. Mark a patient as on healthy cadence after two consecutive completed
   appointments within six calendar months.
4. Starting with the next appointment, count each interval over six months as
   a lapse and each interval within six months as on schedule.
5. Calculate:

   ```text
   slipped post-cadence intervals / observed post-cadence intervals
   ```

#### Notes

- All appointment categories count equally for this analysis. We assume any
  completed visit reflects continued engagement with the practice.
- An unresolved final interval is excluded until its six-month due date. If
  that date has passed with no future booking or completed visit, it is counted
  as an open lapse.
- The calculation is implemented in
  `analysis/part_a/calculate_overdue_rate.py` and uses the current date by default.

#### Result

**22.78%** of observed post-healthy-cadence appointment opportunities slipped
past six calendar months as of 2026-08-20.

| Calculation component | Count |
| --- | ---: |
| Active patients included | 5,998 |
| Patients who entered healthy cadence at least once | 3,261 |
| Healthy-cadence episodes | 8,185 |
| Observed post-healthy-cadence opportunities (denominator) | 32,630 |
| Intervals that slipped past six months (numerator) | 7,434 |
| Open lapses included in the numerator | 1,255 |
| Final intervals not yet due and therefore excluded (censored) | 285 |

The calculation is `7,434 / 32,630 = 22.78%`.

### 2. What percent of the active patient base is currently overdue *and* has nothing booked to bring them back?

#### Analysis and interpretation

Nearly half of the active patient base (44.86%) has a documented last visit
more than six months ago and no future appointment to bring them back. This is
a substantial recall backlog, not a small edge case that can be handled only
by waiting for routine scheduling.

This percentage is deliberately limited to patients whose last visit can be
established from the export. An additional 1,715 active patients have neither
a completed visit nor a future booking; they are not labeled overdue because
we cannot tell whether they are new, have history outside the export, or are
otherwise lapsed. They should be treated as a separate operational-review
cohort rather than folded into the recall backlog without evidence.

The result supports a paced, ongoing outreach program: the confirmed backlog
is large enough to matter, but enrolling everyone at once would create an
unsustainable one-time spike. The pacing recommendation is developed in Part
B using this backlog together with the measured newly-overdue inflow.

#### Methodology

1. Define the active patient base as patients where `is_active = true` and
   `status = Active`. We apply both filters even though the export is described
   as active-only, so the calculation remains reproducible against future
   similarly-shaped exports.
2. For each active patient, derive the effective last-visit date: use the
   nearest future non-cancelled booking when present; otherwise use the latest
   completed past appointment.
3. Count a patient in the numerator only when their effective last-visit date
   is more than six calendar months before the analysis date and they have no
   future non-cancelled booking.
4. Divide that count by the full active-patient base.

#### Notes

- Patients with no completed visit and no future booking are not included in
  the overdue numerator because the export does not establish a last-visit
  date for them.
- The calculation is implemented in
  `analysis/part_a/calculate_current_overdue_share.py` and uses the current date by
  default.

#### Result

**44.86%** of the active patient base is currently overdue and unbooked as of
2026-08-20.

| Calculation component | Count |
| --- | ---: |
| Active patients (denominator) | 5,997 |
| Currently overdue and unbooked (numerator) | 2,690 |
| Patients with a future non-cancelled booking | 1,144 |
| Patients with no completed visit or future booking | 1,715 |

The calculation is `2,690 / 5,997 = 44.86%`.

### 3. What's your estimate of this practice's retention rate? State how you're defining "retention" — there's no single industry-standard definition, so pick a reasonable one, justify it, and compute it.

#### Analysis and interpretation

For an established dental practice, retention is most useful as a yearly
measure; month-over-month retention would be more appropriate for a new
practice with little history. For this exercise, we use a rolling 12-month
window from the same date last year through the current date.

A retained patient is an active patient who was served during that 12-month
window and whose first **observed** completed visit occurred before the
window. Patients first observed during the window are treated as new-to-the-
export for this calculation and are excluded from the retained numerator.

#### Methodology

1. Define the active cohort as `is_active = true` and `status = Active`.
2. Use completed appointments only; future, cancelled, broken, and otherwise
   non-completed appointments do not count as a patient being served.
3. Count unique active patients with at least one completed appointment from
   the same date last year through the analysis date as patients served in the
   rolling 12-month window.
4. Count patients whose first observed completed appointment falls inside that
   window as first-time patients for the purpose of this estimate.
5. Calculate:

   ```text
   (unique patients served in the window - first-time patients served in the window)
   -----------------------------------------------------------------------------------
                          unique patients served in the window
   ```

#### Notes

- This is a rolling 12-month metric, so it avoids comparing a partial calendar
  year with a full year and should be recalculated as time moves forward.
- “First-time” means first observed in this export. A patient with completed
  care before the export began could be classified as first-time by this
  method, so the metric should be read as an estimate.
- All completed appointment categories count as service for this metric.
- The calculation is implemented in
  `analysis/part_a/calculate_retention_rate.py`.

#### Result

**73.28%** rolling 12-month retention for 2025-08-20 through 2026-08-20.

| Calculation component | Count |
| --- | ---: |
| Unique active patients served in the rolling 12-month window | 1,871 |
| Patients first observed as served in the window | 500 |
| Retained patients | 1,371 |

The calculation is `(1,871 - 500) / 1,871 = 73.28%`.

### 4. Assuming a 10% conversion rate on your outreach sequence, what would you recommend to meaningfully improve the practice's numbers?

> This is a business-reasoning question as much as a data one — we want to
> see how you think about levers (volume, cadence, segmentation, copy,
> timing), not just a single "run the sequence" answer.

#### Analysis and interpretation

For this recommendation, a **conversion** means a patient who receives
outreach subsequently books an appointment. It does not mean that the patient
has completed the appointment; completion is a separate downstream outcome to
track.

At a 10% booking conversion rate, every 100 patients enrolled is expected to
produce roughly 10 future bookings. Applied to the confirmed current backlog
of 2,690 overdue and unbooked patients, a one-time program would imply roughly
269 bookings. That demonstrates material upside, but it should not be sent as
a single blast: volume must be paced to available appointment capacity and
continued as newly overdue patients enter the pool.

#### Recommendations

| Overdue duration | Goal | Recommended outreach |
| --- | --- | --- |
| 6–9 months | Remove friction for patients who may already intend to return. | Send a warm reminder with a small set of specific appointment slots or a direct self-scheduling link. If future data includes the patient’s usual clinician and provider capacity, prioritize slots with that clinician. |
| 9–18 months | Re-engage patients who are becoming cold. | Mention verified practice improvements from the last year, ask whether insurance or scheduling needs have changed, and send up to three touches unless the patient books, replies, or opts out. |
| 18–36 months | Recapture patients who may now be using another practice. | Time outreach for lower-demand periods and test a modest return incentive, such as a $25 gift card. Mention relevant new locations or services only when those claims are current and verified. |
| More than 36 months | Confirm continued relevance before repeated outreach. | Send a respectful reactivation message that asks whether the patient is still local and interested in care. Suppress or move the patient to a low-frequency review path when there is no response, rather than repeatedly sending recall messages. |

#### Timing, capacity, and measurement

- Initially avoid standard work-hour sends. Spread delivery across early
  morning, late afternoon, and evening in the practice’s local timezone, then
  measure booking conversion by send window and keep the best-performing
  windows.
- Start with the Part B ceiling of 100 enrollments per week, which projects the
  confirmed backlog clearing in about 43 weeks, and adjust to actual capacity.
- Measure enrollment volume, booking conversion, completed-visit conversion,
  booking lead time, reply/opt-out rate, and backlog size by overdue segment.
- Stop all pending touches immediately when a patient books, replies with a
  disposition, or opts out.

#### Notes

- The supplied dataset does not include a patient’s usual clinician, current
  provider capacity, appointment-slot inventory, insurance information, low
  season, practice upgrades, locations, or incentives. Those inputs would be
  required to operationalize the segment-specific recommendations above.
- The final sequence copy, touch spacing, and re-contact policy are developed
  in Part C; sustainable enrollment volume is developed in Part B.

## Part B — Selection & Pacing Algorithm

### Question

> Design (and justify, in writing) an algorithm that decides, on an ongoing
> basis, which patients to enroll into the outreach sequence and when.

The hard constraint is to assume a 10% conversion rate on contacted patients
while avoiding both an exhausted lead pipeline and a one-time dump of thousands
of emails.

### Objective and conversion definition

The algorithm continuously prioritizes eligible patients, enrolls only a
controlled weekly volume, and updates decisions from persisted outreach state.

For this plan, a **conversion** is a contacted patient who later books an
appointment. Appointment completion remains a separate downstream measure.

### Candidate pools

#### Confirmed recall backlog and newly overdue patients

Patients qualify for the standard recall pool only when they:

- have `is_active = true`, `status = Active`, and a present provider;
- have a documented completed visit more than six calendar months ago;
- have no future non-cancelled booking;
- are not in an active sequence, opted out, suppressed, or within cooldown.

These patients are segmented by overdue duration:

| Segment | Overdue duration | Outreach purpose |
| --- | ---: | --- |
| Hot | More than 6 but less than 9 months | Reduce booking friction for recently due patients |
| Warm | 9 to less than 18 months | Re-engage patients becoming less responsive |
| Cold | 18 to less than 36 months | Reactivate patients who may be using another practice |
| Very cold | More than 36 months | Low-frequency re-permission/reactivation outreach |

#### No-history prospecting

Patients with no recorded completed visit and no future booking are not called
overdue because the export cannot establish a last-visit date. They remain a
small, separate prospecting pool for a first-visit/reactivation message.

### Weekly allocation policy

Let `weekly_capacity` be the configurable number of new sequence enrollments
allowed that week.

| Share | Pool | Rule |
| ---: | --- | --- |
| 90% | Confirmed backlog + newly overdue | Allocate 50% Hot, 30% Warm, and 20% Cold/Very cold; reassign unused quota to the next eligible confirmed segment. |
| 5% | Cooled-down non-responders | A prior sequence finished without booking/reply and the patient has passed cooldown. Prioritize the lowest `sequence_attempt_count` first. |
| 5% | No-history prospecting | Low-frequency, separately worded first-visit/reactivation outreach. |

This protects newly overdue patients from being crowded out by older backlog or
prior non-responders, while preserving a small path to test potential value in
the ambiguous no-history cohort.

### State, tracking, and suppression

The system stores the following per-patient outreach state:

- `outreach_status`: `eligible`, `active`, `booked`,
  `completed_no_response`, `cooldown`, `recontact_eligible`, `opted_out`, or
  `suppressed`
- `first_enrolled_at`, `last_enrolled_at`, `last_touch_at`, and
  `sequence_completed_at`
- `booked_at` and booking outcome
- `enrollment_count` and `sequence_attempt_count`
- `cooldown_until` and latest outreach outcome

A patient cannot be enrolled while active. A detected booking immediately
cancels all pending touches and sets the status to `booked`. A non-responder
enters `cooldown` when their sequence completes; after three months, they can
compete only for the 5% re-contact allocation. Candidates are ordered by the
fewest prior sequence attempts, then the oldest eligible completion date. This
prevents repeatedly
contacting the same person while still allowing controlled reactivation.

Patients who book are not contacted again while booked or on schedule. They
can enter a future recall cycle only after a later completed visit and a new
six-month overdue period with no future booking.

### Ongoing run logic

Every daily or weekly run:

1. Ingests the latest CSV data and derives current recall state.
2. Suppresses any active sequence with a new booking, opt-out, or suppression.
3. Finds patients newly crossing the six-month threshold.
4. Calculates available capacity and fills the 90% / 5% / 5% pools.
5. Persists enrollment and touch decisions before sending, making reruns
   idempotent.
6. Sends only the touch due on that day and records the result.

### Data-backed inputs

| Input | Result | Role in pacing |
| --- | ---: | --- |
| Confirmed overdue backlog | 2,690 | Initial pool to clear gradually |
| Hot backlog | 187 | 50% confirmed-pool target |
| Warm backlog | 229 | 30% confirmed-pool target |
| Cold backlog | 339 | Included in 20% cold/very-cold target |
| Very cold backlog | 1,935 | Included in 20% cold/very-cold target |
| Observed newly-overdue flow | 1,404 in trailing 12 months; 27/week | Conservative steady-state inflow |
| Projected currently-on-time unbooked due dates | 448 in next 12 months; 8.6/week | Near-term lower-bound view; excludes future care cycles |
| Historical completed throughput | 103.3/week average; 111.5/week median | Practice-volume proxy, not a direct measure of open slots |

### Initial pacing recommendation

Set an initial ceiling of **100 enrollments/week**. With 10% booking
conversion, that produces roughly **10 expected bookings/week**, equivalent to
about 9.7% of the historical average weekly completed appointment volume
(10 / 103.3). We explicitly assume the practice can absorb ten incremental
recall bookings per week. The export does not contain actual open-slot data, so
this is a configurable planning assumption that must be reduced if operations
cannot support it.

| Pool | Enrollments/week |
| --- | ---: |
| Confirmed recall backlog/newly overdue | 90 |
| Cooled-down non-responders | 5, starting after cooldown candidates exist |
| No-history prospecting | 5 |
| Total | 100 |

If the confirmed pool has fewer than 90 eligible patients, the algorithm does
not force repeated enrollment. It scales to actual new inflow and preserves
the separate re-contact/no-history limits.

### 24-month pacing simulation

The simulation uses 2,690 initial confirmed-backlog patients, 27 newly overdue
patients per week, 90 confirmed-recall enrollments per week, 10% booking
conversion, and re-contact beginning in week 16 after the initial sequence and
cooldown.

```text
net confirmed-backlog reduction = 90 enrolled - 27 newly overdue = 63/week
estimated clearance time       = 2,690 / 63 ≈ 43 weeks (about 10 months)
```

The confirmed backlog reaches zero in approximately week 43. Afterwards, confirmed enrollment
scales down to roughly the 27/week inflow; together with re-contact and
no-history streams, total ongoing activity becomes approximately 37
enrollments/week.

Over 104 weeks, this scenario projects:

| Outcome | Projection |
| --- | ---: |
| Confirmed-recall enrollments | 5,498 |
| Total enrollments across all pools | 6,463 |
| Expected bookings | 646 |
| Confirmed backlog remaining | 0 |

This is a planning model, not a capacity guarantee. The weekly ceiling remains
configurable and should be reduced when actual appointment capacity, conversion,
delivery health, or opt-out rate indicates a lower safe volume.

### Age and seasonal campaigns

Age bands—Child, Adult, Senior, and Unknown age—are retained for analysis and
message appropriateness, not as core prioritization in the first algorithm.
Back-to-school outreach for children and holiday-period support for seniors are
future campaigns, but require confirmed guardian contacts, campaign calendars,
and capacity data absent from this export.

### Reproducibility

- `analysis/part_b/analyze_pacing_inputs.py` derives backlog, inflow, and throughput
  inputs from the two CSV files.
- `analysis/part_b/simulate_pacing.py` runs the configurable 12–24 month projection.
- `analysis/part_b/simulate_segmented_pacing.py` applies the 90% / 5% / 5% policy to
  the CSV-derived starting pools, ages candidates between segments, tracks
  cooldown re-contact supply, and writes week-by-week projection output.

## Part C — The sequence itself

### Question

> Design a multi-touch email sequence (we'd expect somewhere in the range of
> 2-4 touches per enrolled patient, spaced out over a couple of weeks — use
> your judgment and justify your spacing).
>
> - Write the actual email copy for each touch. This is a real deliverable —
>   we're evaluating the copy itself, not just a placeholder. Make it something
>   you'd actually be comfortable sending: warm, a clear single call to action,
>   not spammy, no fake urgency gimmicks.
> - The copy should be informed by the data you have available (e.g. you know
>   roughly how overdue someone is — does that change what you'd say to them?).
>   You don't have to hyper-personalize every field, but "generic form email
>   photocopy-pasted 4,000 times" is the wrong bar.
> - Decide what happens on the last touch if there's still no response.

### Scope and communication principles

This deliverable is an **email-only** recall sequence. The supplied data also
contains phone numbers, but SMS and phone outreach are intentionally out of
scope: production use would require separate consent, channel-preference, and
compliance handling. A phone number is not treated as permission to text or
call.

Every email uses the patient's first name when available, a verified booking
link, and a single clear call to action. The emails are deliberately short:
the first explains why the practice is reaching out, the second removes booking
friction, and the third respectfully closes the current attempt. Each email
includes the practice's standard unsubscribe link in its footer. The system
immediately suppresses remaining touches if the patient books, replies, opts
out, becomes ineligible, or receives a future non-cancelled appointment.

The copy uses the patient’s overdue segment, rather than clinical claims or
assumptions about the exact kind of their last visit. This matters because the
analysis treats any relevant completed appointment as a visit for recall
purposes; it cannot safely promise that the patient’s last appointment was a
cleaning.

### Sequence design and rationale

Each enrolled patient receives up to three emails:

| Touch | Timing | Purpose |
| --- | --- | --- |
| 1 | Day 0 | Explain the reason for contact and invite booking. |
| 2 | Day 7–10 | Make the next action as easy as possible. |
| 3 | Day 21 | Provide a respectful final reminder and close the sequence. |

Three touches balance recall visibility with patient experience. A one-week
gap gives the first message time to be seen; the final touch is delayed so it
does not feel like repeated pressure. A fourth touch is not used in the
initial sequence because it adds little distinct value; it would be tested
only if engagement data supports it.

The message becomes less conversion-oriented as the patient becomes more
lapsed:

| Segment | Time since effective last visit | Communication goal |
| --- | --- | --- |
| Hot | More than 6 but less than 9 months | Make a routine return easy to schedule. |
| Warm | 9 to less than 18 months | Rebuild intent with concise preventive-care context. |
| Cold | 18 to less than 36 months | Re-engage with verified practice updates and insurance-access information. |
| Very cold | 36+ months | Confirm continued relevance and permission to stay in touch; a booking is a secondary outcome. |

Only facts that the practice can verify at send time—such as accepted insurers,
new locations, available appointments, or a specific offer—may be inserted
into a template.

### Email templates

Replace bracketed fields only with verified, current values. All messages use
the standard footer: `Unsubscribe from recall emails`.

#### Hot — 6–9 months overdue

**Touch 1 — Day 0**
**Subject:** Time to schedule your next visit, {{first_name}}

Hi {{first_name}},

Our records show it has been about {{months_since_last_visit}} months since your
last visit.

It’s time to schedule your next routine dental visit. We have appointments
available over the next two weeks.

[Schedule your visit]({{booking_link}})

— {{practice_name}}

**Touch 2 — Day 7–10**
**Subject:** Find a time that works for you

Hi {{first_name}},

Would an appointment on {{suggested_slot}} work for you? If not, our online
schedule makes it easy to choose another time.

[Choose an appointment]({{booking_link}})

— {{practice_name}}

**Touch 3 — Day 21**
**Subject:** We’ll leave the next step with you

Hi {{first_name}},

Regular dental visits are an important part of ongoing oral health. We’ll pause
these reminders for now, but whenever you’re ready, we’d be glad to see you.

[Schedule your visit]({{booking_link}})

— {{practice_name}}

#### Warm — 9–18 months overdue

**Touch 1 — Day 0**
**Subject:** Let’s help you get back on track

Hi {{first_name}},

It has been a while since your last visit with {{practice_name}}. Routine
preventive care can help you stay on top of your dental health.

[Book your next visit]({{booking_link}})

— {{practice_name}}

**Touch 2 — Day 7–10**
**Subject:** A quick way to schedule

Hi {{first_name}},

Getting back in is simple—choose a time online, and we’ll take care of the
rest. We currently have {{availability_window}} available.

[View available times]({{booking_link}})

— {{practice_name}}

**Touch 3 — Day 21**
**Subject:** Here when you’re ready

Hi {{first_name}},

This is our last reminder in this series. If now is not the right time, that’s
okay; you can schedule with us whenever it is.

[Schedule a visit]({{booking_link}})

— {{practice_name}}

#### Cold — 18–36 months overdue

**Touch 1 — Day 0**
**Subject:** A lot can change—let’s reconnect

Hi {{first_name}},

It has been some time since we saw you. We now offer [verified practice update]
and work with [verified insurance information]. We’d be happy to welcome you
back.

[See appointment times]({{booking_link}})

— {{practice_name}}

**Touch 2 — Day 7–10**
**Subject:** Your next visit can start here

Hi {{first_name}},

If insurance, location, or scheduling has changed for you, our team can help.
We have [verified availability or offer] for returning patients.

[Book an appointment]({{booking_link}})

— {{practice_name}}

**Touch 3 — Day 21**
**Subject:** We’ll pause reminders for now

Hi {{first_name}},

We know circumstances change. We’ll pause these reminders now, but if you’d
like to return, we’re here to help you find a time that works.

[Reconnect with us]({{booking_link}})

— {{practice_name}}

#### Very cold — more than 36 months overdue

**Touch 1 — Day 0**
**Subject:** Are you still in the area, {{first_name}}?

Hi {{first_name}},

It has been quite a while since your last visit. If you are still local and
would like to return, we would be glad to help. If not, no action is needed.

[See appointment options]({{booking_link}})

— {{practice_name}}

**Touch 2 — Day 7–10**
**Subject:** Still here when you need us

Hi {{first_name}},

Whether your schedule, insurance, or location has changed, you are welcome to
reach out when dental care is needed.

[Contact {{practice_name}}]({{booking_link}})

— {{practice_name}}

**Touch 3 — Day 21**
**Subject:** Closing this reminder series

Hi {{first_name}},

We will not send more reminders from this series. If you would like to return
in the future, you can always schedule online.

[Schedule when ready]({{booking_link}})

— {{practice_name}}

### After the final touch

No response after the final touch marks the sequence as `completed_no_response`
and starts the three-month cooldown defined in Part B. The patient is not
contacted again during that window. After cooldown, only the small recontact
allocation is eligible, with patients who have had fewer sequence attempts
prioritized. This prevents the same people from receiving repeated campaigns
while allowing a later, lower-frequency re-engagement attempt.

## Next steps and time-boxed scope cuts

### What I would do next

- **Close the feedback loop.** Ingest booking events and inbound email replies
  instead of relying only on periodic CSV exports. Responses such as “I moved,”
  “I use another practice,” “contact me later,” or “my insurance changed” would
  become verified, structured outcomes that stop unsuitable follow-ups and make
  later conversations more relevant. Ambiguous replies would go to staff
  review rather than automatically changing patient records.
- **Measure business and patient-experience outcomes together.** Track booking
  conversion, unsubscribe rate, success-to-unsubscribe ratio, delivery
  failures, complaints, replies, and completed appointments. Compare results by
  overdue segment, touch, template variant, and send-time cohort.
- **Experiment deliberately.** Test the three-touch sequence against a
  four-touch version and retain the extra message only when incremental
  bookings justify its unsubscribe, complaint, and brand costs. Test copy,
  timing, subject lines, and formatting with adequate sample sizes and clear
  guardrails.
- **Use response data for broader decisions.** Aggregated, verified relocation
  responses could contribute evidence when evaluating new practice locations.
  This would remain one input alongside market demand, competition, and cost
  because respondents are a self-selected sample.
- **Expand campaigns carefully.** Add approved seasonal campaigns, such as
  back-to-school outreach sent to verified guardians and holiday-period
  campaigns for seniors. AI could assist with drafting variants, but only from
  approved facts and with human review.
- **Productionize the system.** Replace SQLite with managed Postgres, trigger
  the planner with EventBridge Scheduler, place due deliveries on SQS, and use
  controlled workers to call Resend. Store credentials in AWS Secrets Manager
  and add structured logs, dashboards, retries, a dead-letter queue, and
  CloudWatch paging for delivery failures, queue age, missed runs, and unusual
  unsubscribe or complaint rates. Long-term touch timing would remain in
  Postgres because SQS is a delivery queue, not the sequence scheduler.
- **Profile and tune capacity.** Monitor worker CPU, memory, duration,
  concurrency, database latency, queue depth, and provider rate limits.
  Distribute due times across daily windows and cap concurrency to avoid burst
  traffic.

### Scope intentionally cut for this take-home

- The deliverable is a stateful scheduled CLI rather than a hosted UI or
  always-on API; authentication and staff-facing administration are omitted.
- CSV polling stands in for production booking webhooks and source-system
  integrations, leaving a documented race window between exports.
- Outreach is email-only. SMS and phone outreach require separate consent,
  preference, and compliance handling.
- Templates and sequence timing are configured in code; there is no campaign
  editor, approval workflow, automatic reply classification, or experimentation
  platform.
- SQLite is appropriate for a local demonstration but not for horizontally
  scaled workers. Cloud infrastructure, deployment automation, paging, and
  operational dashboards are proposed rather than provisioned.
- Tests focus on the highest-risk logic—eligibility, segmentation, enrollment,
  booking and opt-out transitions, cooldowns, and idempotency—rather than
  exhaustive integration or load coverage.
