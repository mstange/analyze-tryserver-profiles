
import os
import symbolication
import urllib2
import cStringIO
import zipfile
from symFileManager import SymFileManager
from symbolicationRequest import SymbolicationRequest
from bs4 import BeautifulSoup
import re
import json

crashreportID = '80b5e83c-bb2b-4f85-b44a-400ad0190830'
inputsample = open('/Users/mozilla/Downloads/.txt', 'r')

def get_raw_dump(reportID):
  url = 'https://crash-stats.mozilla.com/report/index/' + reportID
  page = urllib2.urlopen(url)
  soup = BeautifulSoup(page, 'html.parser')
  return json.loads(soup.select_one('#rawdump > .code').string)

gSymbolicationOptions = {
  # Trace-level logging (verbose)
  "enableTracing": 0,
  # Fallback server if symbol is not found locally
  "remoteSymbolServer": "http://symbolapi.mozilla.org:80/",
  # Maximum number of symbol files to keep in memory
  "maxCacheEntries": 2000000,
  # Frequency of checking for recent symbols to cache (in hours)
  "prefetchInterval": 12,
  # Oldest file age to prefetch (in hours)
  "prefetchThreshold": 48,
  # Maximum number of library versions to pre-fetch per library
  "prefetchMaxSymbolsPerLib": 3,
  # Default symbol lookup directories
  "defaultApp": "FIREFOX",
  "defaultOs": "WINDOWS",
  # Paths to .SYM files, expressed internally as a mapping of app or platform names
  # to directories
  # Note: App & OS names from requests are converted to all-uppercase internally
  "symbolPaths": {
    # Location of Firefox library symbols
    "FIREFOX": os.path.join(os.getcwd(), "symbols_ffx"),
    # Location of Thunderbird library symbols
    "THUNDERBIRD": os.path.join(os.getcwd(), "symbols_tbrd"),
    # Location of Windows library symbols
    "WINDOWS": os.path.join(os.getcwd(), "symbols_os")
  }
}

symbolicator = symbolication.ProfileSymbolicator(gSymbolicationOptions)

reLibraryListLine = re.compile(r"^\s*\*?(?P<load_address>0x[0-9a-f]+)\s*\-\s*(?P<end_address>0x[0-9a-f]+)\s+\+?(?P<lib_longname>\b.*)\s+\<(?P<lib_id>[0-9a-fA-F\-]+)>\s+(?P<lib_path>.*)$", re.DOTALL)
reStackLine1 = re.compile(r"^(?P<before_symbol>.*)\?\?\?.*load address (?P<load_address>0x[0-9a-f]+) \+ (?P<relative_frame_address>0x[0-9a-f]+)\s.*\[(?P<absolute_frame_address>0x[0-9a-f]+)\].*$", re.DOTALL)
reStackLine2 = re.compile(r"^(?P<before_symbol>.*)\?\?\? \((?P<lib_name>.*) \+ (?P<relative_frame_address>[0-9]+)\)\s.*\[(?P<absolute_frame_address>0x[0-9a-f]+)\].*$", re.DOTALL)
reStackLine3 = re.compile(r"^(?P<before_symbol>.*[0-9]+ )(?P<original_symbol>.*) \(in (?P<lib_name>.*)\) \+ (?P<relative_frame_address>[0-9]+)\s.*\[(?P<absolute_frame_address>0x[0-9a-f]+)\].*$", re.DOTALL)

def convert_libid(lib_id):
  return lib_id.replace("-", "") + "0"

def parse_module_list(inputsample):
  modules = {}

  found_lib_list = False
  while True:
    line = inputsample.readline()
    if not line:
      break
    match = reLibraryListLine.match(line)
    if match:
      found_lib_list = True
      lib_name = os.path.basename(match.group("lib_path").strip())
      if " " in lib_name:
        continue
      breakpadID = convert_libid(match.group("lib_id"))
      modules[lib_name] = {
        'debugName': lib_name,
        'breakpadId': breakpadID,
        'path': match.group("lib_path").strip(),
        'debugPath': match.group("lib_path").strip(),
        'arch': 'x86_64'
      }
    elif found_lib_list:
      break
  return modules

local_modules = parse_module_list(inputsample)
local_modules['AMDRadeonX4000GLDriver'] = {
  'debugName': 'AMDRadeonX4000GLDriver',
  'breakpadId': '62E5A997DD6937BFB6192B117EF4E39D0',
  'path': '/System/Library/Extensions/AMDRadeonX4000GLDriver.bundle/Contents/MacOS/AMDRadeonX4000GLDriver',
  'debugPath': '/System/Library/Extensions/AMDRadeonX4000GLDriver.bundle/Contents/MacOS/AMDRadeonX4000GLDriver',
  'arch': 'x86_64h'
}
inputsample.close()

raw_dump = get_raw_dump(crashreportID)

modules_for_symbolication = []
module_name_to_index = {}

for module in raw_dump['modules']:
  if module.get('missing_symbols', False):
    debugName = module['debug_file']
    breakpadID = module['debug_id']
    local_module = local_modules.get(debugName)
    if local_module is None:
      continue
    if local_module['breakpadId'] == breakpadID:
      print debugName + ' is stored at ' + local_module['path']
    else:
      print 'I do not have a local version of ' + debugName
      print 'assuming it matches my local binary, and overwriting.'
      breakpadID = local_module['breakpadId']
      module['debug_id'] = local_module['breakpadId']
    symbolicator.dump_symbols_for_lib(local_module, gSymbolicationOptions["symbolPaths"]["FIREFOX"])
    module_index = len(modules_for_symbolication)
    modules_for_symbolication.append([debugName, breakpadID])
    module_name_to_index[debugName] = module_index

# print modules_for_symbolication

stack = []

for thread in raw_dump['threads']:
  for frame in thread['frames']:
    module_name = frame.get('module')
    if module_name is not None and module_name_to_index.get(module_name) is not None:
      stack.append([module_name_to_index.get(module_name), int(frame['module_offset'], 0)])

# print stack

rawRequest = { "stacks": [stack], "memoryMap": modules_for_symbolication, "version": 4, "symbolSources": ["firefox"] }
request = SymbolicationRequest(symbolicator.sym_file_manager, rawRequest)
symbolicated_stack = request.Symbolicate(0)

# print symbolicated_stack

i = 0

for thread in raw_dump['threads']:
  for frame in thread['frames']:
    module_name = frame.get('module')
    if module_name is not None and module_name_to_index.get(module_name) is not None:
      frame['normalized'] = symbolicated_stack[i]
      i += 1

for threadIndex, thread in enumerate(raw_dump['threads']):
  print 'Thread #%d' % threadIndex
  for frameIndex, frame in enumerate(thread['frames']):
    print '#%d %s' % (frameIndex, frame.get('normalized', frame.get('function', frame.get('module_offset', '<Unknown>'))))
  print ''

exit()
