# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import cStringIO
import hashlib
import json
import os
import platform
import re
import subprocess
import urllib2
import zipfile
from distutils import spawn
from symFileManager import SymFileManager
from symbolicationRequest import SymbolicationRequest
from symLogging import LogMessage

def dump_symbols_for_lib(pdbName, breakpadId, path, output_dir, symbol_dumper):
  if not os.path.exists(path):
    return None
  output_filename_without_extension = os.path.join(output_dir, pdbName, breakpadId, pdbName)
  output_dir = os.path.dirname(output_filename_without_extension)
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)
  return symbol_dumper.store_symbols(path, breakpadId, output_filename_without_extension)

def get_symbol_dumper():
  try:
    if platform.system() == "Darwin":
      return OSXSymbolDumper()
  except:
    pass
  try:
    if platform.system() == "Linux":
      return LinuxSymbolDumper()
  except:
    pass
  return None

class OSXSymbolDumper:
  def __init__(self):
    self.dump_syms_bin = os.path.join(os.path.dirname(__file__), 'dump_syms_mac')
    if not os.path.exists(self.dump_syms_bin):
      raise Exception("No dump_syms_mac binary in this directory")

  def store_symbols(self, lib_path, expected_breakpad_id, output_filename_without_extension):
    """
    Returns the filename at which the .sym file was created, or None if no
    symbols were dumped.
    """
    output_filename = output_filename_without_extension + ".sym"

    def get_archs(filename):
      """
      Find the list of architectures present in a Mach-O file.
      """
      return subprocess.Popen(["lipo", "-info", filename], stdout=subprocess.PIPE).communicate()[0].split(':')[2].strip().split()

    def process_file(arch):
      proc = subprocess.Popen([self.dump_syms_bin, "-a", arch, lib_path],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
      stdout, stderr = proc.communicate()
      if proc.returncode != 0:
        return None

      module = stdout.splitlines()[0]
      bits = module.split(' ', 4)
      if len(bits) != 5:
        return None
      _, platform, cpu_arch, actual_breakpad_id, debug_file = bits

      if actual_breakpad_id != expected_breakpad_id:
        return None

      f = open(output_filename, "w")
      f.write(stdout)
      f.close()
      return output_filename

    for arch in get_archs(lib_path):
      result = process_file(arch)
      if result is not None:
        return result
    return None

class LinuxSymbolDumper:
  def __init__(self):
    self.nm = spawn.find_executable("nm")
    if not self.nm:
      raise Exception("Could not find nm, necessary for symbol dumping")

  def store_symbols(self, lib_path, breakpad_id, output_filename_without_extension):
    """
    Returns the filename at which the .sym file was created, or None if no
    symbols were dumped.
    """
    output_filename = output_filename_without_extension + ".nmsym"

    proc = subprocess.Popen([self.nm, "--demangle", lib_path],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()

    if proc.returncode != 0:
      return

    f = open(output_filename, "w")
    f.write(stdout)

    # Append nm -D output to the file. On Linux, most system libraries have no
    # "normal" symbols, but they have "dynamic" symbols, which nm -D shows.
    proc = subprocess.Popen([self.nm, "--demangle", "-D", lib_path],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode == 0:
      f.write(stdout)
    f.close()
    return output_filename

class ProfileSymbolicator:
  def __init__(self, options):
    self.options = options
    self.sym_file_manager = SymFileManager(self.options)
    self.symbol_dumper = get_symbol_dumper()

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

  def integrate_symbol_zip_from_file(self, filename):
    if self.have_integrated(filename):
      return
    f = open(filename, 'rb')
    zf = zipfile.ZipFile(f)
    self.integrate_symbol_zip(zf)
    f.close()
    zf.close()
    self._create_file_if_not_exists(self._marker_file(filename))

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

  def get_unknown_modules_in_profile(self, profile_json):
    if "libs" not in profile_json:
      return []
    shared_libraries = json.loads(profile_json["libs"])
    memoryMap = []
    for lib in shared_libraries:
      memoryMap.append(self._module_from_lib(lib))

    rawRequest = { "stacks": [[]], "memoryMap": memoryMap, "version": 4, "symbolSources": ["FIREFOX", "WINDOWS"] }
    request = SymbolicationRequest(self.sym_file_manager, rawRequest)
    if not request.isValidRequest:
      return []
    request.Symbolicate(0) # This sets request.knownModules

    unknown_modules = []
    for i, lib in enumerate(shared_libraries):
      if not request.knownModules[i]:
        unknown_modules.append(lib)
    return unknown_modules

  def dump_and_integrate_missing_symbols(self, profile_json, symbol_zip_path):
    if not self.symbol_dumper:
      return

    unknown_modules = self.get_unknown_modules_in_profile(profile_json)
    if not unknown_modules:
      return

    # We integrate the dumped symbols by dumping them directly into our
    # symbol directory.
    output_dir = self.options["symbolPaths"]["FIREFOX"]

    # Additionally, we add all dumped symbol files to the missingsymbols zip file.
    zip = zipfile.ZipFile(symbol_zip_path, 'a', zipfile.ZIP_DEFLATED)

    for lib in unknown_modules:
      self.dump_and_integrate_symbols_for_lib(lib, output_dir, zip)
    zip.close()

  def dump_and_integrate_symbols_for_lib(self, lib, output_dir, zip):
    [name, breakpadId] = self._module_from_lib(lib)

    expected_name_without_extension = os.path.join(name, breakpadId, name)
    for extension in [".sym", ".nmsym"]:
      expected_name = expected_name_without_extension + extension
      if expected_name in zip.namelist():
        # No need to dump the symbols again if we already have it in the
        # missingsymbols zip file from a previous run.
        zip.extract(expected_name, output_dir)
        return

    # Dump the symbols.
    sym_file = dump_symbols_for_lib(name, lib["breakpadId"], lib['name'], output_dir, self.symbol_dumper)
    if sym_file:
      rootlen = len(os.path.join(output_dir, '_')) - 1
      output_filename = sym_file[rootlen:]
      if output_filename not in zip.namelist():
        zip.write(sym_file, output_filename)

  def symbolicate_profile(self, profile_json):
    if "libs" not in profile_json:
      return
    if profile_json["meta"].get("version", 2) == 3:
      self.symbolicate_profile_v3(profile_json)
    else:
      self.symbolicate_profile_v2(profile_json)
    for i, thread in enumerate(profile_json["threads"]):
      if isinstance(thread, basestring):
        thread_json = json.loads(thread)
        self.symbolicate_profile(thread_json)
        profile_json["threads"][i] = json.dumps(thread_json)

  def symbolicate_profile_v2(self, profile_json):
    shared_libraries = json.loads(profile_json["libs"])
    shared_libraries.sort(key=lambda lib: lib["start"])
    addresses = self._find_addresses_v2(profile_json)
    symbols_to_resolve = self._assign_symbols_to_libraries(addresses, shared_libraries)
    symbolication_table = self._resolve_symbols(symbols_to_resolve)
    self._substitute_symbols_v2(profile_json, symbolication_table)

  def symbolicate_profile_v3(self, profile_json):
    shared_libraries = json.loads(profile_json["libs"])
    shared_libraries.sort(key=lambda lib: lib["start"])
    addresses = self._find_addresses_v3(profile_json)
    symbols_to_resolve = self._assign_symbols_to_libraries(addresses, shared_libraries)
    # print symbols_to_resolve
    symbolication_table = self._resolve_symbols(symbols_to_resolve)
    self._substitute_symbols_v3(profile_json, symbolication_table)

  def _find_addresses_v3(self, profile_json):
    addresses = set()
    for thread in profile_json["threads"]:
      if isinstance(thread, basestring):
        continue
      for s in thread["stringTable"]:
        if s[0:2] == "0x":
          addresses.add(s)
    return addresses

  def _substitute_symbols_v3(self, profile_json, symbolication_table):
    for thread in profile_json["threads"]:
      if isinstance(thread, basestring):
        continue
      for i, s in enumerate(thread["stringTable"]):
        thread["stringTable"][i] = symbolication_table.get(s, s)

  def _find_addresses_v2(self, profile_json):
    addresses = set()
    for thread in profile_json["threads"]:
      for sample in thread["samples"]:
        for frame in sample["frames"]:
          if frame["location"][0:2] == "0x":
            addresses.add(frame["location"])
          if "lr" in frame and frame["lr"][0:2] == "0x":
            addresses.add(frame["lr"])
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

    rawRequest = { "stacks": [processedStack], "memoryMap": memoryMap, "version": 4, "symbolSources": ["FIREFOX", "WINDOWS"] }
    request = SymbolicationRequest(self.sym_file_manager, rawRequest)
    if not request.isValidRequest:
      print "invalid request"
      return {}
    symbolicated_stack = request.Symbolicate(0)
    return dict(zip(all_symbols, symbolicated_stack))

  def _substitute_symbols_v2(self, profile_json, symbolication_table):
    for thread in profile_json["threads"]:
      for sample in thread["samples"]:
        for frame in sample["frames"]:
          frame["location"] = symbolication_table.get(frame["location"], frame["location"])

  def symbolicate_profile_file(self, filename):
    f = open(filename, "r")
    profile = json.load(f)
    f.close()
    self.dump_and_integrate_missing_symbols(profile, "missingsymbols.zip")
    self.symbolicate_profile(profile)
    f = open(filename + ".sym", "w")
    json.dump(profile, f)
    f.close()
