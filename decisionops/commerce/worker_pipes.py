"""Concurrent byte-capped pipe consumption; Linux/POSIX operator subprocesses."""
from dataclasses import dataclass
import os
import selectors
import subprocess
import time

STDOUT_LIMIT=65536
STDERR_LIMIT=65536
DIAGNOSTIC_LIMIT=1024


@dataclass
class CapturedOutput:
    outcome: str
    buffers: dict
    consumed: dict
    overflow_stream: str | None=None

    def diagnostics(self):
        return {'stream_limits_bytes':{'stdout':STDOUT_LIMIT,'stderr':STDERR_LIMIT},
                'stream_bytes_consumed':self.consumed,
                'stream_bytes_retained':{name:len(data) for name,data in self.buffers.items()},
                'stream_diagnostics':{name:bytes(data[:DIAGNOSTIC_LIMIT]).decode('utf-8',errors='replace') for name,data in self.buffers.items()},
                'overflow_stream':self.overflow_stream}


def consume(process,payload,deadline):
    """Read at most cap+1 bytes per stream; retain at most cap, never communicate().

    stdout, stderr and stdin are multiplexed, so a blocked writer cannot prevent
    the other pipe or the deadline from being serviced. Caller owns group cleanup.
    """
    limits={'stdout':STDOUT_LIMIT,'stderr':STDERR_LIMIT}
    buffers={name:bytearray() for name in limits};consumed={name:0 for name in limits}
    outcome='complete';overflow=None;pending=memoryview(payload)
    if len(payload)>32768:raise ValueError('Worker input exceeds protocol bound')
    with selectors.DefaultSelector() as selector:
        for name in limits:
            pipe=getattr(process,name);os.set_blocking(pipe.fileno(),False)
            selector.register(pipe,selectors.EVENT_READ,name)
        os.set_blocking(process.stdin.fileno(),False)
        selector.register(process.stdin,selectors.EVENT_WRITE,'stdin')
        while selector.get_map():
            remaining=deadline-time.monotonic()
            if remaining<=0:outcome='timeout';break
            for key,_ in selector.select(timeout=min(remaining,.1)):
                pipe=key.fileobj;name=key.data
                if name=='stdin':
                    try:written=os.write(pipe.fileno(),pending[:4096]);pending=pending[written:]
                    except BrokenPipeError:pending=memoryview(b'')
                    except BlockingIOError:continue
                    if not pending:selector.unregister(pipe);pipe.close()
                    continue
                # Reading the single overflow byte proves the bound is enforced
                # during consumption. Never read a whole oversized producer chunk.
                available=limits[name]-consumed[name]
                try:chunk=os.read(pipe.fileno(),min(4096,available+1))
                except BlockingIOError:continue
                if not chunk:selector.unregister(pipe);continue
                consumed[name]+=len(chunk)
                buffers[name].extend(chunk[:available])
                if consumed[name]>limits[name]:
                    outcome='overflow';overflow=name;break
            if outcome=='overflow':break
        if outcome=='complete':
            # A child can close its pipes and still keep running.
            remaining=deadline-time.monotonic()
            if remaining<=0:outcome='timeout'
            else:
                try:process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:outcome='timeout'
    return CapturedOutput(outcome,buffers,consumed,overflow)
