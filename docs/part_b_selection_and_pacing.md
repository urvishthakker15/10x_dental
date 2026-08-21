# Part B — Selection & Pacing Algorithm

## Question

> Design (and justify, in writing) an algorithm that decides, on an ongoing
> basis, which patients to enroll into the outreach sequence and when.

The hard constraint is to assume a 10% conversion rate on contacted patients
while avoiding both an exhausted lead pipeline and a one-time dump of thousands
of emails.

## Objective and conversion definition

The algorithm enrolls a controlled weekly cohort, continuously finds newly
overdue patients, and uses persisted state to avoid duplicate outreach. A
**conversion** is a contacted patient who books; attendance is tracked
separately.

## Candidate pools

### Confirmed recall backlog and newly overdue patients

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

### No-history prospecting

Patients with no recorded completed visit and no future booking are not called
overdue because the export cannot establish a last-visit date. They remain a
small, separate prospecting pool for a first-visit/reactivation message.

## Weekly allocation policy

Let `weekly_capacity` be the configurable number of new sequence enrollments
allowed that week.

| Share | Pool | Rule |
| ---: | --- | --- |
| 90% | Confirmed backlog + newly overdue | Allocate 50% Hot, 30% Warm, and 20% Cold/Very cold; reassign unused quota to the next eligible confirmed segment. |
| 5% | Cooled-down non-responders | A prior sequence finished without booking/reply and the patient has passed cooldown. Prioritize the lowest `sequence_attempt_count` first. |
| 5% | No-history prospecting | Low-frequency, separately worded first-visit/reactivation outreach. |

This keeps new overdue patients from being crowded out while reserving small,
controlled allocations for recontacts and the ambiguous no-history group.

## State, tracking, and suppression

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

## Ongoing run logic

Each scheduled run:

1. Ingests the latest CSV data and derives current recall state.
2. Suppresses any active sequence with a new booking, opt-out, or suppression.
3. Finds patients newly crossing the six-month threshold.
4. Calculates available capacity and fills the 90% / 5% / 5% pools.
5. Persists enrollment and touch decisions before sending, making reruns
   idempotent.
6. Sends only the touch due on that day and records the result.

## Data-backed inputs

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

## Initial pacing recommendation

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

## 24-month pacing simulation

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

## Age and seasonal campaigns

Age bands—Child, Adult, Senior, and Unknown—support message design, not core
prioritization. Seasonal campaigns would require verified guardian contacts,
campaign calendars, and capacity data absent from this export.

## Reproducibility

- `analysis/part_b/analyze_pacing_inputs.py` derives backlog, inflow, and
  throughput inputs from the two CSV files.
- `analysis/part_b/simulate_pacing.py` runs the configurable 12–24 month projection.
- `analysis/part_b/simulate_segmented_pacing.py` applies the 90% / 5% / 5% policy to
  the CSV-derived starting pools, ages candidates between segments, tracks
  cooldown re-contact supply, and writes week-by-week projection output.
