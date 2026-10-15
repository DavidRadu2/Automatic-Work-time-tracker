#!/usr/bin/python3
"""Registrera arbetstid.ics som separat lokal, skrivskyddad KOrganizer-kalender."""
import os, time, sqlite3, subprocess
from pathlib import Path
import dbus
from settings import DATA_DIR

def register(directory):
    path=(Path(directory)/'arbetstid.ics').resolve()
    if not path.exists(): raise SystemExit('Kalenderfilen saknas. Starta arbetstidstjänsten först.')
    bus=dbus.SessionBus()
    manager=dbus.Interface(bus.get_object('org.freedesktop.Akonadi.Control','/AgentManager'),'org.freedesktop.Akonadi.AgentManager')
    ident=None
    for candidate in manager.agentInstances():
        if manager.agentInstanceType(candidate)!='akonadi_ical_resource': continue
        try:
            settings=dbus.Interface(bus.get_object('org.freedesktop.Akonadi.Agent.'+str(candidate),'/Settings'),'org.kde.Akonadi.ICal.Settings')
            if str(settings.path()) in (str(path),path.as_uri()): ident=str(candidate); break
        except dbus.DBusException: continue
    if ident is None: ident=str(manager.createAgentInstance('akonadi_ical_resource'))
    for attempt in range(30):
        try:
            settings=dbus.Interface(bus.get_object('org.freedesktop.Akonadi.Agent.'+ident,'/Settings'),'org.kde.Akonadi.ICal.Settings')
            settings.path(); break
        except dbus.DBusException:
            if attempt==29: raise
            time.sleep(.2)
    settings.setPath(str(path)); settings.setDisplayName('Arbetstid')
    settings.setReadOnly(True); settings.setMonitorFile(True)
    settings.setPeriodicUpdate(True); settings.setUpdatePeriod(1); settings.save()
    control=dbus.Interface(bus.get_object('org.freedesktop.Akonadi.Agent.'+ident,'/'),'org.freedesktop.Akonadi.Agent.Control')
    control.reconfigure()
    manager.setAgentInstanceName(ident,'Arbetstid'); manager.setAgentInstanceOnline(ident,True)
    manager.agentInstanceSynchronize(ident)
    (Path(directory)/'calendar-resource.txt').write_text(ident+'\n')
    # Read collection ID through Akonadi's local SQLite cache, never modify it.
    dbpath=Path.home()/'.local/share/akonadi/akonadi.db'
    ids=[]
    if dbpath.exists():
        for _ in range(30):
            c=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)
            ids=[r[0] for r in c.execute('SELECT c.id FROM CollectionTable c JOIN ResourceTable r ON c.resourceId=r.id WHERE r.name=?',(ident,))]
            c.close()
            if ids: break
            time.sleep(.2)
    running=any('korganizer' in str(name).lower() for name in bus.list_names())
    if ids and not running:
        old=subprocess.run(['kreadconfig6','--file','korganizerrc','--group','GlobalCollectionSelection','--key','Selection'],capture_output=True,text=True,check=True).stdout.strip()
        selected=[s for s in old.split(',') if s]
        for n in ids:
            if 'c'+str(n) not in selected: selected.append('c'+str(n))
        subprocess.run(['kwriteconfig6','--file','korganizerrc','--group','GlobalCollectionSelection','--key','Selection',','.join(selected)],check=True)
    print('Kalender registrerad:',ident,'Arbetstid')
    print('Fil:',path)
    print('Skrivskyddad:',bool(settings.readOnly()),'Bevakar fil:',bool(settings.monitorFile()))
    if running: print('Markera Arbetstid i KOrganizers kalenderlista om den inte redan visas.')
    return ident

if __name__=='__main__':
    os.umask(0o077)
    register(DATA_DIR)
