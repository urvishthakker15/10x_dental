# Part C — The sequence itself

## Question

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

## Scope and communication principles

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

## Sequence design and rationale

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

## Email templates

Replace bracketed fields only with verified, current values. All messages use
the standard footer: `Unsubscribe from recall emails`.

### Hot — 6–9 months overdue

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

### Warm — 9–18 months overdue

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

### Cold — 18–36 months overdue

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

### Very cold — more than 36 months overdue

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

## After the final touch

No response after the final touch marks the sequence as `completed_no_response`
and starts the three-month cooldown defined in Part B. The patient is not
contacted again during that window. After cooldown, only the small recontact
allocation is eligible, with patients who have had fewer sequence attempts
prioritized. This prevents the same people from receiving repeated campaigns
while allowing a later, lower-frequency re-engagement attempt.

## Future work

With more time and appropriate approval controls, AI could assist in drafting
segment-specific variants of approved templates. It would not be allowed to
invent clinical claims, insurance participation, appointment availability, or
offers; outputs would be constrained to approved facts, reviewed against brand
and compliance rules, and tested before broader use.

The production program would add a measurement and experimentation loop. The
primary measures would be booking conversion (`bookings / contacted patients`),
unsubscribe rate (`unsubscribes / contacted patients`), and the
success-to-unsubscribe ratio (`bookings / unsubscribes`). Delivery failures,
complaints, replies, and opens or clicks where reliable would be supporting
measures. Results would be compared by overdue segment, sequence touch,
template variant, and send-time cohort.

This makes both outcomes visible: a template that produces more bookings but a
disproportionate rise in unsubscribes is not automatically better. With enough
sample size, controlled tests would refine subject lines, format, copy, timing,
and cadence while unsubscribe and complaint rates act as guardrails. A booking
is the sequence conversion used here; completed appointments would be tracked
separately as a downstream business outcome.

Future versions would also ingest replies and other inbound responses instead
of treating outreach as one-way communication. Responses such as "I moved,"
"I use another practice," "contact me later," or "my insurance changed" would
be classified into structured outcomes. After appropriate verification, those
facts could update the existing patient record, stop unsuitable follow-ups,
and make the next conversation more relevant. Ambiguous responses would be
routed for staff review rather than automatically changing clinical or contact
records.

Aggregated response data could also inform broader practice decisions. For
example, a meaningful concentration of former patients reporting a move to the
same city could contribute evidence when evaluating a new location. This would
be one planning input alongside market size, patient demand, competition, and
operating cost; respondents are a self-selected sample and should not be
treated as representative of the full patient base.

The three-touch sequence would also be tested against a four-touch variant.
The additional touch would be retained only if its incremental bookings justify
the corresponding unsubscribe, complaint, and brand-experience costs.

The initial algorithm does not prioritize by age. Future campaign planning may
use age segments only where appropriate and supported by contact data: for
example, a back-to-school campaign for children or a holiday-period campaign
that encourages seniors to schedule before plans become busy. A child campaign
would first require confirmation that the email belongs to the appropriate
guardian. These are targeted campaigns with their own approved copy and
capacity plan, not a reason to change the core recall-priority order.
