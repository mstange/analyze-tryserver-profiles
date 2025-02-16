import sys
import threading
import time

gEnableTracing = False

def SetTracingEnabled(isEnabled):
  global gEnableTracing
  gEnableTracing = isEnabled

def LogTrace(string):
  global gEnableTracing
  if gEnableTracing:
    threadName = threading.current_thread().name.ljust(12)
    print(time.asctime() + " " + threadName + " TRACE " + string, file=sys.stdout)

def LogError(string):
  threadName = threading.current_thread().name + " "
  print(time.asctime() + " " + threadName + "ERROR " + string, file=sys.stderr)

def LogMessage(string):
  threadName = threading.current_thread().name.ljust(12)
  print(time.asctime() + " " + threadName + "       " + string, file=sys.stdout)
