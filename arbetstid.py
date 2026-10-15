#!/usr/bin/python3
"""Lokal arbetstidslogg. Inga externa tjänster."""
import argparse, csv, json, os, signal, sqlite3, subprocess, sys, time
from pathlib import Path
from datetime import datetime
from settings import SSID, TZ, TARGET_HOURS, DATA_DIR, UNPAID_BREAK_SECONDS
from locking import FileLock
from work_calendar import daily_progress, write_calendar, DAILY_TARGET
GAP=300
UNPLUG=600

def stamp(t):
    return datetime.fromtimestamp(t,TZ).isoformat(timespec='seconds') if t is not None else 'pågår'

class Tracker:
    def __init__(self, directory, boot):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(self.directory/'logg.sqlite3',timeout=10)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS passes(id INTEGER PRIMARY KEY,start REAL NOT NULL,end REAL,reason TEXT,uncertain INTEGER DEFAULT 0);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open ON passes((1)) WHERE end IS NULL;
        CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS edits(id INTEGER PRIMARY KEY,at REAL,pass_id INTEGER,old TEXT,new TEXT);''')
        if 'place' not in {r[1] for r in self.db.execute('PRAGMA table_info(passes)')}:
            self.db.execute("ALTER TABLE passes ADD COLUMN place TEXT NOT NULL DEFAULT 'Kontor'")
        self.db.execute('CREATE TABLE IF NOT EXISTS commands(id INTEGER PRIMARY KEY, action TEXT, created REAL, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS reminders(day TEXT PRIMARY KEY,notified REAL NOT NULL)')
        self.db.commit()
        row=self.db.execute('SELECT data FROM state WHERE id=1').fetchone()
        self.s=json.loads(row[0]) if row else {}
        self.boot=boot
    def opened(self):
        return self.db.execute('SELECT id,start FROM passes WHERE end IS NULL').fetchone()
    def remote(self):
        row=self.db.execute('SELECT place FROM passes WHERE end IS NULL').fetchone()
        return bool(row and row[0]=='Hemifrån')
    def day(self,now):
        return datetime.fromtimestamp(now,TZ).date().isoformat()
    def start_remote(self,now,place="Hemifrån"):
        if self.opened(): return 'Ett arbetspass pågår redan.'
        last_end=self.db.execute('SELECT MAX(end) FROM passes').fetchone()[0]
        if last_end is not None and now<last_end: return 'Kan inte starta: aktuell tid är tidigare än senaste sluttiden.'
        self.s.pop('manual_stop_day',None)
        self.s.pop('disconnect',None); self.s.pop('unplug',None)
        self.s.update(last_seen=now,boot=self.boot,prompt_day=self.day(now))
        self.db.execute("INSERT INTO passes(start,place) VALUES(?,?)",(now,place))
        self.save()
        return 'Arbetspass startat '+datetime.fromtimestamp(now,TZ).strftime('%H:%M')+' ('+place+').'
    def manual_stop(self,now):
        self.close(now,'Manuellt avslutat')
        self.s.update(manual_stop_day=self.day(now),prompt_day=self.day(now),last_seen=now)
        self.save()
        return 'Arbetspasset avslutat. Automatisk start pausad resten av dagen.'
    def should_prompt(self,now,wifi,connected,active):
        return (datetime.fromtimestamp(now,TZ).weekday()<5 and wifi is False and connected
                and active and not self.opened() and self.s.get('prompt_day')!=self.day(now)
                and self.s.get('manual_stop_day')!=self.day(now))
    def save(self):
        self.db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(json.dumps(self.s),))
        self.db.commit()
        self.refresh_calendar(self.s.get('last_seen',time.time()))
    def rows(self):
        return self.db.execute('SELECT id,start,end,reason,uncertain,place FROM passes ORDER BY start').fetchall()
    def refresh_calendar(self,now=None):
        try: write_calendar(self.directory,self.rows(),time.time() if now is None else now)
        except OSError as e: print('Kunde inte uppdatera den lokala kalendern: '+str(e),file=sys.stderr,flush=True)
    def close(self,at,reason,uncertain=False):
        row=self.opened()
        if row:
            self.db.execute('UPDATE passes SET end=?,reason=?,uncertain=? WHERE id=?',(max(row[1],at),reason,int(uncertain),row[0]))
        self.s.pop('disconnect',None); self.s.pop('unplug',None)
    def departure(self,now):
        u=self.s.get('unplug')
        return u if u is not None and 0<=now-u<=UNPLUG else now
    def tick(self,now,wifi,ac):
        old=self.s.get('last_seen')
        # A reboot or unobserved gap must never silently extend an old shift.
        if self.opened() and old is not None:
            if self.s.get('boot')!=self.boot or now-old>120 or now<old-2:
                self.close(old if self.remote() else self.departure(old),'Återställd efter omstart/uppehåll',True)
        if ac is True:
            self.s.pop('unplug',None)
        elif ac is False and self.s.get('ac') is True:
            self.s['unplug']=now
        if ac is not None: self.s['ac']=ac
        if self.remote():
            # Explicitly confirmed remote work is independent of network and charger.
            self.s.pop('disconnect',None); self.s.pop('unplug',None)
            if wifi is True:
                self.close(now,'Byte till kontoret')
                self.db.execute("INSERT INTO passes(start,place) VALUES(?,'Kontor')",(now,))
        elif wifi is True:
            d=self.s.get('disconnect')
            if d is not None and now-d>=GAP:
                self.close(d,'Wi-Fi frånkopplat minst 5 minuter',True)
            self.s.pop('disconnect',None)
            if not self.opened() and self.s.get('manual_stop_day')!=self.day(now):
                last_end=self.db.execute('SELECT MAX(end) FROM passes').fetchone()[0]
                if last_end is None or now>=last_end:
                    self.db.execute('INSERT INTO passes(start) VALUES(?)',(now,))
        elif wifi is False and self.opened():
            self.s.setdefault('disconnect',now)
            if now-self.s['disconnect']>=GAP:
                self.close(self.s['disconnect'],'Wi-Fi frånkopplat minst 5 minuter',True)
        self.s.update(last_seen=now,boot=self.boot)
        self.save()
    def stop(self,now,reason,uncertain=False):
        if self.opened():
            # Prefer an already observed network departure, then recent AC unplug.
            at=now if self.remote() else min(now,self.s.get('disconnect',now),self.departure(now))
            self.close(at,reason,uncertain)
        self.s['last_seen']=now; self.save()

def wifi_status():
    try:
        r=subprocess.run(['nmcli','-t','--escape','no','-f','ACTIVE,SSID','device','wifi'],capture_output=True,text=True,timeout=8,env={**os.environ,'LC_ALL':'C'})
        if r.returncode: return None
        return any(line=='yes:'+SSID for line in r.stdout.splitlines())
    except (OSError,subprocess.TimeoutExpired): return None

def ac_status():
    vals=[]
    for p in Path('/sys/class/power_supply').glob('*'):
        try:
            if (p/'type').read_text().strip() in ('Mains','USB','USB_C','USB_PD'):
                vals.append((p/'online').read_text().strip()=='1')
        except OSError: pass
    return any(vals) if vals else None

def connected_network():
    try:
        r=subprocess.run(['nmcli','-t','-f','STATE','general'],capture_output=True,text=True,timeout=5,env={**os.environ,'LC_ALL':'C'})
        return r.returncode==0 and r.stdout.strip().startswith('connected')
    except (OSError,subprocess.TimeoutExpired): return False

def desktop_active():
    try:
        import dbus
        bus=dbus.SessionBus()
        locked=dbus.Interface(bus.get_object('org.freedesktop.ScreenSaver','/ScreenSaver'),'org.freedesktop.ScreenSaver').GetActive(timeout=2)
        return not bool(locked)
    except Exception:
        return False  # No verified desktop session: use manual start instead.

def process_commands(t,now):
    commands=t.db.execute('SELECT id,action,created FROM commands WHERE result IS NULL ORDER BY id').fetchall()
    for ident,action,created in commands:
        if not 0<=now-created<=60: result='Kommandot löpte ut. Försök igen.'
        elif action in ('start','start-office'): result=t.start_remote(now,'Kontor' if action=='start-office' or wifi_status() is True else 'Hemifrån')
        elif action=='stop': result=t.manual_stop(now)
        else: result='Okänt kommando.'
        t.db.execute('UPDATE commands SET result=? WHERE id=?',(result,ident)); t.db.commit()
    return bool(commands)

def check_reminder(t,now):
    progress=daily_progress(t.rows(),now)
    if not progress or not progress['active'] or progress['worked_seconds']<DAILY_TARGET: return False
    day=progress['date']
    if t.db.execute('SELECT 1 FROM reminders WHERE day=?',(day,)).fetchone(): return False
    target=datetime.fromtimestamp(progress['target'],TZ).strftime('%H:%M')
    try:
        result=subprocess.run(['notify-send','--app-name=Arbetstid','--icon=office-calendar',f'Dagens {TARGET_HOURS} timmar är klara',f'Planerad sluttid: {target}. Du kan avsluta arbetsdagen. Loggningen fortsätter om du jobbar vidare.'],timeout=3,capture_output=True)
        if result.returncode!=0: return False
    except (OSError,subprocess.TimeoutExpired): return False
    t.db.execute('INSERT OR IGNORE INTO reminders(day,notified) VALUES(?,?)',(day,now)); t.db.commit()
    return True

def send_command(t,action):
    # The daemon alone changes open passes and in-memory state.
    with FileLock(t.directory/'daemon.lock') as lock:
        try: lock.acquire()
        except BlockingIOError: pass
        else:
            # Manual mode on any OS; no background service is required.
            t.db.execute('BEGIN IMMEDIATE')
            print(t.start_remote(time.time(),'Kontor' if action=='start-office' else 'Hemifrån') if action in ('start','start-office') else t.manual_stop(time.time()))
            return
    cur=t.db.execute('INSERT INTO commands(action,created) VALUES(?,?)',(action,time.time())); t.db.commit()
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        row=t.db.execute('SELECT result FROM commands WHERE id=?',(cur.lastrowid,)).fetchone()
        if row[0] is not None: print(row[0]); return
        time.sleep(.2)
    t.db.execute("UPDATE commands SET result='Avbrutet efter tidsgräns' WHERE id=? AND result IS NULL",(cur.lastrowid,)); t.db.commit()
    raise SystemExit('Inget svar från tjänsten. Kontrollera arbetstid status.')

def daemon(t):
    lock=FileLock(t.directory/'daemon.lock')
    try: lock.acquire()
    except BlockingIOError: raise SystemExit('Loggningen körs redan.')
    running=True; shutdown=False; sleeping=False; callbacks=[]; prompt=None
    def cancel_prompt():
        nonlocal prompt
        if prompt:
            proc=prompt[0]
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=1)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
            prompt=None
    def terminate(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,terminate); signal.signal(signal.SIGINT,terminate)
    # login1 signals are dispatched on this same thread before each sample.
    try:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
        DBusGMainLoop(set_as_default=True)
        bus=dbus.SystemBus()
        def power_signal(value,kind):
            nonlocal shutdown,sleeping
            now=time.time()
            if kind=='shutdown':
                shutdown=bool(value)
                if value: cancel_prompt(); t.stop(now,'Avstängning')
            else:
                sleeping=bool(value)
                if value: cancel_prompt(); t.stop(now,'Viloläge')
        callbacks.append(bus.add_signal_receiver(lambda v:power_signal(v,'shutdown'),signal_name='PrepareForShutdown',dbus_interface='org.freedesktop.login1.Manager'))
        callbacks.append(bus.add_signal_receiver(lambda v:power_signal(v,'sleep'),signal_name='PrepareForSleep',dbus_interface='org.freedesktop.login1.Manager'))
        context=GLib.MainContext.default()
    except ImportError:
        context=None
        print('Varning: strömsignaler saknas; tjänstestopp och uppehållsskydd används.',flush=True)
    print('Arbetstidslogg startad för '+SSID,flush=True)
    try:
        next_sample=0
        while running:
            if context:
                while context.pending(): context.iteration(False)
            if not shutdown and not sleeping and process_commands(t,time.time()):
                cancel_prompt()
            if prompt:
                proc,day,deadline=prompt
                if t.opened() or day!=t.day(time.time()) or time.monotonic()>=deadline:
                    cancel_prompt()
                elif proc.poll() is not None:
                    accepted=proc.returncode==0
                    prompt=None
                    if accepted and not shutdown and not sleeping and wifi_status() is False and connected_network() and desktop_active():
                        print(t.start_remote(time.time()),flush=True)
            if time.monotonic()>=next_sample:
                if not shutdown and not sleeping:
                    wifi=wifi_status(); ac=ac_status()
                    t.tick(time.time(),wifi,ac)
                    check_reminder(t,time.time())
                    if prompt and wifi is not False: cancel_prompt()
                    now=time.time()
                    if not prompt and wifi is False and t.should_prompt(now,wifi,connected_network(),desktop_active()):
                        t.s['prompt_day']=t.day(now); t.save()
                        try:
                            proc=subprocess.Popen(['kdialog','--title','Arbetstid – hemifrån','--yes-label','Ja, starta arbetspass','--no-label','Nej, privat användning','--yesno',f'Du är ansluten till ett annat nätverk än {SSID}.\n\nJobbar du hemifrån?\n\nJa startar loggningen från nu. Nej eller inget svar loggar inget.'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                            prompt=(proc,t.day(now),time.monotonic()+120)
                        except OSError as e: print('Kunde inte visa frågan om hemarbete: '+str(e),flush=True)
                next_sample=time.monotonic()+10
            time.sleep(.2)
    finally:
        cancel_prompt()
        if shutdown: t.stop(time.time(),'Avstängning')
        else: t.stop(time.time(),'Tjänsten stoppades/utloggning',True)
        lock.close()

def report(t,as_csv=False):
    rows=t.rows()
    if as_csv:
        out=csv.writer(sys.stdout); out.writerow(['id','ankomst','hemgång','timmar','orsak','kontrollera','plats'])
    total=0
    now=time.time()
    def hours_minutes(hours):
        minutes=int(hours*60)
        return f'{minutes//60} h {minutes%60:02d} min'
    if rows and not as_csv:
        print('\nARBETSTIDSLOGG\n')
        print(f'{"Pass":<6}{"Datum":<14}{"Ankomst":<10}{"Hemgång":<10}{"Arbetstid":<15}{"Plats":<12}Status')
        print('─'*81)
    if not rows and not as_csv: print('Inga arbetspass registrerade ännu.')
    for ident,start,end,reason,uncertain,place in rows:
        duration=max(0,(end if end is not None else now)-start)/3600
        total+=duration
        if as_csv: out.writerow([ident,stamp(start),stamp(end),f'{duration:.2f}',reason or '',bool(uncertain),place])
        else:
            arrival=datetime.fromtimestamp(start,TZ)
            departure=datetime.fromtimestamp(end,TZ) if end is not None else None
            end_text=departure.strftime('%H:%M') if departure else '–'
            status='Pågår' if end is None else ('Kontrollera' if uncertain else 'Avslutat')
            print(f'{ident:<6}{arrival:%Y-%m-%d}    {arrival:%H:%M}     {end_text:<10}{hours_minutes(duration):<15}{place:<12}{status}')
            if departure and departure.date()!=arrival.date():
                print(f'      Hemgångsdatum: {departure:%Y-%m-%d}')
            if uncertain and reason: print(f'      ↳ {reason}')
    if not as_csv:
        print(f'\nTotalt: {hours_minutes(total)}')
        progress=daily_progress(rows,now)
        if progress and progress['active']:
            target=datetime.fromtimestamp(progress['target'],TZ).strftime('%H:%M')
            print(f'Dagens planerade sluttid: {target} ({TARGET_HOURS} timmars arbete)')
            if progress['worked_seconds']>DAILY_TARGET:
                print(f'Tid utöver dagens {TARGET_HOURS} timmar: '+hours_minutes((progress['worked_seconds']-DAILY_TARGET)/3600))
        if progress:
            print('Dagens nettoarbete: '+hours_minutes(progress['worked_seconds']/3600))
        if UNPAID_BREAK_SECONDS:
            print(f'Rastinställning: {UNPAID_BREAK_SECONDS/60:g} min/dag; registrerade pauser räknas av mot schablonen.')
        else: print('Ingen schablonrast avdragen. Avbrott mellan pass räknas inte som arbete.')
        print('Totalen ovan visar registrerade pass, före eventuell schablonrast.\n')

def parse_date(value):
    d=datetime.fromisoformat(value)
    if d.tzinfo is None: d=d.replace(tzinfo=TZ)
    return d.timestamp()

def main():
    if os.name == 'nt' and hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',default=str(DATA_DIR))
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('daemon','status','report','export','start','stop','calendar'):
        cmd=sub.add_parser(name)
        if name=='start': cmd.add_argument('--place',choices=('office','remote'),default='remote')
    edit=sub.add_parser('correct'); edit.add_argument('id',type=int); edit.add_argument('--start'); edit.add_argument('--end')
    a=p.parse_args(); bootfile=Path('/proc/sys/kernel/random/boot_id'); boot=bootfile.read_text().strip() if bootfile.exists() else 'manual-mode'
    t=Tracker(a.data_dir,boot)
    if a.command=='daemon':
        if not sys.platform.startswith('linux'): p.error('Automatic tracking currently requires Linux; use start/stop for manual tracking.')
        daemon(t)
    elif a.command in ('start','stop'): send_command(t,'start-office' if a.command=='start' and a.place=='office' else a.command)
    elif a.command=='status':
        row=t.opened()
        print('Pågående pass sedan '+stamp(row[1]) if row else 'Inget pågående arbetspass.')
        if row: print('Plats: '+('Hemifrån' if t.remote() else 'Kontor'))
        progress=daily_progress(t.rows(),time.time())
        if row and progress: print('Planerad sluttid: '+datetime.fromtimestamp(progress['target'],TZ).strftime('%H:%M')+f' ({TARGET_HOURS} timmars arbete)')
        print('Senaste avläsning: '+stamp(t.s.get('last_seen')))
        print('Logg: '+str(t.directory/'logg.sqlite3'))
    elif a.command in ('report','export'): report(t,a.command=='export')
    elif a.command=='calendar':
        t.refresh_calendar(); print(t.directory/'arbetstid.ics')
    elif a.command=='correct':
        if not a.start and not a.end: p.error('Ange --start och/eller --end, exempel: "2026-10-15T08:00"')
        t.db.execute('BEGIN IMMEDIATE')
        row=t.db.execute('SELECT start,end FROM passes WHERE id=?',(a.id,)).fetchone()
        if not row: p.error('Passet finns inte.')
        if row[1] is None: p.error('Rätta avslutade pass; stoppa först tjänsten om passet pågår.')
        start=parse_date(a.start) if a.start else row[0]; end=parse_date(a.end) if a.end else row[1]
        if end<start: p.error('Hemgång måste vara efter ankomst.')
        overlap=t.db.execute('SELECT id FROM passes WHERE id!=? AND start<? AND (end IS NULL OR end>?)',(a.id,end,start)).fetchone()
        if overlap: p.error('Tiden överlappar ett annat pass.')
        t.db.execute('INSERT INTO edits(at,pass_id,old,new) VALUES(?,?,?,?)',(time.time(),a.id,json.dumps(row),json.dumps([start,end])))
        t.db.execute('UPDATE passes SET start=?,end=?,uncertain=0,reason=? WHERE id=?',(start,end,'Manuellt korrigerad',a.id)); t.db.commit()
        t.refresh_calendar()
        print('Passet är korrigerat. Ändringen har sparats i historiken.')
if __name__=='__main__': main()
