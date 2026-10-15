import os
os.environ['ARBETSTID_ENV_FILE'] = os.devnull
for key in ('ARBETSTID_WIFI','ARBETSTID_TIMEZONE','ARBETSTID_DAILY_HOURS','ARBETSTID_BREAK_MINUTES'):
    os.environ.pop(key,None)
os.environ['ARBETSTID_TIMEZONE'] = 'Europe/Stockholm'
import tempfile, unittest, sqlite3
from unittest.mock import patch
from types import SimpleNamespace
import arbetstid
from arbetstid import Tracker
class LogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.t=Tracker(self.tmp.name,'boot1')
    def tearDown(self): self.t.db.close(); self.tmp.cleanup()
    def rows(self): return self.t.db.execute('SELECT start,end,reason,uncertain FROM passes ORDER BY id').fetchall()
    def advance(self,start,end,wifi=True,ac=True):
        for now in range(start,end+1,10): self.t.tick(now,wifi,ac)
    def test_duplicate_arrival(self):
        self.advance(1000,1100); self.assertEqual(len(self.rows()),1)
    def test_brief_disconnect(self):
        self.advance(1000,1100); self.advance(1110,1200,False); self.t.tick(1210,True,True)
        self.assertEqual(len(self.rows()),1); self.assertIsNone(self.rows()[0][1])
    def test_long_disconnect(self):
        self.t.tick(1000,True,True); self.advance(1010,1310,False)
        self.assertEqual(self.rows()[0][1],1010); self.assertEqual(self.rows()[0][3],1)
        self.t.tick(1320,True,True); self.assertEqual(len(self.rows()),2)
    def test_shutdown_uses_unplug(self):
        self.t.tick(1000,True,True); self.t.tick(1010,True,False); self.t.stop(1020,'Avstängning')
        self.assertEqual(self.rows()[0][1],1010)
    def test_unplug_alone_does_not_close(self):
        self.t.tick(1000,True,True); self.advance(1010,1700,True,False)
        self.assertIsNone(self.rows()[0][1]); self.t.stop(1710,'Avstängning'); self.assertEqual(self.rows()[0][1],1710)
    def test_replug_cancels_candidate(self):
        self.t.tick(1000,True,True); self.t.tick(1010,True,False); self.t.tick(1020,True,True); self.t.stop(1030,'Avstängning')
        self.assertEqual(self.rows()[0][1],1030)
    def test_reboot_never_counts_night(self):
        self.advance(1000,1100); self.t.db.close(); self.t=Tracker(self.tmp.name,'boot2'); self.t.tick(90000,True,True)
        r=self.rows(); self.assertEqual(r[0][1],1100); self.assertEqual(r[0][3],1); self.assertEqual(r[1][0],90000)
    def test_shutdown_then_next_morning(self):
        self.advance(1000,1100); self.t.stop(1110,'Avstängning'); self.t.db.close(); self.t=Tracker(self.tmp.name,'boot2'); self.t.tick(90000,True,True)
        self.assertEqual(self.rows()[0][1],1110); self.assertEqual(len(self.rows()),2)
    def test_unknown_network_not_departure(self):
        self.advance(1000,1100); self.advance(1110,2000,None); self.assertIsNone(self.rows()[0][1])
    def test_sleep_gap(self):
        self.advance(1000,1100); self.t.tick(90000,True,True)
        self.assertEqual(self.rows()[0][1],1100); self.assertEqual(self.rows()[0][3],1)
    def test_clock_backward(self):
        self.t.tick(1000,True,True); self.t.tick(900,True,True)
        self.assertGreaterEqual(self.rows()[0][1],self.rows()[0][0])
    def test_repeated_stop(self):
        self.t.tick(1000,True,True); self.t.stop(1010,'Avstängning'); self.t.stop(1020,'Avstängning'); self.assertEqual(self.rows()[0][1],1010)
    def test_wifi_uses_stable_locale(self):
        with patch('arbetstid.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='yes:OfficeWiFi\n')) as run:
            self.assertTrue(arbetstid.wifi_status())
            self.assertEqual(run.call_args.kwargs['env']['LC_ALL'],'C')
    def test_clock_backward_does_not_overlap(self):
        self.t.tick(1000,True,True); self.t.tick(900,True,True)
        self.assertEqual(len(self.rows()),1); self.assertIsNone(self.t.opened())
    def weekday(self):
        return arbetstid.datetime(2026,10,15,9,tzinfo=arbetstid.TZ).timestamp()
    def test_prompt_requires_unlocked_connected_weekday_and_no_pass(self):
        now=self.weekday()
        self.assertTrue(self.t.should_prompt(now,False,True,True))
        for wifi,connected,active in [(True,True,True),(None,True,True),(False,False,True),(False,True,False)]:
            self.assertFalse(self.t.should_prompt(now,wifi,connected,active))
        self.assertFalse(self.t.should_prompt(now+2*86400,False,True,True))
        self.t.start_remote(now)
        self.assertFalse(self.t.should_prompt(now,False,True,True))
    def test_decline_or_timeout_persists_for_day_only(self):
        now=self.weekday(); self.t.s['prompt_day']=self.t.day(now); self.t.save()
        self.t.db.close(); self.t=Tracker(self.tmp.name,'boot1')
        self.assertFalse(self.t.should_prompt(now+60,False,True,True))
        self.assertTrue(self.t.should_prompt(now+86400,False,True,True))
        self.assertIsNone(self.t.opened())
    def test_remote_ignores_network_and_charger(self):
        now=self.weekday(); self.t.start_remote(now); self.t.tick(now,False,True)
        for delta in range(10,710,10): self.t.tick(now+delta,False,False)
        self.assertEqual(len(self.rows()),1); self.assertIsNone(self.rows()[0][1]); self.assertTrue(self.t.remote())
    def test_remote_sleep_uses_sleep_time_not_unplug(self):
        now=self.weekday(); self.t.start_remote(now); self.t.s['unplug']=now+10
        self.t.stop(now+60,'Viloläge')
        self.assertEqual(self.rows()[0][1],now+60); self.assertEqual(self.rows()[0][3],0)
    def test_remote_reboot_closes_at_last_seen(self):
        now=self.weekday(); self.t.start_remote(now); self.t.tick(now+10,False,True)
        self.t.db.close(); self.t=Tracker(self.tmp.name,'boot2'); self.t.tick(now+86400,False,True)
        self.assertEqual(self.rows()[0][1],now+10); self.assertEqual(self.rows()[0][3],1); self.assertIsNone(self.t.opened())
    def test_manual_stop_blocks_office_reopen_until_new_day(self):
        now=self.weekday(); self.t.start_remote(now); self.t.manual_stop(now+10); self.t.tick(now+20,True,True)
        self.assertIsNone(self.t.opened()); self.assertFalse(self.t.should_prompt(now+30,False,True,True))
        self.t.tick(now+86400,True,True); self.assertIsNotNone(self.t.opened())
    def test_remote_arrival_at_office_splits_without_overlap(self):
        now=self.weekday(); self.t.start_remote(now); self.t.tick(now+10,True,True)
        r=self.rows(); self.assertEqual(r[0][1],r[1][0]); self.assertFalse(self.t.remote())
    def test_manual_start_is_idempotent(self):
        now=self.weekday(); self.t.start_remote(now); self.t.start_remote(now+10)
        self.assertEqual(len(self.rows()),1)
    def test_queued_commands_and_expiry(self):
        now=self.weekday()
        self.t.db.execute('INSERT INTO commands(action,created) VALUES(?,?)',('start',now-120)); self.t.db.commit()
        arbetstid.process_commands(self.t,now); self.assertIsNone(self.t.opened())
        self.t.db.execute('INSERT INTO commands(action,created) VALUES(?,?)',('start',now)); self.t.db.commit()
        arbetstid.process_commands(self.t,now); self.assertTrue(self.t.remote())
        self.t.db.execute('INSERT INTO commands(action,created) VALUES(?,?)',('stop',now+10)); self.t.db.commit()
        arbetstid.process_commands(self.t,now+10); self.assertIsNone(self.t.opened())
    def test_migration_preserves_old_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            c=sqlite3.connect(arbetstid.Path(directory)/'logg.sqlite3')
            c.execute('CREATE TABLE passes(id INTEGER PRIMARY KEY,start REAL NOT NULL,end REAL,reason TEXT,uncertain INTEGER DEFAULT 0)')
            c.execute('INSERT INTO passes(start,end) VALUES(1000,2000)'); c.commit(); c.close()
            migrated=Tracker(directory,'boot1')
            self.assertEqual(migrated.db.execute('SELECT start,end,place FROM passes').fetchone(),(1000,2000,'Kontor'))
            migrated.db.close()
    def test_reminder_only_at_daily_target_and_once_per_day(self):
        now=self.weekday(); self.t.start_remote(now)
        with patch('arbetstid.subprocess.run',return_value=SimpleNamespace(returncode=0)) as notify:
            self.assertFalse(arbetstid.check_reminder(self.t,now+28799))
            self.assertTrue(arbetstid.check_reminder(self.t,now+28800))
            self.assertFalse(arbetstid.check_reminder(self.t,now+28900))
            self.assertEqual(notify.call_count,1)
        self.t.db.close(); self.t=Tracker(self.tmp.name,'boot1')
        with patch('arbetstid.subprocess.run') as notify:
            self.assertFalse(arbetstid.check_reminder(self.t,now+29000)); notify.assert_not_called()
    def test_reminder_failure_retries_and_closed_pass_is_silent(self):
        now=self.weekday(); self.t.start_remote(now)
        with patch('arbetstid.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            self.assertFalse(arbetstid.check_reminder(self.t,now+28800))
        with patch('arbetstid.subprocess.run',return_value=SimpleNamespace(returncode=0)):
            self.assertTrue(arbetstid.check_reminder(self.t,now+28810))
        self.t.stop(now+28820,'Viloläge')
        with patch('arbetstid.subprocess.run') as notify:
            self.assertFalse(arbetstid.check_reminder(self.t,now+28900)); notify.assert_not_called()
if __name__=='__main__': unittest.main()
