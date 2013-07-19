import sys
import string
import json
import base64
import zlib
import re
import argparse
import urllib2
import StringIO
import gzip
from logging import LogTrace, LogError, LogMessage, SetTracingEnabled

def read_file(filename):
  f = open(filename, "r")
  text = f.read()
  f.close()
  return text

def get_profiles_in_files(filenames):
  return [read_file(filename) for filename in filenames]

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

def weight_profile(profile, weight):
  if "profileJSON" in profile:
    samples = profile["profileJSON"]["threads"][0]["samples"]
  else:
    samples = profile["threads"][0]["samples"]
  for i, sample in enumerate(samples):
    sample["weight"] = weight

def fixup_app_path(profile, app, new_path):
  libs = json.loads(profile["libs"])
  for lib in libs:
    index = string.find(lib["name"], app)
    if index > -1:
      lib["name"] = new_path + lib["name"][index + len(app):]
  profile["libs"] = json.dumps(libs)

def save_profile(profile, filename):
  f = open(filename, "w")
  f.write(json.dumps(profile))
  f.close()

def get_json(url):
  io = urllib2.urlopen(url, None, 30)
  return json.load(io)

def compress_profile(profile):
  symbols = set()
  for thread in profile["threads"]:
    for sample in thread["samples"]:
      for frame in sample["frames"]:
        symbols.add(frame["location"])
  location_to_index = dict((l, str(i)) for i, l in enumerate(symbols))
  for thread in profile["threads"]:
    for sample in thread["samples"]:
      for frame in sample["frames"]:
        frame["location"] = location_to_index[frame["location"]]
  profile["format"] = "profileJSONWithSymbolicationTable,1"
  profile["symbolicationTable"] = dict(enumerate(symbols))
  profile["profileJSON"] = { "threads": profile["threads"] }
  del profile["threads"]

parser = argparse.ArgumentParser(description='Process profiles in Tinderbox Talos logs.')

parser.add_argument("-b", "--before", nargs="*", help="files containing the profiles from before the regression")
parser.add_argument("-a", "--after", nargs="+", help="files containing the profiles from after the regression")
parser.add_argument("-o", "--out", default="comparison-profile.txt", help="result filename")

args = parser.parse_args()

LogMessage('Reading "before" profiles...')
profilestrings_before = get_profiles_in_files(args.before)
profiles_before = [json.loads(s) for s in profilestrings_before]
LogMessage('Reading "after" profiles...')
profilestrings_after = get_profiles_in_files(args.after)
profiles_after = [json.loads(s) for s in profilestrings_after]
LogMessage('Changing sample weights on "before" profiles to -1...')
for profile in profiles_before:
  weight_profile(profile, -1)
LogMessage('Merging profiles...')
profile = merge_profiles(profiles_before + profiles_after)
fixup_sample_data(profile)
LogMessage('Compressing result profile...')
compress_profile(profile)
#fixup_app_path(profile, "FirefoxUX.app", "/Users/markus/Desktop/FirefoxUX.app")
save_profile(profile, args.out)
LogMessage('Created {out}.'.format(out=args.out))
