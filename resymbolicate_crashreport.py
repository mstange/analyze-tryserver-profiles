
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

crashreportID = '9433e825-9497-4255-af10-f5b852161215'
inputsample = open('/Users/mstange/Downloads/nightlysample.txt', 'r')

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
        'pdbName': lib_name,
        'breakpadID': breakpadID,
        'path': match.group("lib_path").strip()
      }
    elif found_lib_list:
      break
  return modules

local_modules = parse_module_list(inputsample)
inputsample.close()

raw_dump = get_raw_dump(crashreportID)

symbol_dumper = symbolication.get_symbol_dumper()

modules_for_symbolication = []
module_name_to_index = {}

for module in raw_dump['modules']:
  if module.get('missing_symbols', False):
    pdbName = module['debug_file']
    breakpadID = module['debug_id']
    local_module = local_modules.get(pdbName)
    if local_module is None:
      continue
    if local_module['breakpadID'] == breakpadID:
      print pdbName + ' is stored at ' + local_module['path']
      symbolication.dump_symbols_for_lib(pdbName, breakpadID, local_module['path'], gSymbolicationOptions["symbolPaths"]["FIREFOX"], symbol_dumper)
    else:
      print 'I do not have a local version of ' + pdbName
      print 'assuming it matches my local binary, and overwriting.'
      breakpadID = local_module['breakpadID']
      module['debug_id'] = local_module['breakpadID']
      symbolication.dump_symbols_for_lib(pdbName, breakpadID, local_module['path'], gSymbolicationOptions["symbolPaths"]["FIREFOX"], symbol_dumper)
    module_index = len(modules_for_symbolication)
    modules_for_symbolication.append([pdbName, breakpadID])
    module_name_to_index[pdbName] = module_index

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

def process_one_process():
  input_start = inputsample.tell()
  input_end = -1

  modules = []
  load_addresses = []
  stack = []
  load_address_to_module_index = {}
  lib_name_to_module_index = {}

  found_lib_list = False
  while True:
    line = inputsample.readline()
    if not line:
      break
    match = reLibraryListLine.match(line)
    if match:
      found_lib_list = True
      module_index = len(modules)
      load_address = match.group("load_address")
      lib_name = os.path.basename(match.group("lib_path").strip())
      if " " in lib_name:
        continue
      load_address_to_module_index[load_address] = module_index
      lib_name_to_module_index[lib_name] = module_index
      modules.append([lib_name, convert_libid(match.group("lib_id"))])
      load_addresses.append(load_address)
    elif found_lib_list:
      break

  input_end = inputsample.tell()
  inputsample.seek(input_start)

  # print modules

  while inputsample.tell() < input_end:
    line = inputsample.readline()
    if not line:
      break
    match = reStackLine1.match(line)
    if match and match.group("load_address") in load_address_to_module_index:
      module_index = load_address_to_module_index[match.group("load_address")]
      stack.append([module_index, int(match.group("relative_frame_address"), 0)])
      continue
    match = reStackLine2.match(line)
    if match and match.group("lib_name") in lib_name_to_module_index:
      module_index = lib_name_to_module_index[match.group("lib_name")]
      relative_frame_address = int(match.group("absolute_frame_address"), 0) - int(load_addresses[module_index], 0)
      stack.append([module_index, relative_frame_address])
      continue
    match = reStackLine3.match(line)
    if match and match.group("lib_name") in lib_name_to_module_index:
      module_index = lib_name_to_module_index[match.group("lib_name")]
      relative_frame_address = int(match.group("absolute_frame_address"), 0) - int(load_addresses[module_index], 0)
      stack.append([module_index, relative_frame_address])
      continue
  inputsample.seek(input_start)

  # print stack
  # print modules

  rawRequest = { "stacks": [stack], "memoryMap": modules, "version": 4, "symbolSources": ["firefox"] }
  request = SymbolicationRequest(symbolicator.sym_file_manager, rawRequest)
  symbolicated_stack = request.Symbolicate(0)

  i = 0
  while inputsample.tell() < input_end:
    line = inputsample.readline()
    if not line:
      break
    match = reStackLine1.match(line)
    if match and match.group("load_address") in load_address_to_module_index:
      outputsample.write(match.group("before_symbol") + symbolicated_stack[i] + " [%s]\n" % match.group("absolute_frame_address"))
      i = i + 1
      continue
    match = reStackLine2.match(line)
    if match and match.group("lib_name") in lib_name_to_module_index:
      outputsample.write(match.group("before_symbol") + symbolicated_stack[i] + " [%s]\n" % match.group("absolute_frame_address"))
      i = i + 1
      continue
    match = reStackLine3.match(line)
    if match and match.group("lib_name") in lib_name_to_module_index:
      if symbolicated_stack[i][0:2] != "0x":
        outputsample.write(match.group("before_symbol") + symbolicated_stack[i] + " [%s]\n" % match.group("absolute_frame_address"))
      else:
        outputsample.write(line)
      i = i + 1
      continue
    outputsample.write(line)

  inputsample.seek(input_end)
  return found_lib_list

while process_one_process():
  pass

inputsample.close()
outputsample.close()
