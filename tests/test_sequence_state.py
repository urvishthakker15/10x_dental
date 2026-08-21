"""Sequence transitions and idempotency tests."""

from datetime import timedelta

from tests.support import EngineTestCase, FakeSender, appointment_row, patient_row


class SequenceStateTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.patients = [patient_row("P-1")]
        self.old_appointment = appointment_row(
            "A-1", "P-1", "2025-12-01T18:00:00+00:00", completed="true"
        )
        self.write_data(self.patients, [self.old_appointment])
        self.states = self.load_states()
        self.plan(self.states)

    def test_sent_touch_is_not_sent_again(self) -> None:
        """A second run at the same time must not resend a successful touch."""
        sender = FakeSender()

        first = self.engine.send_due_messages(self.states, self.now, sender, dry_run=False)
        second = self.engine.send_due_messages(self.states, self.now, sender, dry_run=False)

        self.assertEqual(first["sent"], 1)
        self.assertEqual(second["sent"], 0)
        self.assertEqual(len(sender.calls), 1)
        with self.database.connection() as connection:
            states = [row[0] for row in connection.execute("SELECT state FROM messages ORDER BY touch_number")]
        self.assertEqual(states, ["sent", "pending", "pending"])

    def test_future_booking_marks_success_and_cancels_remaining_touches(self) -> None:
        """A booking after touch one must stop every unsent message."""
        sender = FakeSender()
        self.engine.send_due_messages(self.states, self.now, sender, dry_run=False)
        future = appointment_row("A-2", "P-1", "2026-09-01T18:00:00+00:00")
        self.write_data(self.patients, [self.old_appointment, future])
        refreshed_states = self.load_states()

        cancelled = self.engine.suppress_booked_patients(refreshed_states, self.now)

        with self.database.connection() as connection:
            enrollment_status = connection.execute("SELECT status FROM enrollments").fetchone()[0]
            message_states = [row[0] for row in connection.execute("SELECT state FROM messages ORDER BY touch_number")]
        self.assertEqual(cancelled, 2)
        self.assertEqual(enrollment_status, "booked")
        self.assertEqual(message_states, ["sent", "cancelled", "cancelled"])

    def test_opt_out_is_persisted_and_blocks_reenrollment(self) -> None:
        """An opt-out must cancel the sequence and remain excluded next week."""
        applied = self.engine.suppress_patient("P-1", "opted_out", self.now)
        next_week = self.now + timedelta(days=7)
        result = self.plan(self.states, next_week)

        with self.database.connection() as connection:
            enrollment_status = connection.execute("SELECT status FROM enrollments").fetchone()[0]
            suppression = connection.execute(
                "SELECT reason FROM patient_suppressions WHERE patient_id='P-1'"
            ).fetchone()[0]
            message_states = {row[0] for row in connection.execute("SELECT state FROM messages")}
            enrollment_count = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        self.assertTrue(applied)
        self.assertEqual(result["planned"], 0)
        self.assertEqual(enrollment_status, "cancelled")
        self.assertEqual(suppression, "opted_out")
        self.assertEqual(message_states, {"cancelled"})
        self.assertEqual(enrollment_count, 1)

    def test_final_touch_completes_sequence_and_starts_cooldown(self) -> None:
        """Sending all three due touches must close the sequence for 90 days."""
        sender = FakeSender()
        after_final_touch = self.now + timedelta(days=22)

        result = self.engine.send_due_messages(
            self.states, after_final_touch, sender, dry_run=False
        )
        repeated = self.engine.send_due_messages(
            self.states, after_final_touch, sender, dry_run=False
        )

        with self.database.connection() as connection:
            enrollment = connection.execute(
                "SELECT status, cooldown_until FROM enrollments"
            ).fetchone()
            sent_count = connection.execute("SELECT COUNT(*) FROM messages WHERE state='sent'").fetchone()[0]
        self.assertEqual(result["sent"], 3)
        self.assertEqual(repeated["sent"], 0)
        self.assertEqual(len(sender.calls), 3)
        self.assertEqual(enrollment["status"], "completed_no_response")
        self.assertEqual(
            enrollment["cooldown_until"],
            (after_final_touch + timedelta(days=90)).isoformat(timespec="seconds"),
        )
        self.assertEqual(sent_count, 3)
