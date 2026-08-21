# Recall Outreach Engine — Take-Home Submission

This document consolidates Parts A–D. Setup instructions and detailed Part D
evidence are also available in the repository README and
`docs/part_d_system_design.md`.

## Contents

1. Part A — Data analysis
2. Part B — Selection and pacing algorithm
3. Part C — Email sequence
4. Part D — Working system
5. Next steps and time-boxed scope cuts

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
- `patients.birth_date` is missing in 146 rows (2.43%). Missingness appears in
  every 1,000-patient-ID range (1.90%–3.20%), so it is not isolated to one
  import cohort. It is higher for male records (3.15%) than female records
  (1.66%) and for Provider A (2.51%) than Provider B (0.30%). Birth date does
  not determine recall eligibility.
- `patients.deactivation_reason` is blank for every row, consistent with the
  file being active-only.
- Patient ID is not a useful proxy for age: mean age varies only from 48.1 to
  50.2 across the six 1,000-ID cohorts, and the Pearson correlation between
  numeric patient ID and age is 0.006.
- One patient is missing a provider, one is missing status, and three are
  missing gender.
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

The engine reports exclusion counts but does not alert on them. In production,
I would alert when missing-provider or missing-status rates rise materially
above their baseline.

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

A patient enters healthy cadence after two consecutive completed appointments
within six calendar months. Every later interval is then an opportunity to
remain on schedule or lapse. A lapse on the first opportunity is 1 / 1 (100%);
no lapses is 0%. The practice rate pools all lapses across all observed
post-cadence opportunities.

A lapse ends that cadence episode. Two new on-time completed visits start a new
episode, so a patient who regains cadence and lapses again contributes both
episodes.

#### Methodology

1. Group appointments by patient and order them by date.
2. Keep completed past appointments; use a future non-cancelled booking as the
   known final appointment. Exclude all other past appointments.
3. Enter healthy cadence after two consecutive completed visits within six
   calendar months; end the episode after a lapse and allow later re-entry.
4. Calculate:

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

Nearly half of the active patient base (44.86%) is confirmed overdue and
unbooked, making recall outreach a material opportunity. Another 1,715 active
patients have no completed visit or future booking; because the export cannot
establish their last visit, they remain a separate lower-confidence pool.

The backlog justifies ongoing outreach, but its size also argues against a
one-time send. Part B combines it with newly-overdue inflow to set a sustainable
weekly pace.

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

The calculation is implemented in
`analysis/part_a/calculate_current_overdue_share.py` and uses the current date
by default.

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

For an established practice, I use a rolling 12-month measure rather than
month-over-month retention. A retained patient is active, completed a visit in
the window, and had a first **observed** completed visit before the window.
Patients first observed during the window count as new-to-the-export.

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

- A rolling window avoids comparing a partial calendar year with a full year.
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

The 10% conversion assumption is a planning baseline, not a reason to send the
same message to all 2,690 overdue patients. Here, conversion means booking an
appointment after outreach; completing that appointment is a separate
downstream outcome.

I recommend enrolling 100 patients per week, expecting about 10 bookings, and
using a different lever for each overdue segment. Make scheduling nearly
frictionless for recently overdue patients, rebuild relevance for patients who
are becoming cold, test verified improvements or modest incentives when trying
to recapture older patients, and use the coldest outreach to confirm whether
the relationship is still relevant. This approach does not assume every
patient has equal intent or should be contacted at once.

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

The export does not include usual clinician, open slots, insurance, low season,
practice upgrades, locations, or incentives. These recommendations use those
inputs only when verified at send time.

## Part B — Selection & Pacing Algorithm

### Question

> Design (and justify, in writing) an algorithm that decides, on an ongoing
> basis, which patients to enroll into the outreach sequence and when.

The hard constraint is to assume a 10% conversion rate on contacted patients
while avoiding both an exhausted lead pipeline and a one-time dump of thousands
of emails.

### Objective and conversion definition

The algorithm enrolls a controlled weekly cohort, continuously finds newly
overdue patients, and uses persisted state to avoid duplicate outreach. A
**conversion** is a contacted patient who books; attendance is tracked
separately.

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

This keeps new overdue patients from being crowded out while reserving small,
controlled allocations for recontacts and the ambiguous no-history group.

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
limits repeated contact while allowing controlled reactivation.

Patients who book are not contacted again while booked or on schedule. They
can enter a future recall cycle only after a later completed visit and a new
six-month overdue period with no future booking.

### Ongoing run logic

Each scheduled run:

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

Set an initial ceiling of **100 enrollments/week**. At 10% conversion, that is
about **10 bookings/week**, or 9.7% of the historical average completed volume
(10 / 103.3). I assume the practice can absorb those incremental bookings; the
ceiling remains configurable because the export has no open-slot data.

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

The confirmed backlog reaches zero around week 43. Confirmed enrollment then
falls to the 27/week inflow; including recontacts and no-history prospecting,
ongoing enrollment is about 37/week.

Over 104 weeks, this scenario projects:

| Outcome | Projection |
| --- | ---: |
| Confirmed-recall enrollments | 5,498 |
| Total enrollments across all pools | 6,463 |
| Expected bookings | 646 |
| Confirmed backlog remaining | 0 |

This is a planning model, not a capacity guarantee. Actual appointment
capacity, conversion, delivery health, and opt-outs should determine the final
ceiling.

### Age and seasonal campaigns

Age bands—Child, Adult, Senior, and Unknown—support message design, not core
prioritization. Seasonal campaigns would require verified guardian contacts,
campaign calendars, and capacity data absent from this export.

### Reproducibility

- `analysis/part_b/analyze_pacing_inputs.py` derives backlog, inflow, and
  throughput inputs from the two CSV files.
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

This is an **email-only** sequence. A phone number is not treated as permission
to call or text; those channels need separate consent and preference handling.

Each email uses the patient’s first name, one booking link, one call to action,
and a visible unsubscribe link. Touch 1 explains the outreach, Touch 2 removes
booking friction, and Touch 3 closes the attempt respectfully. A booking,
opt-out, suppression, or future non-cancelled appointment cancels the remaining
touches.

Copy changes by overdue segment but avoids claims about the patient’s last
procedure. The export supports “last visit,” not “last cleaning.”

### Sequence design and rationale

Each enrolled patient receives up to three emails:

| Touch | Timing | Purpose |
| --- | --- | --- |
| 1 | Day 0 | Explain the reason for contact and invite booking. |
| 2 | Day 8 | Make the next action as easy as possible. |
| 3 | Day 21 | Provide a respectful final reminder and close the sequence. |

Three touches provide multiple chances to respond without crowding the inbox.
The first follow-up waits about a week; the final note arrives on Day 21 and
then stops. A fourth touch belongs in an experiment, not the default sequence.

The message becomes less conversion-oriented as the patient becomes more
lapsed:

| Segment | Time since effective last visit | Communication goal |
| --- | --- | --- |
| Hot | More than 6 but less than 9 months | Make a routine return easy to schedule. |
| Warm | 9 to less than 18 months | Rebuild intent with concise preventive-care context. |
| Cold | 18 to less than 36 months | Re-engage around changes in insurance, location, or schedule. |
| Very cold | 36+ months | Confirm continued relevance; a booking is a secondary outcome. |

Any insurer, location, availability, or offer mentioned in production must be
verified at send time.

The current engine uses generic equivalents for fields absent from the export,
such as suggested slots, availability windows, practice updates, insurance
information, and offers.

### Email templates

Fill template fields only with verified, current values. Every message ends
with `Unsubscribe from recall emails`.

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

**Touch 2 — Day 8**

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

**Touch 2 — Day 8**

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

**Touch 2 — Day 8**

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

**Touch 2 — Day 8**

**Subject:** Still here when you need us

Hi {{first_name}},

Whether your schedule, insurance, or location has changed, you are welcome to
reach out when dental care is needed.

[Contact {{practice_name}}]({{booking_link}})

— {{practice_name}}

**Touch 3 — Day 21**

**Subject:** Closing the loop for now

Hi {{first_name}},

We will not send more reminders from this series. If you would like to return
in the future, you can always schedule online.

[Schedule when ready]({{booking_link}})

— {{practice_name}}

### After the final touch

No response marks the sequence `completed_no_response` and starts a three-month
cooldown. Afterward, the patient may enter only the 5% recontact pool; fewer
prior attempts receive priority. This allows low-frequency re-engagement
without repeatedly targeting the same people.

## Part D — Working system

The repository contains a scheduled Python CLI backed by SQLite. Each run
reloads both CSVs, cancels outreach after new bookings, creates the current
weekly plan once, and sends only due touches. SQLite persists enrollments,
messages, suppressions, cooldowns, attempts, and provider IDs across runs.

Atomic claims and stored Resend idempotency keys prevent duplicate sends.
Delivery is dry-run by default, and the system can pause or resume without
losing state.

Nine unit tests cover eligibility, segment boundaries, calendar-month
calculations, booking and opt-out transitions, cooldowns, and idempotency. A
controlled Resend delivery, including calculated months since the patient's
last visit, is shown in
[Part D system design](docs/part_d_system_design.md); setup and run commands are
in the [README](README.md).


## Next steps and time-boxed scope cuts

### What I would do next

- Ingest booking events and replies, convert clear responses into verified
  patient outcomes, and route ambiguous replies to staff.
- Measure bookings, completed visits, unsubscribes, complaints, replies, and
  delivery health by segment, touch, template, and send time, including the
  success-to-unsubscribe ratio (`bookings / unsubscribes`).
- Compare three- and four-touch sequences. Keep an extra touch only when its
  incremental bookings justify the added unsubscribes and complaints.
- Use verified relocation responses as one signal when evaluating new practice
  locations, alongside demand, competition, and cost.
- Move SQLite to Postgres, schedule planning with EventBridge, queue sends in
  SQS, store secrets securely, and add retries, dashboards, and alerts.
- Add basic authenticated staff tools and carefully approved back-to-school and
  senior holiday campaigns. AI may help draft variants from verified facts,
  with human review.
- Tune send volume and worker concurrency from appointment capacity, queue
  depth, resource use, and provider limits.

### Scope intentionally cut

- CSV polling replaces booking webhooks, leaving a documented race between an
  export and an email send.
- The product is an email-only scheduled CLI; UI, authentication, SMS/phone
  consent handling, and staff workflows are out of scope.
- Templates and timing live in code; there is no campaign editor, approval
  workflow, reply classifier, or experimentation platform.
- Booking links, availability, insurance information, practice updates, and
  unsubscribe handling require verified production integrations.
- SQLite and local scheduling demonstrate statefulness but do not provide
  horizontally scaled production infrastructure.
- Tests focus on eligibility, segmentation, state transitions, and idempotency,
  not exhaustive integration or load coverage.
