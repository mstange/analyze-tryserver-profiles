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

parser.add_argument("-o", "--out", help="output filename")
parser.add_argument("-r", "--rev", nargs="+", help="tryserver revisions")
parser.add_argument("-p", "--platform", choices=["snowleopard", "lion", "mountainlion", "winxp", "win7", "win8", "linux", "linux64"], help="tryserver Talos platform")
parser.add_argument("-t", "--test", choices=["tpaint", "ts_paint", "cart", "tart", "tresize", "tscrollx", "tsvgx", "tp5o", "tp5o_scroll", "sessionrestore", "glterrain"], help="name of the test")
parser.add_argument("-m", "--max", type=int, default=1000, help="maximum number of profiles")

args = parser.parse_args()

symbolicator = symbolication.ProfileSymbolicator(gSymbolicationOptions)

def load_json_debug(s):
  try:
    return json.loads(s)
  except Exception as e:
    LogMessage("Error loading JSON from string %s...%s" % (s[0:100], s[-100:]))
    raise e

for rev in args.rev:
  LogMessage("Listing Talos runs for try revision {rev}...".format(rev=rev))
  push = tryserver.TryserverPush(rev)
  LogMessage("Looking for build directory...")
  dir = push.get_build_dir(args.platform)
  LogMessage("Downloading profiles...")
  profiles = {}
  for talos_zip_url in push.find_talos_zips(args.platform, args.test):
    for subtest, profile in push.get_talos_profiles(talos_zip_url):
      profiles.setdefault(subtest, []).append(profile)
  for subtest in profiles:
    num_exceed_max = max(0, len(profiles[subtest]) - args.max)
    if num_exceed_max > 0:
      LogMessage("Discarding {num_exceed_max} profiles for subtest {subtest} due to --max restriction to {max} profiles.".format(num_exceed_max=num_exceed_max, subtest=subtest, max=args.max))
    profiles[subtest] = profiles[subtest][0:args.max]
  if not profiles:
    LogMessage("No profiles found in any log for revision {rev}.".format(rev=rev))
    continue
  symbolicate = True
  if symbolicate:
    LogMessage("Getting symbols...")
    symbol_zip_url = push.get_build_symbols_url(dir)
    if symbol_zip_url:
      symbolicator.integrate_symbol_zip_from_url(symbol_zip_url)
  for subtest, subtest_profiles in profiles.iteritems():
    LogMessage("Parsing profiles for subtest {subtest}...".format(subtest=subtest))
    try:
      subtest_profiles = [s.get_json() for s in subtest_profiles]
    except Exception as e:
      exit();
    LogMessage("Extracted {numprofiles} profiles for subtest {subtest}.".format(numprofiles=len(subtest_profiles), subtest=subtest))
    if symbolicate:
      LogMessage("Symbolicating profiles...")
      for profile in subtest_profiles:
        symbolicator.symbolicate_profile(profile)
    LogMessage("Merging profiles...")
    merged_profile = sps.merge_profiles(subtest_profiles)
    LogMessage("Compressing merged profile...")
    sps.compress_profile(merged_profile)
    LogMessage("Saving merged profile...")
    out_filename = "merged-profile-{subtest}-{test}-{platform}-{rev}.sps".format(rev=rev, platform=args.platform, test=args.test, subtest=subtest)
    sps.save_profile(merged_profile, out_filename)
    LogMessage("Created {out_filename}.".format(out_filename=out_filename))
