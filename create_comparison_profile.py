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
import sps

def read_file(filename):
  f = open(filename, "r")
  text = f.read()
  f.close()
  return text

def get_profiles_in_files(filenames):
  return [read_file(filename) for filename in filenames]

def fixup_sample_data(profile):
  if "profileJSON" in profile:
    samples = profile["profileJSON"]["threads"][0]["samples"]
  else:
    samples = profile["threads"][0]["samples"]
  for i, sample in enumerate(samples):
    sample["time"] = i
    if "responsiveness" in sample:
      del sample["responsiveness"]

def weight_profile(profile, factor):
  if "profileJSON" in profile:
    samples = profile["profileJSON"]["threads"][0]["samples"]
  else:
    samples = profile["threads"][0]["samples"]
  for i, sample in enumerate(samples):
    weightbefore = sample["weight"] if "weight" in sample else 1
    sample["weight"] = factor * weightbefore

def get_json(url):
  io = urllib2.urlopen(url, None, 30)
  return json.load(io)

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Process profiles in Tinderbox Talos logs.')

  parser.add_argument("-b", "--before", nargs="*", default=[], help="files containing the profiles from before the regression")
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
  profile = sps.merge_profiles(profiles_before + profiles_after)
  fixup_sample_data(profile)
  LogMessage('Compressing result profile...')
  sps.compress_profile(profile)
  sps.save_profile(profile, args.out)
  LogMessage('Created {out}.'.format(out=args.out))
