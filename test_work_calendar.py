import os
for key in list(os.environ):
    if key.startswith('ARBETSTID_'):
        os.environ.pop(key)
os.environ['ARBETSTID_ENV_FILE'] = os.devnull
for key in ('ARBETSTID_WIFI','ARBETSTID_TIMEZONE','ARBETSTID_DAILY_HOURS','ARBETSTID_BREAK_MINUTES'):
    os.environ.pop(key,None)
os.environ['ARBETSTID_TIMEZONE'] = 'Europe/Stockholm'
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
import work_calendar
from work_calendar import TZ, daily_progress, write_calendar, _fold


def ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ).timestamp()


def row(ident, start, end=None, place='Kontor'):
    return (ident, ts(start), ts(end) if end else None, '', 0, place)


class CalendarTests(unittest.TestCase):
    def test_single_shift_target(self):
        rows = [row(1, '2026-10-15T08:15')]
        progress = daily_progress(rows, ts('2026-10-15T10:00'))
        self.assertEqual(progress['target'], ts('2026-10-15T16:15'))
        self.assertEqual(progress['worked_seconds'], 105 * 60)
        self.assertTrue(progress['active'])

    def test_breaks_excluded_and_threshold_kept_during_overtime(self):
        rows = [row(1, '2026-10-15T08:00', '2026-10-15T10:00'),
                row(2, '2026-10-15T11:00')]
        before = daily_progress(rows, ts('2026-10-15T12:00'))
        self.assertEqual(before['target'], ts('2026-10-15T17:00'))
        after = daily_progress(rows, ts('2026-10-15T18:00'))
        self.assertEqual(after['target'], ts('2026-10-15T17:00'))
        self.assertEqual(after['remaining_seconds'], 0)
        self.assertEqual(after['worked_seconds'], 9 * 3600)

    def test_completed_early_projection(self):
        progress = daily_progress([row(1, '2026-10-15T08:00', '2026-10-15T10:00')], ts('2026-10-15T15:00'))
        self.assertFalse(progress['active'])
        self.assertEqual(progress['target'], ts('2026-10-15T16:00'))

    def test_midnight_and_dst_count_actual_elapsed_seconds(self):
        rows = [row(1, '2026-10-24T23:00', '2026-10-25T05:00')]
        progress = daily_progress(rows, ts('2026-10-25T06:00'))
        self.assertEqual(progress['worked_seconds'], 6 * 3600)
        self.assertEqual(progress['target'], ts('2026-10-25T07:00'))
        spring = [row(2, '2026-03-28T23:00', '2026-03-29T05:00')]
        self.assertEqual(daily_progress(spring, ts('2026-03-29T06:00'))['worked_seconds'], 4 * 3600)

    def test_midnight_end_does_not_create_next_day(self):
        self.assertIsNone(daily_progress([row(1, '2026-10-14T20:00', '2026-10-15T00:00')], ts('2026-10-15T10:00')))

    def test_no_data_for_today(self):
        self.assertIsNone(daily_progress([], ts('2026-10-15T10:00')))
        self.assertIsNone(daily_progress([row(1, '2026-10-14T08:00', '2026-10-14T12:00')], ts('2026-10-15T10:00')))

    def test_calendar_stability_actual_ends_and_target_uids(self):
        rows = [row(1, '2026-10-14T08:00', '2026-10-14T17:00'),
                row(2, '2026-10-15T08:15')]
        with tempfile.TemporaryDirectory() as directory:
            path = write_calendar(directory, rows, ts('2026-10-15T10:00'))
            original = path.read_bytes()
            modified = path.stat().st_mtime_ns
            write_calendar(directory, rows, ts('2026-10-15T10:01'))
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(modified, path.stat().st_mtime_ns)
            text = original.decode().replace('\r\n ', '')
            self.assertEqual(text.count('UID:arbetstid-pass-1@local'), 1)
            self.assertEqual(text.count('UID:arbetstid-target-2026-10-14@local'), 1)
            self.assertIn('DTEND:20261014T150000Z', text)
            self.assertIn('DTSTART:20261014T140000Z', text)  # 8h target, actual end later
            self.assertIn('STATUS:TENTATIVE', text)
            self.assertNotIn('VALARM', text)
            if os.name != 'nt': self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertNotIn(b'\n', original.replace(b'\r\n', b''))

    def test_utf8_folding_and_escaping(self):
        long = 'DESCRIPTION:' + 'å' * 200
        folded = _fold(long)
        self.assertEqual(folded.replace('\r\n ', ''), long)
        self.assertTrue(all(len(line.encode()) <= 75 for line in folded.split('\r\n')))
        with tempfile.TemporaryDirectory() as directory:
            path = write_calendar(directory, [row(1, '2026-10-15T08:00', '2026-10-15T12:00', 'Hem, åäö;\\\n' * 20)], ts('2026-10-15T13:00'))
            data = path.read_bytes()
            self.assertTrue(all(len(line) <= 75 for line in data.split(b'\r\n')))
            self.assertIn('Hem\\, åäö\\;\\\\\\n', data.decode().replace('\r\n ', ''))

    def test_open_overtime_changes_only_by_minute(self):
        rows = [row(1, '2026-10-15T08:00')]
        with tempfile.TemporaryDirectory() as directory:
            path = write_calendar(directory, rows, ts('2026-10-15T17:00:05'))
            before = path.read_bytes()
            write_calendar(directory, rows, ts('2026-10-15T17:00:50'))
            self.assertEqual(before, path.read_bytes())
            write_calendar(directory, rows, ts('2026-10-15T17:01:00'))
            self.assertNotEqual(before, path.read_bytes())

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_uninterrupted_shift_deducts_configured_break(self):
        rows = [row(1, '2026-10-15T08:15')]
        beginning = daily_progress(rows, ts('2026-10-15T08:15'))
        self.assertEqual(beginning['target'], ts('2026-10-15T16:45'))
        progress = daily_progress(rows, ts('2026-10-15T16:45'))
        self.assertEqual(progress['worked_seconds'], 8 * 3600)
        self.assertEqual(progress['gross_seconds'], 8.5 * 3600)
        self.assertEqual(progress['break_deduction_seconds'], 1800)
        self.assertEqual(progress['remaining_seconds'], 0)
        self.assertEqual(progress['target'], ts('2026-10-15T16:45'))

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_recorded_half_hour_break_not_deducted_twice(self):
        rows = [row(1, '2026-10-15T08:15', '2026-10-15T12:15'),
                row(2, '2026-10-15T12:45')]
        progress = daily_progress(rows, ts('2026-10-15T16:45'))
        self.assertEqual(progress['worked_seconds'], 8 * 3600)
        self.assertEqual(progress['break_deduction_seconds'], 0)
        self.assertEqual(progress['recorded_gap_seconds'], 1800)
        self.assertEqual(progress['target'], ts('2026-10-15T16:45'))

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_partial_break_credits_only_recorded_gap(self):
        rows = [row(1, '2026-10-15T08:15', '2026-10-15T12:15'),
                row(2, '2026-10-15T12:30')]
        progress = daily_progress(rows, ts('2026-10-15T16:45'))
        self.assertEqual(progress['gross_seconds'], 8.25 * 3600)
        self.assertEqual(progress['worked_seconds'], 8 * 3600)
        self.assertEqual(progress['break_deduction_seconds'], 900)
        self.assertEqual(progress['target'], ts('2026-10-15T16:45'))

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_long_break_does_not_reduce_work_target(self):
        rows = [row(1, '2026-10-15T08:15', '2026-10-15T12:15'),
                row(2, '2026-10-15T13:15')]
        progress = daily_progress(rows, ts('2026-10-15T17:15'))
        self.assertEqual(progress['worked_seconds'], 8 * 3600)
        self.assertEqual(progress['break_deduction_seconds'], 0)
        self.assertEqual(progress['target'], ts('2026-10-15T17:15'))

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_later_break_does_not_move_previously_reached_target(self):
        rows = [row(1, '2026-10-15T08:15', '2026-10-15T17:00'),
                row(2, '2026-10-15T17:30')]
        progress = daily_progress(rows, ts('2026-10-15T18:00'))
        self.assertEqual(progress['target'], ts('2026-10-15T16:45'))

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_overlapping_segments_are_merged_before_deduction(self):
        rows = [row(1, '2026-10-15T08:15', '2026-10-15T12:15'),
                row(2, '2026-10-15T11:15', '2026-10-15T16:45')]
        progress = daily_progress(rows, ts('2026-10-15T18:00'))
        self.assertEqual(progress['gross_seconds'], 8.5 * 3600)
        self.assertEqual(progress['worked_seconds'], 8 * 3600)
        self.assertEqual(progress['recorded_gap_seconds'], 0)

    @patch('work_calendar.UNPAID_BREAK_SECONDS', 1800)
    def test_short_shift_deduction_clamped_to_gross(self):
        progress = daily_progress([row(1, '2026-10-15T08:15')], ts('2026-10-15T08:25'))
        self.assertEqual(progress['gross_seconds'], 600)
        self.assertEqual(progress['worked_seconds'], 0)
        self.assertEqual(progress['break_deduction_seconds'], 600)
        self.assertEqual(progress['target'], ts('2026-10-15T16:45'))


if __name__ == '__main__':
    unittest.main()
