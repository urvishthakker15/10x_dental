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

This is an **email-only** sequence. A phone number is not treated as permission
to call or text; those channels need separate consent and preference handling.

Each email uses the patient’s first name, one booking link, one call to action,
and a visible unsubscribe link. Touch 1 explains the outreach, Touch 2 removes
booking friction, and Touch 3 closes the attempt respectfully. A booking,
opt-out, suppression, or future non-cancelled appointment cancels the remaining
touches.

Copy changes by overdue segment but avoids claims about the patient’s last
procedure. The export supports “last visit,” not “last cleaning.”

## Sequence design and rationale

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

## Email templates

Fill template fields only with verified, current values. Every message ends
with `Unsubscribe from recall emails`.

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

### Warm — 9–18 months overdue

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

### Cold — 18–36 months overdue

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

### Very cold — more than 36 months overdue

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

## After the final touch

No response marks the sequence `completed_no_response` and starts a three-month
cooldown. Afterward, the patient may enter only the 5% recontact pool; fewer
prior attempts receive priority. This allows low-frequency re-engagement
without repeatedly targeting the same people.

## What I would test next

- Compare three touches with four, keeping the extra touch only if incremental
  bookings justify the added unsubscribes and complaints.
- Measure booking conversion, completed visits, unsubscribes, complaints, and
  replies by segment, touch, template, and send time. Opens and clicks are
  supporting signals where reliable.
- Ingest replies such as “I moved,” “I use another practice,” or “contact me
  later” as verified, structured outcomes. Ambiguous replies should go to staff
  review.
- Use aggregated relocation responses as one signal when evaluating new
  locations, alongside demand, competition, and cost. Respondents are
  self-selected, so the signal is not representative on its own.
- Test seasonal campaigns only with appropriate contact data—for example,
  back-to-school outreach sent to a verified guardian.
- Use AI to draft variants from approved facts, followed by human review. It
  must not invent clinical claims, insurance coverage, availability, or offers.
