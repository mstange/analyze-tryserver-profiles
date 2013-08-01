import json

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

def merge_profiles(profiles):
  first_profile = profiles[0]
  other_profiles = profiles[1:]
  first_samples = first_profile["threads"][0]["samples"]
  for other_profile in other_profiles:
    other_samples = other_profile["threads"][0]["samples"]
    first_samples.extend(other_samples)
  return first_profile

def fixup_sample_data(profile):
  samples = profile["threads"][0]["samples"]
  for i, sample in enumerate(samples):
    sample["time"] = i
    if "responsiveness" in sample:
      del sample["responsiveness"]

def save_profile(profile, filename):
  f = open(filename, "w")
  json.dump(profile, f)
  f.close()
