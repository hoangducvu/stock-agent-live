"""Restartable research process lifecycle, independent of trading engine ownership."""
import os
from pathlib import Path
import subprocess
import sys
import threading
class ResearchSupervisor:
    def __init__(self):self.process=None;self.thread=None;self.stopped=threading.Event()
    def start(self):
        if os.getenv('NEXLARA_WORKER_ENABLED')!='true' or os.getenv('NEXLARA_REQUIRE_TEST_DEPS')=='1':return
        self.stopped.clear()
        self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()
    def monitor(self):
        while not self.stopped.is_set():
            if self.process is None or self.process.poll() is not None:
                try:self.process=subprocess.Popen([sys.executable,'-m','research.worker'],cwd=str(Path(__file__).resolve().parents[1]),env=os.environ.copy())
                except OSError:pass
            self.stopped.wait(5)
    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=6)
        if self.process is None or self.process.poll() is not None:return
        self.process.terminate()
        try:self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
