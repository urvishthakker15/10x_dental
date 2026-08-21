"""Calendar-month and overdue-segment boundary tests."""

from datetime import date

from recall_engine.eligibility import calendar_months_elapsed, recall_segment

from tests.support import EngineTestCase, appointment_row, patient_row


class CalendarMonthTests(EngineTestCase):
    def test_complete_calendar_months_handle_month_end(self) -> None:
        """A clamped month-end anniversary counts as a complete calendar month."""
        cases = [
            (date(2026, 1, 31), date(2026, 2, 27), 0),
            (date(2026, 1, 31), date(2026, 2, 28), 1),
            (date(2024, 2, 29), date(2024, 8, 29), 6),
            (date(2025, 11, 20), date(2026, 8, 20), 9),
        ]
        for start, end, expected in cases:
            with self.subTest(start=start, end=end):
                self.assertEqual(calendar_months_elapsed(start, end), expected)

    def test_segment_boundaries_use_calendar_months(self) -> None:
        """Segment transitions occur exactly at 6, 9, 18, and 36 months."""
        as_of = date(2026, 8, 20)
        cases = [
            (date(2026, 2, 20), None),
            (date(2026, 2, 19), "hot"),
            (date(2025, 11, 21), "hot"),
            (date(2025, 11, 20), "warm"),
            (date(2025, 2, 21), "warm"),
            (date(2025, 2, 20), "cold"),
            (date(2023, 8, 21), "cold"),
            (date(2023, 8, 20), "very_cold"),
        ]
        for last_visit, expected in cases:
            with self.subTest(last_visit=last_visit):
                self.assertEqual(recall_segment(last_visit, as_of), expected)

    def test_derived_states_expose_segment_and_month_count_source(self) -> None:
        """The CSV-derived state uses the same visit date that drives personalization."""
        patients = [
            patient_row("P-HOT"),
            patient_row("P-WARM"),
            patient_row("P-COLD"),
            patient_row("P-VERY-COLD"),
        ]
        appointments = [
            appointment_row("A-1", "P-HOT", "2025-12-20T18:00:00+00:00", completed="true"),
            appointment_row("A-2", "P-WARM", "2025-11-20T18:00:00+00:00", completed="true"),
            appointment_row("A-3", "P-COLD", "2025-02-20T18:00:00+00:00", completed="true"),
            appointment_row("A-4", "P-VERY-COLD", "2023-08-20T18:00:00+00:00", completed="true"),
        ]
        self.write_data(patients, appointments)

        states = self.load_states()

        self.assertEqual(states["P-HOT"].segment, "hot")
        self.assertEqual(states["P-WARM"].segment, "warm")
        self.assertEqual(states["P-COLD"].segment, "cold")
        self.assertEqual(states["P-VERY-COLD"].segment, "very_cold")
