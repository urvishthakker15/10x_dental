"""Stateful planning, booking suppression, and sequence advancement."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .database import Database
from .delivery import DeliveryError, EmailSender
from .eligibility import (
    calendar_months_elapsed,
    derive_recall_states,
    is_contactable,
    read_appointments,
    read_patients,
)
from .models import Candidate, RecallState
from .templates import render_email


CONFIRMED_SEGMENT_SHARES = (("hot", 0.50), ("warm", 0.30), ("cold", 0.10), ("very_cold", 0.10))
TOUCH_OFFSETS = (timedelta(), timedelta(days=8), timedelta(days=21))
FOLLOWUP_DELAYS = {
    1: ((2, timedelta(days=8)), (3, timedelta(days=21))),
    2: ((3, timedelta(days=13)),),
}
COOLDOWN = timedelta(days=90)
SEND_HOURS = (8, 14, 19)
STALE_SEND_AFTER = timedelta(minutes=30)


class RecallEngine:
    def __init__(self, database: Database, time_zone: str = "America/Los_Angeles"):
        self.database = database
        self.zone = ZoneInfo(time_zone)

    def initialize(self) -> None:
        """Create missing SQLite structures without clearing prior runs."""
        self.database.initialize()

    def set_paused(self, paused: bool) -> None:
        """Persist the global pause flag without altering queued work."""
        self.initialize()
        with self.database.connection() as connection:
            self.database.set_setting(connection, "paused", "true" if paused else "false")

    def suppress_patient(self, patient_id: str, reason: str, now: datetime) -> bool:
        """Persist an opt-out or suppression and cancel that patient's pending touches."""
        self.initialize()
        with self.database.connection() as connection:
            patient = connection.execute("SELECT 1 FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
            if patient is None:
                return False
            connection.execute(
                """
                INSERT INTO patient_suppressions(patient_id, reason, created_at) VALUES (?, ?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET reason=excluded.reason, created_at=excluded.created_at
                """,
                (patient_id, reason, now.isoformat(timespec="seconds")),
            )
            enrollment_rows = connection.execute(
                "SELECT id FROM enrollments WHERE patient_id=? AND status='active'", (patient_id,)
            ).fetchall()
            for row in enrollment_rows:
                connection.execute(
                    "UPDATE enrollments SET status='cancelled', cancellation_reason=? WHERE id=?", (reason, row["id"])
                )
                connection.execute("UPDATE messages SET state='cancelled' WHERE enrollment_id=? AND state='pending'", (row["id"],))
        return True

    def unsuppress_patient(self, patient_id: str) -> bool:
        """Remove only the suppression record; historical enrollments remain intact."""
        self.initialize()
        with self.database.connection() as connection:
            return connection.execute("DELETE FROM patient_suppressions WHERE patient_id=?", (patient_id,)).rowcount == 1

    def is_paused(self) -> bool:
        """Read the global pause flag from SQLite rather than process memory."""
        self.initialize()
        with self.database.connection() as connection:
            return self.database.get_setting(connection, "paused", "false") == "true"

    def load_states(self, patients_path, appointments_path, now: datetime) -> dict[str, RecallState]:
        """Rebuild current recall facts from both CSVs and refresh patient snapshots."""
        patients = read_patients(patients_path)
        appointments = read_appointments(appointments_path)
        states = derive_recall_states(patients, appointments, now)
        with self.database.connection() as connection:
            for patient in patients.values():
                connection.execute(
                    """
                    INSERT INTO patients(patient_id, first_name, last_name, email, phone, provider, status, is_active, source_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(patient_id) DO UPDATE SET
                      first_name=excluded.first_name, last_name=excluded.last_name, email=excluded.email,
                      phone=excluded.phone, provider=excluded.provider, status=excluded.status,
                      is_active=excluded.is_active, source_seen_at=excluded.source_seen_at
                    """,
                    (
                        patient.patient_id, patient.first_name, patient.last_name, patient.email, patient.phone,
                        patient.provider, patient.status, int(patient.is_active), now.isoformat(timespec="seconds"),
                    ),
                )
        return states

    def suppress_booked_patients(self, states: dict[str, RecallState], now: datetime) -> int:
        """Convert active sequences to booked and cancel unsent touches from fresh data."""
        booking_patient_ids = [patient_id for patient_id, state in states.items() if state.future_booking_at is not None]
        if not booking_patient_ids:
            return 0
        cancelled = 0
        with self.database.connection() as connection:
            for patient_id in booking_patient_ids:
                row = connection.execute(
                    """SELECT id FROM enrollments WHERE patient_id = ? AND status = 'active'""", (patient_id,)
                ).fetchone()
                if row is None:
                    continue
                connection.execute(
                    """
                    UPDATE enrollments
                    SET status='booked', booked_at=?, cancellation_reason='future_booking_detected'
                    WHERE id=? AND status='active'
                    """,
                    (now.isoformat(timespec="seconds"), row["id"]),
                )
                changed = connection.execute(
                    "UPDATE messages SET state='cancelled' WHERE enrollment_id=? AND state='pending'",
                    (row["id"],),
                ).rowcount
                cancelled += changed
        return cancelled

    def plan_week(
        self,
        states: dict[str, RecallState],
        now: datetime,
        weekly_capacity: int,
        practice_name: str,
        booking_link: str,
        unsubscribe_link: str,
    ) -> dict[str, int]:
        """Create at most one paced enrollment plan for the current calendar week."""
        if self.is_paused():
            return {"planned": 0, "reason": "paused"}
        week_start = (now.date() - timedelta(days=now.weekday())).isoformat()
        with self.database.connection() as connection:
            existing = connection.execute("SELECT 1 FROM pacing_windows WHERE window_start=?", (week_start,)).fetchone()
            if existing is not None:
                return {"planned": 0, "reason": "already_planned"}

            candidates = self._candidate_pools(connection, states, now)
            selected = self._select_candidates(candidates, weekly_capacity)
            connection.execute(
                "INSERT INTO pacing_windows(window_start, weekly_capacity, created_at) VALUES (?, ?, ?)",
                (week_start, weekly_capacity, now.isoformat(timespec="seconds")),
            )
            first_touch_slots = self._delivery_slots(now, len(selected))
            for candidate, first_due_at in zip(selected, first_touch_slots):
                self._create_enrollment(
                    connection, candidate, now, first_due_at, practice_name, booking_link, unsubscribe_link
                )
        counts: dict[str, int] = defaultdict(int)
        for candidate in selected:
            counts[candidate.pool] += 1
        counts["planned"] = len(selected)
        return dict(counts)

    def _candidate_pools(
        self, connection: sqlite3.Connection, states: dict[str, RecallState], now: datetime
    ) -> dict[str, list[Candidate]]:
        active_ids = {
            row["patient_id"]
            for row in connection.execute("SELECT patient_id FROM enrollments WHERE status='active'")
        }
        booked_rows = connection.execute(
            "SELECT patient_id, MAX(booked_at) AS booked_at FROM enrollments WHERE status='booked' GROUP BY patient_id"
        ).fetchall()
        booked_at_by_patient = {row["patient_id"]: row["booked_at"] for row in booked_rows}
        suppressed_ids = {
            row["patient_id"] for row in connection.execute("SELECT patient_id FROM patient_suppressions")
        }
        prior_rows = connection.execute(
            """
            SELECT e.patient_id, e.sequence_attempt_count AS attempt_count,
                   e.cooldown_until, e.status
            FROM enrollments e
            JOIN (
                SELECT patient_id, MAX(id) AS enrollment_id
                FROM enrollments GROUP BY patient_id
            ) latest ON latest.enrollment_id = e.id
            """
        ).fetchall()
        prior = {row["patient_id"]: row for row in prior_rows}
        pools: dict[str, list[Candidate]] = {"confirmed": [], "recontact": [], "no_history": []}
        for patient_id, state in states.items():
            patient = state.patient
            booked_at = booked_at_by_patient.get(patient_id)
            booking_is_still_current = (
                booked_at is not None
                and (state.latest_completed_at is None or state.latest_completed_at <= datetime.fromisoformat(booked_at))
            )
            if (
                not is_contactable(patient)
                or patient_id in active_ids
                or booking_is_still_current
                or patient_id in suppressed_ids
            ):
                continue
            existing = prior.get(patient_id)
            if existing is not None and existing["cooldown_until"]:
                cooldown_until = datetime.fromisoformat(existing["cooldown_until"])
                if cooldown_until.tzinfo is None:
                    cooldown_until = cooldown_until.replace(tzinfo=now.tzinfo)
                if cooldown_until > now:
                    continue
            if state.segment is not None:
                candidate = Candidate(
                    patient_id=patient_id, first_name=patient.first_name, email=patient.email,
                    segment=state.segment, pool="confirmed", due_date=state.due_date,
                    months_since_last_visit=calendar_months_elapsed(
                        state.latest_completed_at.date(), now.date()
                    ),
                    attempt_count=int(existing["attempt_count"]) if existing else 0,
                )
                if existing is not None and existing["cooldown_until"]:
                    pools["recontact"].append(
                        Candidate(**{**candidate.__dict__, "pool": "recontact"})
                    )
                elif existing is None or existing["status"] in {"booked", "cancelled"}:
                    pools["confirmed"].append(candidate)
            elif state.latest_completed_at is None and state.future_booking_at is None:
                candidate = Candidate(
                    patient_id=patient_id, first_name=patient.first_name, email=patient.email,
                    segment="no_history", pool="no_history", due_date=None,
                    attempt_count=int(existing["attempt_count"]) if existing else 0,
                )
                if existing is not None and existing["cooldown_until"]:
                    pools["recontact"].append(Candidate(**{**candidate.__dict__, "pool": "recontact"}))
                elif existing is None:
                    pools["no_history"].append(candidate)
        return pools

    def _select_candidates(self, pools: dict[str, list[Candidate]], capacity: int) -> list[Candidate]:
        """Apply 90/5/5 pool quotas, then the confirmed-patient segment mix."""
        confirmed_capacity = int(capacity * 0.90)
        recontact_capacity = int(capacity * 0.05)
        no_history_capacity = capacity - confirmed_capacity - recontact_capacity

        selected: list[Candidate] = []
        selected_confirmed_ids: set[str] = set()
        for segment, share in CONFIRMED_SEGMENT_SHARES:
            segment_candidates = sorted(
                (candidate for candidate in pools["confirmed"] if candidate.segment == segment),
                key=lambda candidate: (candidate.due_date or date.max, candidate.patient_id),
            )
            target = int(confirmed_capacity * share)
            chosen = segment_candidates[:target]
            selected.extend(chosen)
            selected_confirmed_ids.update(candidate.patient_id for candidate in chosen)

        remaining_confirmed = confirmed_capacity - len(selected_confirmed_ids)
        if remaining_confirmed:
            overflow = sorted(
                (candidate for candidate in pools["confirmed"] if candidate.patient_id not in selected_confirmed_ids),
                key=lambda candidate: (candidate.due_date or date.max, candidate.patient_id),
            )
            selected.extend(overflow[:remaining_confirmed])

        selected.extend(
            sorted(pools["recontact"], key=lambda candidate: (candidate.attempt_count, candidate.patient_id))[:recontact_capacity]
        )
        selected.extend(sorted(pools["no_history"], key=lambda candidate: candidate.patient_id)[:no_history_capacity])
        return selected

    def _delivery_slots(self, now: datetime, count: int) -> list[datetime]:
        """Distribute first touches evenly across 8am, 2pm, and 7pm for seven days."""
        slots: list[datetime] = []
        current_date = now.astimezone(self.zone).date()
        for day_offset in range(7):
            for hour in SEND_HOURS:
                slot = datetime.combine(current_date + timedelta(days=day_offset), time(hour=hour), self.zone)
                if slot >= now:
                    slots.append(slot)
        if not slots:
            raise RuntimeError("No future delivery slots available")
        base, extra = divmod(count, len(slots))
        distributed: list[datetime] = []
        for index, slot in enumerate(slots):
            distributed.extend([slot] * (base + (1 if index < extra else 0)))
        return distributed

    def _create_enrollment(
        self,
        connection: sqlite3.Connection,
        candidate: Candidate,
        now: datetime,
        first_due_at: datetime,
        practice_name: str,
        booking_link: str,
        unsubscribe_link: str,
    ) -> None:
        """Persist one enrollment and immutable Day 0, 8, and 21 email payloads."""
        attempt_row = connection.execute(
            "SELECT MAX(sequence_attempt_count) AS count FROM enrollments WHERE patient_id=?", (candidate.patient_id,)
        ).fetchone()
        attempt = int(attempt_row["count"] or 0) + 1
        cursor = connection.execute(
            """
            INSERT INTO enrollments(patient_id, pool, segment, status, enrolled_at, sequence_attempt_count)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (candidate.patient_id, candidate.pool, candidate.segment, now.isoformat(timespec="seconds"), attempt),
        )
        enrollment_id = int(cursor.lastrowid)
        for touch_number, offset in enumerate(TOUCH_OFFSETS, start=1):
            content = render_email(
                candidate.segment,
                touch_number,
                candidate.first_name,
                practice_name,
                booking_link,
                unsubscribe_link,
                candidate.months_since_last_visit,
            )
            connection.execute(
                """
                INSERT INTO messages(enrollment_id, touch_number, due_at, subject, text_body, html_body, state, idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    enrollment_id, touch_number, (first_due_at + offset).isoformat(timespec="seconds"),
                    content.subject, content.text, content.html,
                    f"recall/{uuid4()}",
                ),
            )

    def send_due_messages(
        self,
        states: dict[str, RecallState],
        now: datetime,
        sender: EmailSender,
        dry_run: bool,
        recipient_override: str | None = None,
        delivery_limit: int | None = None,
    ) -> dict[str, int]:
        """Send due touches once, rechecking booking/contactability before each claim."""
        if self.is_paused():
            return {"sent": 0, "dry_run": 0, "reason": "paused"}
        self.suppress_booked_patients(states, now)
        self.recover_stale_sends(now)
        with self.database.connection() as connection:
            due_messages = connection.execute(
                """
                SELECT m.*, e.patient_id, e.status AS enrollment_status, p.email
                FROM messages m
                JOIN enrollments e ON e.id=m.enrollment_id
                JOIN patients p ON p.patient_id=e.patient_id
                WHERE m.state='pending' AND m.due_at <= ? AND e.status='active'
                  AND NOT EXISTS (
                    SELECT 1 FROM messages prior
                    WHERE prior.enrollment_id=m.enrollment_id
                      AND prior.touch_number < m.touch_number
                      AND prior.state IN ('pending', 'sending')
                  )
                ORDER BY m.due_at, m.id
                """,
                (now.isoformat(timespec="seconds"),),
            ).fetchall()

        results = {"sent": 0, "dry_run": 0, "cancelled": 0, "failed": 0}
        for message in due_messages[:delivery_limit]:
            current_state = states.get(message["patient_id"])
            if current_state is None or current_state.future_booking_at is not None or not is_contactable(current_state.patient):
                self._cancel_message_before_send(message["id"], now, "booking_or_ineligible_before_send")
                results["cancelled"] += 1
                continue
            if dry_run:
                recipient = recipient_override or message["email"]
                sender.send(recipient, self._content_from_message(message), message["idempotency_key"])
                self._record_attempt(message["id"], now, "dry_run", "would_send", recipient)
                results["dry_run"] += 1
                continue
            if not self._claim_message(message["id"], now):
                continue
            recipient = recipient_override or message["email"]
            try:
                provider_message_id = sender.send(recipient, self._content_from_message(message), message["idempotency_key"])
            except DeliveryError as error:
                self._release_message(message["id"], now, str(error))
                results["failed"] += 1
                continue
            self._mark_sent(message, now, provider_message_id, recipient)
            results["sent"] += 1
        return results

    def recover_stale_sends(self, now: datetime) -> int:
        """Return abandoned 30-minute send claims to pending with the same provider key."""
        cutoff = now - STALE_SEND_AFTER
        with self.database.connection() as connection:
            return connection.execute(
                """
                UPDATE messages
                SET state='pending', claimed_at=NULL, last_error='recovered_stale_send'
                WHERE state='sending' AND claimed_at <= ?
                """,
                (cutoff.isoformat(timespec="seconds"),),
            ).rowcount

    @staticmethod
    def _content_from_message(message):
        """Rehydrate the exact email payload saved when the patient was enrolled."""
        from .models import EmailContent
        return EmailContent(subject=message["subject"], text=message["text_body"], html=message["html_body"])

    def _cancel_message_before_send(self, message_id: int, now: datetime, reason: str) -> None:
        """Cancel a still-pending message when the patient is no longer eligible."""
        with self.database.connection() as connection:
            connection.execute("UPDATE messages SET state='cancelled', last_error=? WHERE id=? AND state='pending'", (reason, message_id))

    def _claim_message(self, message_id: int, now: datetime) -> bool:
        """Atomically move one pending message to sending to prevent concurrent sends."""
        with self.database.connection() as connection:
            changed = connection.execute(
                "UPDATE messages SET state='sending', claimed_at=? WHERE id=? AND state='pending'",
                (now.isoformat(timespec="seconds"), message_id),
            ).rowcount
            return changed == 1

    def _release_message(self, message_id: int, now: datetime, error: str) -> None:
        """Return a provider failure to pending and retain its error for inspection."""
        with self.database.connection() as connection:
            connection.execute("UPDATE messages SET state='pending', last_error=?, claimed_at=NULL WHERE id=?", (error, message_id))
            self._record_attempt_in_connection(connection, message_id, now, "send", "failed", error)

    def _record_attempt(self, message_id: int, now: datetime, mode: str, outcome: str, detail: str) -> None:
        """Append an audit record for a dry-run or real provider attempt."""
        with self.database.connection() as connection:
            self._record_attempt_in_connection(connection, message_id, now, mode, outcome, detail)

    @staticmethod
    def _record_attempt_in_connection(connection, message_id: int, now: datetime, mode: str, outcome: str, detail: str) -> None:
        """Append a delivery audit record within the caller's transaction."""
        connection.execute(
            "INSERT INTO delivery_attempts(message_id, attempted_at, mode, outcome, detail) VALUES (?, ?, ?, ?, ?)",
            (message_id, now.isoformat(timespec="seconds"), mode, outcome, detail),
        )

    def _mark_sent(self, message, now: datetime, provider_message_id: str, recipient: str) -> None:
        """Persist provider success and start cooldown after the third touch."""
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE messages
                SET state='sent', sent_at=?, provider_message_id=?, claimed_at=NULL, last_error=NULL
                WHERE id=?
                """,
                (now.isoformat(timespec="seconds"), provider_message_id, message["id"]),
            )
            self._record_attempt_in_connection(connection, message["id"], now, "send", "sent", recipient)
            for touch_number, delay in FOLLOWUP_DELAYS.get(message["touch_number"], ()):
                connection.execute(
                    """
                    UPDATE messages SET due_at=?
                    WHERE enrollment_id=? AND touch_number=? AND state='pending'
                    """,
                    (
                        (now + delay).isoformat(timespec="seconds"),
                        message["enrollment_id"],
                        touch_number,
                    ),
                )
            if message["touch_number"] == 3:
                cooldown_until = now + COOLDOWN
                connection.execute(
                    """
                    UPDATE enrollments SET status='completed_no_response', sequence_completed_at=?, cooldown_until=?
                    WHERE id=? AND status='active'
                    """,
                    (now.isoformat(timespec="seconds"), cooldown_until.isoformat(timespec="seconds"), message["enrollment_id"]),
                )

    def status(self) -> dict[str, int | str]:
        """Report pause state plus enrollment and message counts by status."""
        self.initialize()
        with self.database.connection() as connection:
            paused = self.database.get_setting(connection, "paused", "false")
            result: dict[str, int | str] = {"paused": paused}
            for table, field in (("enrollments", "status"), ("messages", "state")):
                rows = connection.execute(f"SELECT {field}, COUNT(*) AS count FROM {table} GROUP BY {field}").fetchall()
                for row in rows:
                    result[f"{table}_{row[field]}"] = int(row["count"])
            return result
