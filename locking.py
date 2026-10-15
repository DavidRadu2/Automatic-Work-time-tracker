"""Small cross-platform advisory file lock for this local single-user tracker."""
import os

class FileLock:
    def __init__(self,path):
        self.file=open(path,'a+b')
        self.locked=False
    def acquire(self):
        if os.name=='nt':
            import msvcrt
            self.file.seek(0,2)
            if self.file.tell()==0: self.file.write(b'0'); self.file.flush()
            self.file.seek(0)
            try: msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc: raise BlockingIOError('Tracker lock is in use') from exc
        else:
            import fcntl
            fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.locked=True
        return self
    def close(self):
        if self.locked and os.name=='nt':
            import msvcrt
            self.file.seek(0); msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        self.file.close(); self.locked=False
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
