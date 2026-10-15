import os
os.environ['ARBETSTID_ENV_FILE'] = os.devnull
for key in ('ARBETSTID_WIFI','ARBETSTID_TIMEZONE','ARBETSTID_DAILY_HOURS','ARBETSTID_BREAK_MINUTES'):
    os.environ.pop(key,None)
os.environ['ARBETSTID_TIMEZONE'] = 'Europe/Stockholm'
import tempfile
import unittest
from pathlib import Path
from settings import read_env

class SettingsTests(unittest.TestCase):
    def test_literal_values_without_shell_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.env'
            p.write_text('# Comment\nARBETSTID_WIFI="Example office"\nLITERAL=$(echo no)\n')
            self.assertEqual(read_env(p),{'ARBETSTID_WIFI':'Example office','LITERAL':'$(echo no)'})
    def test_missing_file_has_no_settings(self):
        self.assertEqual(read_env(Path('/nonexistent/arbetstid-config-file')), {})
    def test_invalid_quotes_report_line_without_value(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.env';p.write_text('VALUE="private-example\n')
            with self.assertRaisesRegex(ValueError,'line 1') as err: read_env(p)
            self.assertNotIn('private-example',str(err.exception))
if __name__=='__main__': unittest.main()
