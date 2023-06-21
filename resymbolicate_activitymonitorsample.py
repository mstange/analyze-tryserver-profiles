
import os
import symbolication
import urllib2
import cStringIO
import zipfile
from symFileManager import SymFileManager
from symbolicationRequest import SymbolicationRequest
import re

inputsample = open('/Users/mstange/Downloads/metal-linking-crash-1010.txt', 'r')
outputsample = open('/Users/mstange/Downloads/metal-linking-symbolicated.txt', 'w')

gSymbolicationOptions = {
  # Trace-level logging (verbose)
  "enableTracing": 0,
  # Fallback server if symbol is not found locally
  "remoteSymbolServer": "https://symbolication.services.mozilla.com/symbolicate/v4",
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

reLibraryListLine1 = re.compile(r"^\s*\*?(?P<load_address>0x[0-9a-f]+)\s*\-\s*(?P<end_address>0x[0-9a-f]+)\s+\+?(?P<lib_longname>\b[^\(\))]+)(?P<lib_versioninfo>\s\(.*\))?\s+\<(?P<lib_id>[0-9a-fA-F\-]+)>\s+(?P<lib_path>.*)$", re.DOTALL)
reLibraryListLine2 = re.compile(r"^\s*\*?(?P<load_address>0x[0-9a-f]+)\s*\-\s*\?\?\?\s+\?\?\?\s+\<(?P<lib_id>[0-9a-fA-F\-]+)>", re.DOTALL)
reStackLines = [
  re.compile(r"^(?P<before_symbol>.*)\?\?\?.*load address (?P<load_address>0x[0-9a-f]+) \+ (?P<relative_frame_address>0x[0-9a-f]+)\s.*\[(?P<absolute_frame_address>0x[0-9a-f]+)\]", re.DOTALL),
  re.compile(r"^(?P<before_symbol>.*)\?\?\? \((?P<lib_name>.*) \+ (?P<relative_frame_address>[0-9]+)\)\s.*\[(?P<absolute_frame_address>0x[0-9a-f]+)\]", re.DOTALL),
  re.compile(r"^(?P<before_symbol>.*[0-9]+ )(?P<original_symbol>.*) \(in (?P<lib_name>.*)\) \+ (?P<relative_frame_address>[0-9]+)\s.*\[(?P<absolute_frame_address>0x[0-9a-f]+)\]", re.DOTALL),
  re.compile(r"^(?P<before_symbol>[0-9]+\s+(?P<lib_name>\S+)\s+(?P<absolute_frame_address>0x[0-9a-f]+) )(?P<original_symbol>.*) \+ (?P<function_offset>[0-9]+)", re.DOTALL)
]

# Examples:
# ":    +                   !         : |   + !                             :     | +   : | + 1 ???  (in Activity Monitor)  load address 0x1011b6000 + 0x3987f  [0x1011ef87f]"
# "     +                   !       :   |     1 -[NSTableView _tileAndRedisplayAll]  (in AppKit) + 231  [0x7fffc2c2ef7a]"
# "4   XUL                                   0x00000001148f2af4 XRE_GetBootstrap + 3738372"

def convert_libid(lib_id):
  return lib_id.replace("-", "") + "0"

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
    match = reLibraryListLine1.match(line)
    if match:
      found_lib_list = True
      module_index = len(modules)
      load_address = match.group("load_address")
      lib_name = os.path.basename(match.group("lib_path").strip())
      if " " in lib_name:
        continue
      load_address_to_module_index[load_address] = module_index
      lib_name_to_module_index[lib_name] = module_index
      if match.group("lib_longname") != lib_name:
        lib_name_to_module_index[match.group("lib_longname")] = module_index
        print "long name:", match.group("lib_longname")
      modules.append([lib_name, convert_libid(match.group("lib_id"))])
      load_addresses.append(load_address)
    else:
      match = reLibraryListLine2.match(line)
      if match:
        found_lib_list = True
        module_index = len(modules)
        load_address = match.group("load_address")
        lib_id = match.group("lib_id")
        lib_name_to_module_index["<" + lib_id + ">"] = module_index
        modules.append(["XUL", convert_libid(lib_id)])
        load_addresses.append(load_address)

    if found_lib_list and not match:
      break

  input_end = inputsample.tell()
  inputsample.seek(input_start)

  # print modules

  def get_normalized_match(line):
    for reStackLine in reStackLines:
      match = reStackLine.match(line)
      if match is None:
        continue
      d = match.groupdict()
      if "load_address" in d and d["load_address"] in load_address_to_module_index:
        module_index = load_address_to_module_index[d["load_address"]]
      elif "lib_name" in d and d["lib_name"] in lib_name_to_module_index:
        module_index = lib_name_to_module_index[d["lib_name"]]
      else:
        if "lib_name" in d:
          print "Couldn't find lib name", d["lib_name"]
        continue
      if "absolute_frame_address" in d:
        absolute_frame_address = int(d["absolute_frame_address"], 0)
        relative_frame_address = absolute_frame_address - int(load_addresses[module_index], 0)
      elif "relative_frame_address" in d:
        relative_frame_address = int(d["relative_frame_address"], 0)
        absolute_frame_address = int(load_addresses[module_index], 0) + relative_frame_address
      else:
        continue
      return {
        "before_symbol": d["before_symbol"],
        "module_index": module_index,
        "relative_frame_address": relative_frame_address,
        "absolute_frame_address": absolute_frame_address,
      }
    return None

  while inputsample.tell() < input_end:
    line = inputsample.readline()
    if not line:
      break
    m = get_normalized_match(line)
    if m:
      stack.append([m["module_index"], m["relative_frame_address"]])
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
    m = get_normalized_match(line)
    if m:
      if symbolicated_stack[i][0:2] != "0x":
        outputsample.write(m["before_symbol"] + symbolicated_stack[i] + " [%s]\n" % m["absolute_frame_address"])
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
