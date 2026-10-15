# Automatic Work-time Tracker

A configurable, local-first work-time tracker. Log office or remote sessions, export a standard calendar file, and calculate when your daily work target is reached.

**Defaults: 8 hours, UTC timezone, no automatic break deduction.** Change these during setup. The command-line interface is currently in Swedish.

## Platform support

| Feature | Windows / macOS | Linux |
| --- | --- | --- |
| Manual start/stop, reports and corrections | Portable Python implementation | Supported and tested |
| CSV and standard `.ics` calendar export | Portable Python implementation | Supported and tested |
| Automatic office Wi-Fi and sleep tracking | Not implemented | NetworkManager + systemd |
| Remote-work desktop question and target notification | Not implemented | Optional KDE/desktop integration |
| Automatic local calendar refresh | Depends on your calendar app | Optional KOrganizer adapter |

Native Windows/macOS execution has not yet been tested. There is no claim of automatic Wi-Fi or sleep detection there. The portable core does not require KDE or a calendar account.

## Setup

Python 3.10 or newer is required. On Windows, install Python's timezone data:

```bash
python -m pip install -r requirements.txt
```

Run the application with `python` (or `python3` on Linux/macOS, `py` on Windows). In the checkout:

```bash
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
```

Edit your local `.env`:

```dotenv
ARBETSTID_WIFI="OfficeWiFi"
ARBETSTID_TIMEZONE="UTC"
ARBETSTID_DAILY_HOURS=8
ARBETSTID_BREAK_MINUTES=0
```

- **Daily hours** are the net work target. Use your own schedule.
- **Timezone** is an IANA name, for example `Europe/Stockholm` or `America/New_York`. UTC is the neutral default.
- **Break minutes** are an optional unpaid daily allowance. Leave `0` if you explicitly stop/start for breaks, or configure a fixed deduction if you leave tracking running during lunch. Actual gaps between sessions count towards this allowance so the same break is not deducted twice.
- **Office Wi-Fi** is used only by the optional Linux automation. Manual tracking works without Wi-Fi.
- Optional **ARBETSTID_DATA_DIR** selects another private storage directory.

Example with an eight-hour work target: a continuous 09:00 session targets 17:00 without a fixed break, or 17:30 with a configured 30-minute unpaid break. A recorded 12:00–12:30 gap already covers that break allowance. Longer recorded breaks shift the projected end accordingly.

`.env` is ignored by Git; `.env.example` has placeholders only. Process environment variables override the file. `ARBETSTID_ENV_FILE` selects another configuration file. Values are literal: shell commands and variable expansion are never executed. Use full-line comments and quote values containing spaces.

This application needs no Wi-Fi password, API key, GitHub token or cloud-calendar credential. Keep your actual network names, work logs and configuration private.

## Manual use: all platforms

```bash
python arbetstid.py start --place office
python arbetstid.py stop
python arbetstid.py start --place remote
python arbetstid.py status
python arbetstid.py report
python arbetstid.py export > work-times.csv
python arbetstid.py calendar
python arbetstid.py correct 1 --start '2025-05-12T09:00' --end '2025-05-12T17:30'
```

Only completed sessions can be corrected through the CLI. Corrections retain an audit trail and cannot overlap other sessions. Repeated starts do not create duplicates.

**Manual mode requires explicit stop.** Without the optional Linux background service, sleep or shutdown does not end a session, notifications are not scheduled, and an unclosed session can count overnight until corrected. Do not leave a manual session running when finished.

Reports show gross recorded time per session and in the period total, with today's net work shown separately after any configured unpaid-break allowance. Gaps between sessions are never recorded as work.

## Use your calendar

`python arbetstid.py calendar` creates or refreshes a standard `.ics` file and prints its path. Import it using your calendar application's iCalendar import feature. A normal file import is a snapshot: re-importing or refreshing is a calendar-client operation, not cloud synchronization. The application does not upload to Google Calendar, Outlook, iCloud or any other account.

Stable event identifiers help calendar clients recognize the same entries, but duplicate handling on repeated manual import depends on the client. Completed entries show actual times. Open sessions are tentative and show a projected end; refresh the file during overtime to extend them. A separate transparent event marks the daily work target.

For automatic updates, your calendar must support watching/subscribing to a local file or use a dedicated adapter. The included **optional KOrganizer adapter is Linux-specific**:

```bash
python register_calendar.py
```

It registers a read-only **Arbetstid** calendar for the generated local file using Akonadi. Select that calendar in KOrganizer's sidebar. Other calendars are preserved. Correct times in the tracker, not the calendar. A historical day that ended early may show the target it would have reached if work continued; its description identifies that projection.

## Optional Linux automation

The included background service targets Ubuntu/KDE Plasma. It uses NetworkManager, systemd user services and optionally these desktop packages:

```bash
sudo apt install python3-dbus python3-gi kdialog libnotify-bin konsole
# Only if you want the included calendar adapter:
sudo apt install korganizer
```

Clone into a permanent directory whose path contains only letters, digits, `_`, `-`, `/` and `.`. Configure `.env` first, then:

```bash
bash install.sh
~/.local/bin/arbetstid status
```

Installation creates/replaces the user's `arbetstid.service`, command wrapper and three menu shortcuts. It requires no root and does not erase the local database. The service uses this checkout, so keep it in place. Before upgrading an existing installation, stop its service; stopping it ends its current session.

At the office, the configured Wi-Fi starts a session. On weekdays, an unlocked desktop on another network receives at most one remote-work question per local date. Only Yes starts work, from the response time. No, closing the question or a two-minute timeout starts nothing. Manual start works later that day, offline or on weekends.

Manual stop pauses automatic starts on every network for the remainder of that local day. Manual start clears the pause. A confirmed remote session ignores Wi-Fi drops and charger unplugging; arrival at the office switches to an office session.

A desktop notification is sent at most once per day when the configured **net daily target** is reached while a session is active. It does not end work. Tracking and calendar updates continue during overtime, with no separate duplicate calendar alarm. Prompts require the graphical session's D-Bus/display environment, normally supplied by KDE.

### Departure rules and limitations

- Office Wi-Fi is sampled about every ten seconds. Disconnections under five minutes are ignored. A longer disconnection closes at the first observed time and is flagged for review.
- Office sleep/shutdown ends the session. If AC was unplugged in the preceding ten minutes, that observed time is used. Unplugging alone does not end work.
- Remote sleep/shutdown or manual stop ends remote work at that time.
- Sleep during the day also counts as departure. There is no keyboard-idle timeout.
- After a reboot, unexpected gap over two minutes or backwards clock jump, an open session is recovered at the last observed time and flagged. Overnight downtime is not automatically filled as work by the Linux daemon.
- Stopping the service or logging out ends the session and may create another at the office when restarted.
- Same-named Wi-Fi elsewhere can give a false arrival. SSID matching is a convenience signal, not authentication. These are editable estimates based on laptop use; test a real sleep/resume cycle on your hardware.

## Data and privacy

Default runtime directories:

- Windows: `%LOCALAPPDATA%\Arbetstid`
- macOS: `~/Library/Application Support/Arbetstid`
- Linux: `$XDG_DATA_HOME/arbetstid` or `~/.local/share/arbetstid`

Files include SQLite sessions and correction history, confirmation dates, reminder state and the calendar export. They are **not encrypted at rest**. File permissions are private where supported; Windows access control follows the account's filesystem permissions. The KOrganizer adapter also imports events into the local Akonadi cache. This application makes no network uploads.

The repository ignores `.env`, databases and SQLite sidecars, calendar files, exports, logs, Python caches and common private-key filenames. Do not force-add private configuration or runtime data. Use a GitHub noreply address if you do not want your email in public commit metadata.

## Tests

```bash
python -m unittest discover -v
```

Tests use temporary databases and synthetic times, not real work logs. They cover migration, network interruptions, reboot recovery, remote confirmation, manual controls, net targets and breaks, timezone/daylight saving behavior, calendar output and reminder deduplication. They do not install a service, register calendars or send real notifications. Windows/macOS-native validation is still outstanding.

## Uninstall Linux automation

```bash
systemctl --user disable --now arbetstid.service
rm ~/.config/systemd/user/arbetstid.service ~/.local/bin/arbetstid
rm ~/.local/share/applications/arbetstid{,-start,-stop}.desktop
systemctl --user daemon-reload
```

Remove the optional **Arbetstid** calendar in KOrganizer separately. Local logs and `.env` are retained; delete them only if you intend to erase that data. With manual-only use there is no installed service to remove.

## License

MIT. See [LICENSE](LICENSE).
