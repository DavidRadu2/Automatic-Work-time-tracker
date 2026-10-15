"""Load local configuration without executing shell code or logging values."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def read_env(path):
    values = {}
    if not path.exists():
        return values
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Invalid .env syntax on line {number}')
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key.isidentifier():
            raise ValueError(f'Invalid .env key on line {number}')
        if value[:1] in ('"', "'"):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed .env quote on line {number}')
            value = value[1:-1]
        values[key] = value
    return values


ENV_PATH = Path(os.environ.get('ARBETSTID_ENV_FILE', str(Path(__file__).with_name('.env'))))
LOCAL = read_env(ENV_PATH)


def value(key, default):
    return os.environ.get(key, LOCAL.get(key, default))


SSID = value('ARBETSTID_WIFI', 'OfficeWiFi')
if not SSID or '\n' in SSID or '\r' in SSID:
    raise ValueError('ARBETSTID_WIFI must be a nonempty single line')
TZ = ZoneInfo(value('ARBETSTID_TIMEZONE', 'UTC'))
DAILY_TARGET = float(value('ARBETSTID_DAILY_HOURS', '8')) * 3600
if not 0 < DAILY_TARGET <= 24 * 3600:
    raise ValueError('ARBETSTID_DAILY_HOURS must be greater than zero and at most 24')
TARGET_HOURS = f'{DAILY_TARGET / 3600:g}'

UNPAID_BREAK_SECONDS = float(value('ARBETSTID_BREAK_MINUTES', '0')) * 60
if not 0 <= UNPAID_BREAK_SECONDS < 24 * 3600:
    raise ValueError('ARBETSTID_BREAK_MINUTES must be at least zero and less than 1440')
if os.name == 'nt':
    DEFAULT_DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Arbetstid'
elif __import__('sys').platform == 'darwin':
    DEFAULT_DATA = Path.home() / 'Library' / 'Application Support' / 'Arbetstid'
else:
    DEFAULT_DATA = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'arbetstid'
DATA_DIR = Path(value('ARBETSTID_DATA_DIR', str(DEFAULT_DATA))).expanduser()
