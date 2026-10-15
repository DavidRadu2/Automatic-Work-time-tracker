"""Private, local iCalendar projection of work sessions; no network access."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from settings import TZ, DAILY_TARGET, TARGET_HOURS, UNPAID_BREAK_SECONDS
import os
import tempfile



def _bounds(day):
    start = datetime.combine(day, datetime.min.time(), TZ)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _progress(rows, day, now):
    midnight, tomorrow = _bounds(day)
    segments = []
    for ident, start, end, reason, uncertain, place in rows:
        stop = now if end is None else min(end, now)
        a, b = max(start, midnight), min(stop, tomorrow)
        if a < tomorrow and start <= now and b >= a and stop >= midnight:
            # An end exactly at midnight belongs only to the preceding day.
            if b == midnight and start < midnight:
                continue
            segments.append((a, b, end is None and start <= now < tomorrow))
    if not segments:
        return None
    segments.sort()
    merged = []
    for a, b, active in segments:
        if merged and a <= merged[-1][1]:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], b), previous[2] or active)
        else:
            merged.append((a, b, active))
    gross, gaps, target = 0, 0, None
    previous_end = None
    for a, b, active in merged:
        if previous_end is not None:
            gaps += a - previous_end
        deduction = max(0, UNPAID_BREAK_SECONDS - gaps)
        needed = DAILY_TARGET + deduction - gross
        # A newly recorded break may satisfy the allowance at the next start.
        # Preserve an earlier actual threshold; later breaks cannot move it back.
        if target is None and needed <= b - a:
            target = a + max(0, needed)
        gross += b - a
        previous_end = b
    deduction = min(gross, max(0, UNPAID_BREAK_SECONDS - gaps))
    worked = max(0, gross - deduction)
    remaining = max(0, DAILY_TARGET - worked)
    active = any(segment[2] for segment in merged)
    if target is None:
        # Include the undeducted allowance even before any net work accrues.
        future_gross = max(0, DAILY_TARGET + max(0, UNPAID_BREAK_SECONDS - gaps) - gross)
        target = (now if active else merged[-1][1]) + future_gross
    return dict(target=target, worked_seconds=worked, gross_seconds=gross,
                break_deduction_seconds=deduction, recorded_gap_seconds=gaps,
                remaining_seconds=remaining, active=active,
                date=day.isoformat(), first_start=merged[0][0])


def daily_progress(rows, now):
    """Today's clipped work, remaining seconds, projected/reached target timestamp.

    Return None without work today; otherwise keys: target, worked_seconds,
    remaining_seconds, active, date (ISO local date), first_start (timestamp),
    gross_seconds, break_deduction_seconds, recorded_gap_seconds. Recorded gaps
    count toward the configured unpaid break; only its outstanding allowance
    is deducted from gross work. Once reached, target keeps the first instant
    the configured net-work target was actually reached.
    """
    return _progress(rows, datetime.fromtimestamp(now, TZ).date(), now)


def _escape(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _fold(line):
    """RFC 5545: physical lines <=75 octets, including continuation space."""
    parts, current, size = [], '', 0
    for char in line:
        width = len(char.encode('utf-8'))
        if size + width > 75:
            parts.append(current)
            current, size = ' ', 1
        current += char
        size += width
    parts.append(current)
    return '\r\n'.join(parts)


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _event(uid, start, end, summary, description, tentative=False, transparent=False):
    return ['BEGIN:VEVENT', 'UID:' + uid, 'DTSTAMP:' + _utc(start),
            'DTSTART:' + _utc(start), 'DTEND:' + _utc(end),
            'SUMMARY:' + _escape(summary), 'DESCRIPTION:' + _escape(description),
            'STATUS:' + ('TENTATIVE' if tentative else 'CONFIRMED'),
            'TRANSP:' + ('TRANSPARENT' if transparent else 'OPAQUE'), 'END:VEVENT']


def write_calendar(directory, rows, now):
    """Atomically update private arbetstid.ics, only when content changes.

    Closed shifts retain actual ends. An open shift has a tentative projected
    end; targets are separate transparent one-minute events without alarms.
    Returns the Path of the local calendar.
    """
    rows = list(rows)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Arbetstid//Lokal logg//SV',
             'CALSCALE:GREGORIAN', 'X-WR-CALNAME:Arbetstid']
    dates = set()
    current = daily_progress(rows, now)
    for ident, start, end, reason, uncertain, place in sorted(rows, key=lambda row: (row[1], row[0])):
        if start > now:
            continue
        tentative = end is None
        if tentative:
            projected = current['target'] if current else now
            finish = max(start, projected, int(now // 60) * 60)
            summary = 'Arbete (pågår)'
            description = f'{place}. Planerad sluttid; faktisk sluttid är ännu inte känd.'
        else:
            finish = end
            summary = 'Arbete – ' + str(place)
            description = 'Faktiskt arbetspass. ' + (reason or '')
            if uncertain:
                description += ' Kontrollera registreringen.'
        lines += _event(f'arbetstid-pass-{ident}@local', start, finish, summary, description, tentative)
        day = datetime.fromtimestamp(start, TZ).date()
        final_day = datetime.fromtimestamp(min(now, end if end is not None else now), TZ).date()
        while day <= final_day:
            if _progress([(ident, start, end, reason, uncertain, place)], day, now):
                dates.add(day)
            day += timedelta(days=1)
    for day in sorted(dates):
        progress = _progress(rows, day, now)
        target = progress['target']
        description = f'{TARGET_HOURS} timmars nettoarbetstid. Registrerade avbrott räknas mot inställd obetald rast.'
        if progress['worked_seconds'] < DAILY_TARGET:
            description += f' Planerad tid; {TARGET_HOURS} timmar är ännu inte registrerade denna dag.'
        else:
            description += f' {TARGET_HOURS} timmar uppnåddes vid denna tid.'
        lines += _event(f'arbetstid-target-{day.isoformat()}@local', target, target + 60,
                        f'Planerad sluttid – {TARGET_HOURS} timmar', description, transparent=True)
    lines.append('END:VCALENDAR')
    content = ('\r\n'.join(_fold(line) for line in lines) + '\r\n').encode('utf-8')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / 'arbetstid.ics'
    if destination.exists() and destination.read_bytes() == content:
        destination.chmod(0o600)
        return destination
    descriptor, temporary = tempfile.mkstemp(prefix='.arbetstid-', suffix='.ics', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination
