"""Plain-text and HTML sequence templates, selected by outreach segment."""

from __future__ import annotations

from html import escape

from .models import EmailContent


COPY = {
    "hot": (
        ("Time to schedule your next visit, {first_name}",
         "Hi {first_name},\n\nOur records show it has been about {months_since_last_visit} months since your last visit.\n\nIt’s a good time to schedule your next routine dental visit. You can view available times online.\n\nSchedule your visit: {booking_link}\n\n— {practice_name}"),
        ("A quick follow-up on your next visit",
         "Hi {first_name},\n\nJust checking in—our online schedule makes it easy to choose a time that works for you.\n\nChoose an appointment: {booking_link}\n\n— {practice_name}"),
        ("We’ll leave the next step with you",
         "Hi {first_name},\n\nWe’ll pause these reminders after today. Whenever you’re ready for your next visit, we’d be glad to see you.\n\nSchedule your visit: {booking_link}\n\n— {practice_name}"),
    ),
    "warm": (
        ("Let’s help you get back on track",
         "Hi {first_name},\n\nIt’s been a while since we last saw you. Life gets busy, and scheduling your next visit is a simple way to get back on track.\n\nBook your next visit: {booking_link}\n\n— {practice_name}"),
        ("A quick way to schedule",
         "Hi {first_name},\n\nChoose a time online that works for you, and we’ll take care of the rest.\n\nView available times: {booking_link}\n\n— {practice_name}"),
        ("Here when you’re ready",
         "Hi {first_name},\n\nThis is our last reminder for now. If the timing isn’t right, that’s okay—we’ll be here whenever you’re ready.\n\nSchedule a visit: {booking_link}\n\n— {practice_name}"),
    ),
    "cold": (
        ("A lot can change—let’s reconnect",
         "Hi {first_name},\n\nIt’s been some time since we saw you, and we wanted to check in. If your insurance, location, or schedule has changed, our team can help make returning simple.\n\nSee appointment times: {booking_link}\n\n— {practice_name}"),
        ("Your next visit can start here",
         "Hi {first_name},\n\nWe’d be happy to welcome you back. Choose a time online, and our team will take care of the rest.\n\nBook an appointment: {booking_link}\n\n— {practice_name}"),
        ("We’ll pause reminders for now",
         "Hi {first_name},\n\nWe know circumstances change, so we’ll pause these reminders after today. If you’d like to return, we’re here to help.\n\nReconnect with us: {booking_link}\n\n— {practice_name}"),
    ),
    "very_cold": (
        ("Are you still in the area, {first_name}?",
         "Hi {first_name},\n\nIt’s been quite a while since your last visit, and we wanted to check whether you’re still in the area. If you’d like to return, we’d be glad to help. If you’ve moved or found another practice, we completely understand.\n\nSee appointment options: {booking_link}\n\n— {practice_name}"),
        ("Still here when you need us",
         "Hi {first_name},\n\nIf your schedule, insurance, or location has changed, you’re still welcome to reconnect with our team whenever the time is right.\n\nContact {practice_name}: {booking_link}\n\n— {practice_name}"),
        ("Closing the loop for now",
         "Hi {first_name},\n\nWe don’t want to crowd your inbox, so this is our last message in this series. If you’d like to return in the future, we’d be happy to hear from you.\n\nSchedule when ready: {booking_link}\n\n— {practice_name}"),
    ),
    "no_history": (
        ("Schedule your first visit with {practice_name}",
         "Hi {first_name},\n\nWe would be glad to help you schedule a visit with {practice_name}. Choose a time online whenever you’re ready.\n\nSee appointment options: {booking_link}\n\n— {practice_name}"),
        ("A convenient time for your visit",
         "Hi {first_name},\n\nOur online schedule makes it easy to choose a time that works for you.\n\nChoose an appointment: {booking_link}\n\n— {practice_name}"),
        ("We’ll leave the next step with you",
         "Hi {first_name},\n\nWe’ll pause these reminders for now. If you would like to schedule in the future, we would be glad to see you.\n\nSchedule a visit: {booking_link}\n\n— {practice_name}"),
    ),
}


def render_email(
    segment: str,
    touch_number: int,
    first_name: str,
    practice_name: str,
    booking_link: str,
    unsubscribe_link: str,
    months_since_last_visit: int | None = None,
) -> EmailContent:
    """Render approved segment copy with patient, practice, CTA, and opt-out fields."""
    try:
        subject_template, text_template = COPY[segment][touch_number - 1]
    except (KeyError, IndexError) as error:
        raise ValueError(f"No template for segment={segment!r}, touch={touch_number}") from error

    values = {
        "first_name": first_name or "there",
        "practice_name": practice_name,
        "booking_link": booking_link,
        "unsubscribe_link": unsubscribe_link,
        "months_since_last_visit": months_since_last_visit or "several",
    }
    subject = subject_template.format(**values)
    rendered = text_template.format(**values)
    text = rendered + f"\n\nUnsubscribe from recall emails: {unsubscribe_link}"
    sections = rendered.split("\n\n")
    body_sections = sections[:-2]
    cta_label = sections[-2].split(":", 1)[0]
    signature = sections[-1]
    paragraphs = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in body_sections)
    html = (
        '<html><body style="font-family:Arial,sans-serif;color:#202124;line-height:1.5;">'
        f"{paragraphs}"
        f'<p><a href="{escape(booking_link, quote=True)}">{escape(cta_label)}</a></p>'
        f'<p style="margin-bottom:6px;">{escape(signature)}</p>'
        f'<p style="font-size:12px;color:#6b7280;margin-top:0;"><a href="{escape(unsubscribe_link, quote=True)}">'
        "Unsubscribe from recall emails</a></p>"
        "</body></html>"
    )
    return EmailContent(subject=subject, text=text, html=html)
