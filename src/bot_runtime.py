"""Single-engine process ownership and continuous, bounded log collection."""
import fcntl
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import threading
from collections import deque


class InstanceLock:
    """Kernel lock survives stale PID files and is released on process death."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('A trading engine is already running') from None
        self.file.seek(0)
        self.file.truncate()
        self.file.write(str(os.getpid()))
        self.file.flush()

    def close(self):
        # Do not unlink the inode: another process may already have it open.
        self.file.close()


class BotRuntime:
    def __init__(self, log_dir):
        self.log_dir = Path(log_dir)
        self.processes = {}
        self.logs = {}
        self.lock = threading.RLock()
        self.readers = {}

    def alive(self, strategy):
        process = self.processes.get(strategy)
        return process is not None and process.poll() is None

    def start(self, strategy, script, env):
        with self.lock:
            if any(self.alive(sid) for sid in self.processes):
                raise RuntimeError('One engine is already running; stop it before changing strategy')
            for reader in self.readers.values():
                reader.join(timeout=2)
            self.processes.clear()
            self.logs = {strategy: deque(maxlen=200)}
            self.log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(self.log_dir / 'bot-process.log',
                                          maxBytes=5_000_000, backupCount=3)
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            try:
                process = subprocess.Popen(
                    [sys.executable, '-u', str(Path(script).resolve())],
                    cwd=str(Path(script).resolve().parent),
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
            except Exception:
                handler.close()
                raise
            self.processes[strategy] = process
            reader = threading.Thread(target=self._collect,
                                      args=(strategy, process, handler), daemon=True)
            self.readers[strategy] = reader
            reader.start()
            return process

    def _collect(self, strategy, process, handler):
        try:
            with process.stdout:
                for raw in iter(lambda: process.stdout.readline(4096), b''):
                    line = raw.decode(errors='replace').rstrip()
                    self.logs[strategy].append(line)
                    handler.emit(logging.LogRecord('bot', logging.INFO, '', 0, line, (), None))
        finally:
            handler.close()

    def stop(self, strategy=None):
        with self.lock:
            if strategy is not None and strategy not in self.processes:
                raise KeyError(strategy)
            targets = [strategy] if strategy else list(self.processes)
            for sid in targets:
                process = self.processes[sid]
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                self.readers[sid].join(timeout=2)
                self.processes.pop(sid)
            return targets
