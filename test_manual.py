"""Manual mode must work without NetworkManager, D-Bus or a running daemon."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from locking import FileLock

class ManualTests(unittest.TestCase):
    def test_manual_cli_without_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            env={**os.environ,'ARBETSTID_ENV_FILE':os.devnull,'ARBETSTID_TIMEZONE':'UTC','ARBETSTID_DAILY_HOURS':'8','ARBETSTID_BREAK_MINUTES':'0'}
            def run(*args):
                return subprocess.run([sys.executable,str(Path(__file__).with_name('arbetstid.py')),'--data-dir',directory,*args],env=env,capture_output=True,text=True,encoding='utf-8',check=True).stdout
            self.assertIn('Kontor',run('start','--place','office'))
            run('start','--place','remote')
            run('stop')
            output=run('report')
            self.assertIn('Avslutat',output)
            self.assertTrue((Path(directory)/'arbetstid.ics').exists())
            with sqlite3.connect(Path(directory)/'logg.sqlite3') as c:
                rows=c.execute('SELECT place,end FROM passes').fetchall()
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0][0],'Kontor'); self.assertIsNotNone(rows[0][1])
    def test_lock_excludes_second_writer_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lock'
            with FileLock(path) as first:
                first.acquire()
                with FileLock(path) as second:
                    with self.assertRaises(BlockingIOError): second.acquire()
            with FileLock(path) as next_lock: next_lock.acquire()

if __name__=='__main__': unittest.main()
