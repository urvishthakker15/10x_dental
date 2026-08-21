"""Enrollment eligibility tests."""

from tests.support import EngineTestCase, appointment_row, patient_row


class EnrollmentEligibilityTests(EngineTestCase):
    def test_only_eligible_recall_and_no_history_patients_are_enrolled(self) -> None:
        """Bookings, inactivity, and missing ownership fields must block enrollment."""
        patients = [
            patient_row("P-ELIGIBLE"),
            patient_row("P-FUTURE"),
            patient_row("P-NO-PROVIDER", provider=""),
            patient_row("P-NO-STATUS", status=""),
            patient_row("P-INACTIVE", is_active="false"),
            patient_row("P-NO-HISTORY"),
            patient_row("P-CANCELLED-FUTURE"),
        ]
        old_visit = "2025-12-01T18:00:00+00:00"
        future_visit = "2026-09-01T18:00:00+00:00"
        appointments = [
            appointment_row("A-1", "P-ELIGIBLE", old_visit, completed="true"),
            appointment_row("A-2", "P-FUTURE", old_visit, completed="true"),
            appointment_row("A-3", "P-FUTURE", future_visit),
            appointment_row("A-4", "P-NO-PROVIDER", old_visit, completed="true"),
            appointment_row("A-5", "P-NO-STATUS", old_visit, completed="true"),
            appointment_row("A-6", "P-INACTIVE", old_visit, completed="true"),
            appointment_row("A-7", "P-CANCELLED-FUTURE", old_visit, completed="true"),
            appointment_row("A-8", "P-CANCELLED-FUTURE", future_visit, cancelled="true"),
        ]
        self.write_data(patients, appointments)

        states = self.load_states()
        result = self.plan(states)

        with self.database.connection() as connection:
            enrolled = {
                (row["patient_id"], row["pool"])
                for row in connection.execute("SELECT patient_id, pool FROM enrollments")
            }

        self.assertEqual(result["planned"], 3)
        self.assertEqual(
            enrolled,
            {
                ("P-ELIGIBLE", "confirmed"),
                ("P-CANCELLED-FUTURE", "confirmed"),
                ("P-NO-HISTORY", "no_history"),
            },
        )
        self.assertIsNotNone(states["P-FUTURE"].future_booking_at)
        self.assertEqual(states["P-NO-HISTORY"].history_status, "no_appointment_records")

    def test_weekly_plan_is_created_only_once(self) -> None:
        """Repeating planning in the same week must not duplicate enrollment."""
        self.write_data(
            [patient_row("P-1")],
            [appointment_row("A-1", "P-1", "2025-12-01T18:00:00+00:00", completed="true")],
        )
        states = self.load_states()

        first = self.plan(states)
        second = self.plan(states)

        with self.database.connection() as connection:
            enrollment_count = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
            message_count = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

        self.assertEqual(first["planned"], 1)
        self.assertEqual(second, {"planned": 0, "reason": "already_planned"})
        self.assertEqual(enrollment_count, 1)
        self.assertEqual(message_count, 3)
