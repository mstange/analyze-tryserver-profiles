import json
import os
import argparse
import symbolication
import tryserver
import taloslog
import sps
from logging import LogTrace, LogError, LogMessage, SetTracingEnabled

# Snappy symbolication server optinos
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

parser = argparse.ArgumentParser(description='Process profiles in Tinderbox Talos logs.')

parser.add_argument("-f", "--file", nargs="*", help="locally-saved log file")
parser.add_argument("-o", "--out", help="output filename")
parser.add_argument("-r", "--rev", nargs="+", help="tryserver revisions")
parser.add_argument("-p", "--platform", choices=["snowleopard", "lion", "mountainlion", "winxp", "win7"], help="tryserver Talos platform")
parser.add_argument("-t", "--test", choices=["tpaint", "ts_paint"], help="name of the test")
parser.add_argument("-rp", "--reflow-profile", help="specify to extract reflow profiles instead of SPS profiles", action="store_true")
parser.add_argument("-m", "--max", type=int, default=1000, help="maximum number of profiles")

args = parser.parse_args()

symbolicator = symbolication.ProfileSymbolicator(gSymbolicationOptions)

if args.file:
  LogMessage("Loading profiles from files...")
  profilestrings = []
  for filename in args.file:
    fin = open(filename, "r")
    log = fin.read()
    fin.close()
    log_analyzer = taloslog.TalosLogAnalyzer(log)
    if args.reflow_profile:
      profilestrings_in_this_log = list(log_analyzer.get_reflow_profiles())
    else:
      profilestrings_in_this_log = list(log_analyzer.get_sps_profiles())
    profilestrings += profilestrings_in_this_log
    for system_lib_symbols_zip in log_analyzer.get_system_lib_symbols():
      symbolicator.integrate_symbol_zip(system_lib_symbols_zip)
  profiles = [json.loads(s) for s in profilestrings[0:args.max]]
  if not profiles:
    LogMessage("No profiles found.")
    exit()
  LogMessage("Extracted %d profiles." % len(profiles))
  LogMessage("Sample counts: %s" % ", ".join("%d" % len(p["threads"][0]["samples"]) for p in profiles))
  LogMessage("Filtering profiles...")
  for profile in profiles:
    sps.filter_measurements(profile, is_startup_test=(args.test[0:2]=="ts"))
  LogMessage("Sample counts: %s" % ", ".join("%d" % len(p["threads"][0]["samples"]) for p in profiles))
  LogMessage("Merging profiles...")
  merged_profile = sps.merge_profiles(profiles)
  sps.fixup_sample_data(merged_profile)
  out_filename = args.out
  sps.save_profile(merged_profile, out_filename)
  LogMessage("Created {out_filename}.".format(out_filename=out_filename))
  exit()

for rev in args.rev:
  LogMessage("Listing Talos runs for try revision {rev}...".format(rev=rev))
  push = tryserver.TryserverPush(rev)
  LogMessage("Downloading symbols...")
  symbol_zip_file = push.get_build_symbols(args.platform)
  if symbol_zip_file:
    symbolicator.integrate_symbol_zip(symbol_zip_file)
  LogMessage("Downloading logs and reading profiles...")
  profilestrings = []
  for log in push.get_talos_testlogs(args.platform, args.test):
    log_analyzer = taloslog.TalosLogAnalyzer(log)
    if args.reflow_profile:
      profilestrings_in_this_log = list(log_analyzer.get_reflow_profiles())
    else:
      profilestrings_in_this_log = list(log_analyzer.get_sps_profiles())
    profilestrings += profilestrings_in_this_log
    for system_lib_symbols_zip in log_analyzer.get_system_lib_symbols():
      symbolicator.integrate_symbol_zip(system_lib_symbols_zip)
  profiles = [json.loads(s) for s in profilestrings[0:args.max]]
  if not profiles:
    LogMessage("No profiles found in any log for revision {rev}.".format(rev=rev))
    continue
  LogMessage("Extracted %d profiles." % len(profiles))
  LogMessage("Sample counts: %s" % ", ".join("%d" % len(p["threads"][0]["samples"]) for p in profiles))
  LogMessage("Filtering profiles...")
  for profile in profiles:
    sps.filter_measurements(profile, is_startup_test=(args.test[0:2]=="ts"))
  LogMessage("Sample counts: %s" % ", ".join("%d" % len(p["threads"][0]["samples"]) for p in profiles))
  LogMessage("Symbolicating profiles...")
  for profile in profiles:
    symbolicator.symbolicate_profile(profile)
  LogMessage("Merging profiles...")
  merged_profile = sps.merge_profiles(profiles)
  sps.fixup_sample_data(merged_profile)
  out_filename = "merged-profile-{test}-{platform}-{rev}.txt".format(rev=rev, platform=args.platform, test=args.test)
  sps.save_profile(merged_profile, out_filename)
  LogMessage("Created {out_filename}.".format(out_filename=out_filename))
