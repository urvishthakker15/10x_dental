# Part A — Data Analysis

## Purpose and reproducibility

All figures are reproducible from `analysis/part_a/` and
`analysis/overall_data_analysis/`; the source CSVs are excluded from Git.

## Assumptions and definitions

| Decision | Rule | Why it is reasonable |
| --- | --- | --- |
| Analysis date | Use the date the script runs, with an optional `as_of_date` override that is printed in the output. | Operational runs need the current date; the override reproduces historical results. |
| Future appointment | Any future appointment that is not cancelled means the patient is already booked. | This is the brief’s stated rule; a booked patient should not be labeled overdue for outreach. |
| Last completed visit | If no qualifying future booking exists, use the latest completed past appointment. | Cancelled and broken appointments are not evidence that care occurred. |
| Overdue threshold | More than six calendar months, rather than 180 days. | “Six months” is the business definition and calendar arithmetic handles variable month lengths correctly. |
| No usable history | Do not label patients with neither a completed past visit nor a future booking as overdue. Report them separately. | Their history may be incomplete or they may be new/no-show patients; “overdue for cleaning” would be an unsupported claim. |
| Visit type | Count every completed appointment category when measuring recall cadence. | A visit of any category is treated as continued engagement with the practice; the export does not contain reliable clinical detail to infer whether cleaning also occurred. |
| Patient lifecycle | Treat `is_active = true` as authoritative; do not infer deactivation, mortality, or relocation from appointment gaps. | The assignment supplies an active roster, and lifecycle rules belong in the source practice-management system. |

## Data-quality observations

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

## Data-quality handling decisions

| Observation | Decision | Rationale |
| --- | --- | --- |
| `time_zone` is blank in every row, while wall-clock times strongly match Pacific Time behavior. | Store/order by UTC `start_time`; apply `America/Los_Angeles` for calendar-based recall dates. | This preserves the source-of-truth timestamp while aligning “today” and six-month due dates with practice-local time. |
| Birth date is missing for 146 patients and patient ID is not predictive of age. | Retain missing values as `Unknown age`; do not impute or exclude these patients from outreach. | Birth date is not required for recall eligibility, and imputation would manufacture unsupported demographic data for a material cohort. |
| One patient has a missing provider. | Exclude from outreach enrollment and record the exclusion. | We must not infer a provider: outreach appearing to come from the wrong clinician creates patient-trust and provider-relationship risk. |
| One patient has a missing status. | Exclude from outreach enrollment and record the exclusion. | Status is an operational eligibility field; withholding is safer than inventing a value. |
| Three patients have missing gender. | Map to `Other` for aggregate analysis only; do not use gender in eligibility or email copy. | This avoids forcing an unsupported binary value and has no effect on outreach logic. |
| `visit_type` is synthetic, while `visit_category` is a supplied stable grouping. | Use the five `visit_category` values as the reduced taxonomy; do not create a second manual mapping from labels. | The data validates this choice: every one of the 21 labels maps one-to-one to a category. It avoids treating a synthetic label as clinical truth. |
| A future `General Visit` is categorized as `other`, not `hygiene`. | Treat it as a future booking that suppresses outreach, but do not relabel it as a cleaning. | The brief explicitly says any future non-cancelled appointment means the patient is already returning. Calling `other` a cleaning would add an unsupported clinical assumption. |

### Monitoring boundary

The engine reports exclusion counts but does not implement alerting. Production
would alert when missing-provider or missing-status rates materially exceed
their established baseline.

## Derived last-visit status (required first step)

The patient-level recall table joins both CSVs. Its
`effective_last_visit_date` is the nearest future non-cancelled booking when
one exists; otherwise it is the latest completed past visit. This prevents a
patient who is already booked from being labeled overdue.

### Handling the no-completed-history cohort

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

## 1. At what rate do patients become overdue?

> Once a patient is on a healthy recall cadence, how often do they slip past
> 6 months before their next visit?

### Analysis and interpretation

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

### Methodology

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

### Notes

- All appointment categories count equally for this analysis. We assume any
  completed visit reflects continued engagement with the practice.
- An unresolved final interval is excluded until its six-month due date. If
  that date has passed with no future booking or completed visit, it is counted
  as an open lapse.
- The calculation is implemented in
  `analysis/part_a/calculate_overdue_rate.py` and uses the current date by default.

### Result

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

## 2. What percent of the active patient base is currently overdue *and* has nothing booked to bring them back?

### Analysis and interpretation

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

### Methodology

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

### Notes

- Patients with no completed visit and no future booking are not included in
  the overdue numerator because the export does not establish a last-visit
  date for them.
- The calculation is implemented in
  `analysis/part_a/calculate_current_overdue_share.py` and uses the current date by
  default.

### Result

**44.86%** of the active patient base is currently overdue and unbooked as of
2026-08-20.

| Calculation component | Count |
| --- | ---: |
| Active patients (denominator) | 5,997 |
| Currently overdue and unbooked (numerator) | 2,690 |
| Patients with a future non-cancelled booking | 1,144 |
| Patients with no completed visit or future booking | 1,715 |

The calculation is `2,690 / 5,997 = 44.86%`.

## 3. What's your estimate of this practice's retention rate? State how you're defining "retention" — there's no single industry-standard definition, so pick a reasonable one, justify it, and compute it.

### Analysis and interpretation

For an established dental practice, retention is most useful as a yearly
measure; month-over-month retention would be more appropriate for a new
practice with little history. For this exercise, we use a rolling 12-month
window from the same date last year through the current date.

A retained patient is an active patient who was served during that 12-month
window and whose first **observed** completed visit occurred before the
window. Patients first observed during the window are treated as new-to-the-
export for this calculation and are excluded from the retained numerator.

### Methodology

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

### Notes

- This is a rolling 12-month metric, so it avoids comparing a partial calendar
  year with a full year and should be recalculated as time moves forward.
- “First-time” means first observed in this export. A patient with completed
  care before the export began could be classified as first-time by this
  method, so the metric should be read as an estimate.
- All completed appointment categories count as service for this metric.
- The calculation is implemented in
  `analysis/part_a/calculate_retention_rate.py`.

### Result

**73.28%** rolling 12-month retention for 2025-08-20 through 2026-08-20.

| Calculation component | Count |
| --- | ---: |
| Unique active patients served in the rolling 12-month window | 1,871 |
| Patients first observed as served in the window | 500 |
| Retained patients | 1,371 |

The calculation is `(1,871 - 500) / 1,871 = 73.28%`.

## 4. Assuming a 10% conversion rate on your outreach sequence, what would you recommend to meaningfully improve the practice's numbers?

> This is a business-reasoning question as much as a data one — we want to
> see how you think about levers (volume, cadence, segmentation, copy,
> timing), not just a single "run the sequence" answer.

### Analysis and interpretation

The 10% conversion assumption is a planning baseline, not a reason to send the
same message to all 2,690 overdue patients. Here, conversion means booking an
appointment after outreach; completing that appointment is a separate
downstream outcome.

I recommend enrolling 100 patients per week, expecting about 10 bookings, and
using a different lever for each overdue segment. Make scheduling nearly
frictionless for recently overdue patients, rebuild relevance for patients who
are becoming cold, test verified improvements or modest incentives when trying
to recapture older patients, and use the coldest outreach to confirm whether
the relationship is still relevant. This paced, segmented program is more
useful than applying 10% to the whole backlog as if every patient had equal
intent or should be contacted at once.

### Recommendations

| Overdue duration | Goal | Recommended outreach |
| --- | --- | --- |
| 6–9 months | Remove friction for patients who may already intend to return. | Send a warm reminder with a small set of specific appointment slots or a direct self-scheduling link. If future data includes the patient’s usual clinician and provider capacity, prioritize slots with that clinician. |
| 9–18 months | Re-engage patients who are becoming cold. | Mention verified practice improvements from the last year, ask whether insurance or scheduling needs have changed, and send up to three touches unless the patient books, replies, or opts out. |
| 18–36 months | Recapture patients who may now be using another practice. | Time outreach for lower-demand periods and test a modest return incentive, such as a $25 gift card. Mention relevant new locations or services only when those claims are current and verified. |
| More than 36 months | Confirm continued relevance before repeated outreach. | Send a respectful reactivation message that asks whether the patient is still local and interested in care. Suppress or move the patient to a low-frequency review path when there is no response, rather than repeatedly sending recall messages. |

### Timing, capacity, and measurement

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

### Notes

- The supplied dataset does not include a patient’s usual clinician, current
  provider capacity, appointment-slot inventory, insurance information, low
  season, practice upgrades, locations, or incentives. Those inputs would be
  required to operationalize the segment-specific recommendations above.
- The final sequence copy, touch spacing, and re-contact policy are developed
  in Part C; sustainable enrollment volume is developed in Part B.
