import cStringIO
import hashlib
import json
import os
import urllib2
import zipfile
from symFileManager import SymFileManager
from symbolicationRequest import SymbolicationRequest
from logging import LogTrace, LogError, LogMessage, SetTracingEnabled


class ProfileSymbolicator:
  def __init__(self, options):
    self.options = options
    self.sym_file_manager = SymFileManager(self.options)

  def integrate_symbol_zip_from_url(self, symbol_zip_url):
    if self.have_integrated(symbol_zip_url):
      return
    LogMessage("Retrieving symbol zip from {symbol_zip_url}...".format(symbol_zip_url=symbol_zip_url))
    io = urllib2.urlopen(symbol_zip_url, None, 30)
    sio = cStringIO.StringIO(io.read())
    zf = zipfile.ZipFile(sio)
    io.close()
    self.integrate_symbol_zip(zf)
    zf.close()
    self._create_file_if_not_exists(self._marker_file(symbol_zip_url))

  def _create_file_if_not_exists(self, filename):
    try:
      os.makedirs(os.path.dirname(filename))
    except OSError:
      pass
    try:
      open(filename, 'a').close()
    except IOError:
      pass

  def integrate_symbol_zip(self, symbol_zip_file):
    symbol_zip_file.extractall(self.options["symbolPaths"]["FIREFOX"])

  def _marker_file(self, symbol_zip_url):
    marker_dir = os.path.join(self.options["symbolPaths"]["FIREFOX"], ".markers")
    return os.path.join(marker_dir, hashlib.sha1(symbol_zip_url).hexdigest())

  def have_integrated(self, symbol_zip_url):
    return os.path.isfile(self._marker_file(symbol_zip_url))

  def symbolicate_profile(self, profile_json):
    if "libs" not in profile_json:
      return
    shared_libraries = json.loads(profile_json["libs"])
    shared_libraries.sort(key=lambda lib: lib["start"])
    addresses = self._find_addresses(profile_json)
    symbols_to_resolve = self._assign_symbols_to_libraries(addresses, shared_libraries)
    symbolication_table = self._resolve_symbols(symbols_to_resolve)
    self._substitute_symbols(profile_json, symbolication_table)

  def _find_addresses(self, profile_json):
    addresses = set()
    for thread in profile_json["threads"]:
      for sample in thread["samples"]:
        for frame in sample["frames"]:
          if frame["location"][0:2] == "0x":
            addresses.add(frame["location"])
          if "lr" in frame and frame["lr"][0:2] == "0x":
            address.add(frame["lr"])
    return addresses

  def _get_containing_library(self, address, libs):
    left = 0
    right = len(libs) - 1
    while left <= right:
      mid = (left + right) / 2
      if address >= libs[mid]["end"]:
        left = mid + 1
      elif address < libs[mid]["start"]:
        right = mid - 1
      else:
        return libs[mid]
    return None

  def _assign_symbols_to_libraries(self, addresses, shared_libraries):
    libs_with_symbols = {}
    for address in addresses:
      lib = self._get_containing_library(int(address, 0), shared_libraries)
      if not lib:
        continue
      if lib["start"] not in libs_with_symbols:
        libs_with_symbols[lib["start"]] = { "library": lib, "symbols": set() }
      libs_with_symbols[lib["start"]]["symbols"].add(address)
    return libs_with_symbols.values()

  def _module_from_lib(self, lib):
    if "breakpadId" in lib:
      return [lib["name"].split("/")[-1], lib["breakpadId"]]
    pdbSig = re.sub("[{}\-]", "", lib["pdbSignature"])
    return [lib["pdbName"], pdbSig + lib["pdbAge"]]

  def _resolve_symbols(self, symbols_to_resolve):
    memoryMap = []
    processedStack = []
    all_symbols = []
    for moduleIndex, library_with_symbols in enumerate(symbols_to_resolve):
      lib = library_with_symbols["library"]
      symbols = library_with_symbols["symbols"]
      memoryMap.append(self._module_from_lib(lib))
      all_symbols += symbols
      for symbol in symbols:
        processedStack.append([moduleIndex, int(symbol, 0) - lib["start"]])

    rawRequest = { "stacks": [processedStack], "memoryMap": memoryMap, "version": 3, "osName": "Windows", "appName": "Firefox" }
    request = SymbolicationRequest(self.sym_file_manager, rawRequest)
    if not request.isValidRequest:
      return {}
    symbolicated_stack = request.Symbolicate(0)
    return dict(zip(all_symbols, symbolicated_stack))

  def _substitute_symbols(self, profile_json, symbolication_table):
    for thread in profile_json["threads"]:
      for sample in thread["samples"]:
        for frame in sample["frames"]:
          frame["location"] = symbolication_table.get(frame["location"], frame["location"])
