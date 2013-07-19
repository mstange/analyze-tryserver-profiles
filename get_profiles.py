import sys
import string
import json
import base64
import zlib
import re
import os
import argparse
import urllib2
import StringIO
import gzip
import zipfile
from symFileManager import SymFileManager
from symbolicationRequest import SymbolicationRequest
from logging import LogTrace, LogError, LogMessage, SetTracingEnabled

# Default config options
gOptions = {
  # Trace-level logging (verbose)
  "enableTracing": 0,
  # Fallback server if symbol is not found locally
  "remoteSymbolServer": "http://symbolapi.mozilla.org:80/",
  # Maximum number of symbol files to keep in memory
  # "maxCacheEntries": 10 * 1000 * 1000,
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
    "FIREFOX": os.getcwd() + os.sep + "symbols_ffx" + os.sep,
    # Location of Thunderbird library symbols
    "THUNDERBIRD": os.getcwd() + os.sep + "symbols_tbrd" + os.sep,
    # Location of Windows library symbols
    "WINDOWS": os.getcwd() + os.sep + "symbols_os" + os.sep
  }
}

def get_test_in_log(log, testname):
  match = re.compile("Running test " + testname + ":(.*?)(Running test |$)", re.DOTALL).search(log)
  return match and match.groups()[0]

def get_profilestrings(logpart):
  profilestrings = re.compile("data:text/x-sps_profile;base64,.{0,100}?([A-Za-z0-9+/=]{5,})", re.MULTILINE | re.DOTALL).findall(logpart)
  profiles = []
  for base64compressed in profilestrings:
    try:
      #print "decoding..."
      compressed = base64.b64decode(base64compressed)
      #print "decoded!"
      #print "uncompressing..."
      profile = zlib.decompress(compressed)
      #print "uncompressed!"
      #print profile
      profiles.append(profile)
    except:
      print "decoding or uncompressing failed"
      pass

  return profiles

def merge_profiles(profiles):
  first_profile = profiles[0]
  other_profiles = profiles[1:]
  if "profileJSON" in first_profile:
    first_samples = first_profile["profileJSON"]["threads"][0]["samples"]
  else:
    first_samples = first_profile["threads"][0]["samples"]
  for other_profile in other_profiles:
    if "profileJSON" in other_profile:
      other_samples = other_profile["profileJSON"]["threads"][0]["samples"]
    else:
      other_samples = other_profile["threads"][0]["samples"]
    first_samples.extend(other_samples)
  if "symbolicationTable" in first_profile:
    symbolicationTable = first_profile["symbolicationTable"]
    for other_profile in other_profiles:
      if "symbolicationTable" in other_profile:
        symbolicationTable.update(other_profile["symbolicationTable"])
  return first_profile

def filter_measurements(profile, is_startup_test=False):
  startMeasurementMarker = "MEASUREMENT_START"
  stopMeasurementMarker = "MEASUREMENT_STOP"
  samples = profile["threads"][0]["samples"]
  measured_samples = []
  in_measurement = is_startup_test
  for sample in samples:
    if "marker" in sample:
      if startMeasurementMarker in sample["marker"]:
        in_measurement = True
      if stopMeasurementMarker in sample["marker"]:
        in_measurement = False
      del sample["marker"]
    if in_measurement:
      measured_samples.append(sample)
  profile["threads"][0]["samples"] = measured_samples
  return profile

def get_json(url):
  io = urllib2.urlopen(url, None, 30)
  return json.load(io)

def get_log_for_run(run):
  url = run["log"] 
  #print "Reading log from url " + url
  try:
    io = urllib2.urlopen(url, None, 30)
  except e:
    return ""
  sio = StringIO.StringIO(io.read())
  io.close()
  gz = gzip.GzipFile(fileobj=sio)
  result = gz.read()
  gz.close()
  return result

def containing_directory(url):
  return url[0:url.rfind('/')+1]

def symbols_url_in_dir(builddir):
  io = urllib2.urlopen(builddir, None, 30)
  html = io.read()
  io.close()
  filename = re.search('"([^"]*\.crashreporter-symbols\.zip)"', html).groups()[0]
  return builddir + filename

def unzip_symbols(symbols_zip_url, target_path):
  io = urllib2.urlopen(symbols_zip_url, None, 30)
  sio = StringIO.StringIO(io.read())
  zf = zipfile.ZipFile(sio)
  zf.extractall(target_path)

def ensure_symbols(talos_runs):
  somerun = talos_runs[0]
  builddir = containing_directory(somerun["log"])
  symbols_url = symbols_url_in_dir(builddir)
  unzip_symbols(symbols_url, gOptions["symbolPaths"]["FIREFOX"])

def merge_profiles(profiles):
  first_profile = profiles[0]
  other_profiles = profiles[1:]
  if "profileJSON" in first_profile:
    first_samples = first_profile["profileJSON"]["threads"][0]["samples"]
  else:
    first_samples = first_profile["threads"][0]["samples"]
  for other_profile in other_profiles:
    if "profileJSON" in other_profile:
      other_samples = other_profile["profileJSON"]["threads"][0]["samples"]
    else:
      other_samples = other_profile["threads"][0]["samples"]
    first_samples.extend(other_samples)
  if "symbolicationTable" in first_profile:
    symbolicationTable = first_profile["symbolicationTable"]
    for other_profile in other_profiles:
      if "symbolicationTable" in other_profile:
        symbolicationTable.update(other_profile["symbolicationTable"])
  return first_profile

def fixup_sample_data(profile):
  if "profileJSON" in profile:
    samples = profile["profileJSON"]["threads"][0]["samples"]
  else:
    samples = profile["threads"][0]["samples"]
  for i, sample in enumerate(samples):
    sample["time"] = i
    if "responsiveness" in sample:
      del sample["responsiveness"]

def save_profile(profile, filename):
  f = open(filename, "w")
  f.write(json.dumps(profile))
  f.close()

def find_addresses(profile):
  addresses = set()
  for thread in profile["threads"]:
    for sample in thread["samples"]:
      for frame in sample["frames"]:
        if frame["location"][0:2] == "0x":
          addresses.add(frame["location"])
        if "lr" in frame and frame["lr"][0:2] == "0x":
          address.add(frame["lr"])
  return addresses

def get_containing_library(address, libs):
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

def assign_symbols_to_libraries(addresses, shared_libraries):
  libs_with_symbols = {}
  for address in addresses:
    lib = get_containing_library(int(address, 0), shared_libraries)
    if not lib:
      continue
    if lib["start"] not in libs_with_symbols:
      libs_with_symbols[lib["start"]] = { "library": lib, "symbols": set() }
    libs_with_symbols[lib["start"]]["symbols"].add(address)
  return libs_with_symbols.values()

def module_from_lib(lib):
  if "breakpadId" in lib:
    return [lib["name"], lib["breakpadId"]]
  pdbSig = re.sub("[{}\-]", "", lib["pdbSignature"])
  return [lib["pdbName"], pdbSig + lib["pdbAge"]]

def resolve_symbols_windows(symbols_to_resolve):
  global gOptions

  memoryMap = []
  processedStack = []
  all_symbols = [];
  for moduleIndex, library_with_symbols in enumerate(symbols_to_resolve):
    lib = library_with_symbols["library"]
    symbols = library_with_symbols["symbols"]
    memoryMap.append(module_from_lib(lib))
    all_symbols += symbols
    for symbol in symbols:
      processedStack.append([moduleIndex, int(symbol, 0) - lib["start"]])

  rawRequest = { "stacks": [processedStack], "memoryMap": memoryMap, "version": 3, "osName": "Windows", "appName": "Firefox" }
  request = SymbolicationRequest(SymFileManager(gOptions), rawRequest)
  if not request.isValidRequest:
    return {}
  symbolicated_stack = request.Symbolicate(0)
  return dict(zip(all_symbols, symbolicated_stack))

def substitute_symbols(profile, symbolication_table):
  for thread in profile["threads"]:
    for sample in thread["samples"]:
      for frame in sample["frames"]:
        frame["location"] = symbolication_table.get(frame["location"], frame["location"])

def symbolicate(profile):
  shared_libraries = json.loads(profile["libs"])
  shared_libraries.sort(key=lambda lib: lib["start"])
  addresses = find_addresses(profile)
  symbols_to_resolve = assign_symbols_to_libraries(addresses, shared_libraries)
  symbolication_table = resolve_symbols_windows(symbols_to_resolve)
  substitute_symbols(profile, symbolication_table)

buildernames = {
  "win7": {
    "tpaint": 'Windows 7 32-bit try talos other'
  },
  "winxp": {
    "tpaint": 'Windows XP 32-bit try talos other'
  }
}

parser = argparse.ArgumentParser(description='Process profiles in Tinderbox Talos logs.')

parser.add_argument("-r", "--rev", nargs="+", help="tryserver revisions")
parser.add_argument("-p", "--platform", choices=["winxp", "win7"], help="tryserver Talos platform")
parser.add_argument("-t", "--test", choices=["tpaint"], help="name of the test")
parser.add_argument("-m", "--max", type=int, default=1000, help="maximum number of profiles")

args = parser.parse_args()

test_name = args.test
is_startup_test = (test_name[0:2]=="ts")

for rev in args.rev:
  LogMessage("Listing Talos runs for try revision {rev}...".format(rev=rev))
  tbpl_json = get_json("https://tbpl.mozilla.org/php/getRevisionBuilds.php?branch=try&rev=" + rev)
  talos_runs = [run for run in tbpl_json if run['buildername'] == buildernames[args.platform][args.test]]
  LogMessage("Downloading symbols...")
  ensure_symbols(talos_runs)
  profilestrings = []
  LogMessage("Downloading logs and reading profiles...")
  for run in talos_runs:
    log = get_log_for_run(run)
    profilestrings += get_profilestrings(get_test_in_log(log, test_name))
  profiles = [json.loads(s) for s in profilestrings[0:args.max]]
  LogMessage("Filtering profiles...")
  profiles = [filter_measurements(p, is_startup_test=is_startup_test) for p in profiles]
  LogMessage("Symbolicating profiles...")
  for profile in profiles:
    symbolicate(profile)
  LogMessage("Merging profiles...")
  merged_profile = merge_profiles(profiles)
  out_filename = "merged-profile-{rev}-{platform}.txt".format(rev=rev, platform=args.platform)
  save_profile(merged_profile, out_filename)
  LogMessage("Created {out_filename}.".format(out_filename=out_filename))
