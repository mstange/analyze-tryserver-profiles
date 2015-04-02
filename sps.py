# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json

def filter_measurements(profile, is_startup_test=False):
  startMeasurementMarker = "MEASUREMENT_START"
  stopMeasurementMarker = "MEASUREMENT_STOP"
  samples = profile["threads"][0]["samples"]
  measured_samples = []
  in_measurement = is_startup_test
  for sample in samples:
    if "marker" in sample:
      for marker in sample["marker"]:
        if startMeasurementMarker in marker["name"]:
          in_measurement = True
        if stopMeasurementMarker in marker["name"]:
          in_measurement = False
    if True or in_measurement:
      measured_samples.append(sample)
  profile["threads"][0]["samples"] = measured_samples
  return profile

def merge_profiles(profiles):
  if len(profiles) == 1:
    return profiles[0]

  interleave = False

  def earliest_absolute_sample_time(profile):
    def earliest_sample_time_in_thread(thread):
      return next((sample["time"] for sample in thread["samples"] if "time" in sample), float("inf"))
    return profile["meta"]["startTime"] + min(earliest_sample_time_in_thread(thread) for thread in profile["threads"])

  def ensure_time_field(samples):
    for i, sample in enumerate(samples):
      if not "time" in sample:
        if i >= 2:
          previous_delta = samples[i - 1]["time"] - samples[i - 2]["time"]
          sample["time"] = samples[i - 1]["time"] + previous_delta
        else:
          sample["time"] = 0

  def adjust_time(samples, time_delta):
    for i, sample in enumerate(samples):
      sample["time"] += time_delta

  profiles = sorted(profiles, key=earliest_absolute_sample_time)

  for profile in profiles:
    for thread in profile["threads"]:
      ensure_time_field(thread["samples"])
      ensure_time_field(thread["markers"])
      for marker in thread["markers"]:
        marker_samples = marker.get("data", {}).get("stack", {}).get("samples", [])
        ensure_time_field(marker_samples)

  first_profile = profiles[0]
  other_profiles = profiles[1:]

  for other_profile in other_profiles:
    for other_thread in other_profile["threads"]:
      try:
        first_thread = next(thread for thread in first_profile["threads"] if thread["name"] == other_thread["name"])
      except StopIteration:
        first_thread = { "name": other_thread["name"], "samples": [], "markers": [] }
        first_profile["threads"].append(first_thread)

      if not interleave:
        time_delta = other_profile["meta"]["startTime"] - first_profile["meta"]["startTime"]
        # Adjusting other_thread's time information by time_delta so that the profiler timeline
        # shows the correct absolute time relation of all included profiles
        adjust_time(other_thread["samples"], time_delta)
        adjust_time(other_thread["markers"], time_delta)
        for marker in other_thread["markers"]:
          marker_samples = marker.get("data", {}).get("stack", {}).get("samples", [])
          adjust_time(marker_samples, time_delta)

      first_thread["samples"] += other_thread["samples"]
      first_thread["markers"] += other_thread["markers"]

  if interleave:
    for first_thread in first_profile["threads"]:
      first_thread["samples"].sort(key=lambda s: s["time"])
      first_thread["markers"].sort(key=lambda s: s["time"])

  return first_profile

def compress_profile(profile):
  symbols = set()
  for thread in profile["threads"]:
    for sample in thread["samples"]:
      for frame in sample["frames"]:
        if isinstance(frame, basestring):
          symbols.add(frame)
        else:
          symbols.add(frame["location"])
  location_to_index = dict((l, str(i)) for i, l in enumerate(symbols))
  for thread in profile["threads"]:
    for sample in thread["samples"]:
      for i, frame in enumerate(sample["frames"]):
        if isinstance(frame, basestring):
          sample["frames"][i] = location_to_index[frame]
        else:
          frame["location"] = location_to_index[frame["location"]]
  profile["format"] = "profileJSONWithSymbolicationTable,1"
  profile["symbolicationTable"] = dict(enumerate(symbols))
  profile["profileJSON"] = { "threads": profile["threads"] }
  del profile["threads"]

def save_profile(profile, filename):
  f = open(filename, "w")
  json.dump(profile, f)
  f.close()
