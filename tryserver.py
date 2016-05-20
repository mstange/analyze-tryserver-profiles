import json
import os
import re
import urllib2
import StringIO
import cStringIO
import gzip
import zipfile
from symLogging import LogTrace, LogError, LogMessage, SetTracingEnabled

class FileInZip:
  def __init__(self, zf, filename):
    self.zf = zf
    self.filename = filename

  def get_json(self):
    f = self.zf.open(self.filename)
    result = json.load(f)
    f.close()
    return result

class TryserverPush:
  treeherder_platformnames = {
    "snowleopard": "osx-10-6",
    "lion": "osx-10-7",
    "mountainlion": "osx-10-8",
    "win7": "windows7-32",
    "winxp": "windowsxp",
    "win8": "windows8-64",
    "linux": "linux32",
    "linux64": "linux64",
  }

  def __init__(self, rev):
    self.rev = rev
    self.treeherder_data = self._get_json("https://treeherder.mozilla.org/api/project/try/resultset/?count=1&format=json&with_jobs=true&full=true&revision=" + rev)

  def find_talos_zips(self, platform, test):
    # Find all talos runs that link to a profile_{test}.zip.
    link_value = "profile_{test}.zip".format(test=test)
    for info in self._get_jobs_on_platform(platform):
      job_details = info.get("blob", {}).get("job_details", [])
      for job_detail in job_details:
        if job_detail["content_type"] == "link" and job_detail["value"] == link_value:
          yield job_detail["url"]

  def _get_jobs_on_platform(self, platform):
    if not platform in self.treeherder_platformnames:
      LogError("Unknown try platform {platform}.".format(platform=platform))
      return
    job_property_index_id = self.treeherder_data["job_property_names"].index("id")
    for result in self.treeherder_data["results"]:
      for th_platform in result["platforms"]:
        if th_platform["name"] != self.treeherder_platformnames[platform]:
          continue
        for group in th_platform["groups"]:
          for job in group["jobs"]:
            job_id = job[job_property_index_id]
            job_info = self._get_json("https://treeherder.mozilla.org/api/project/try/artifact/?job_id=%d&name=Job+Info&type=json" % job_id)
            for info in job_info:
              yield info

  def get_build_symbols_url(self, dir):
    if not dir:
      return None
    return self._url_in_dir_ending_in("crashreporter-symbols.zip", dir)

  def get_talos_profiles(self, zip_url):
    LogMessage("Retrieving profile zip from {zip_url}...".format(zip_url=zip_url))
    io = urllib2.urlopen(zip_url, None, 30)
    sio = cStringIO.StringIO(io.read())
    zf = zipfile.ZipFile(sio)
    io.close()
    for filename in zf.namelist():
      profilename_subtestname = os.path.dirname(filename)
      subtestname = os.path.basename(profilename_subtestname)
      yield (subtestname, FileInZip(zf, filename))

  def _get_json(self, url):
    io = urllib2.urlopen(url, None, 30)
    return json.load(io)

  def _get_test_in_log(self, log, testname):
    match = re.compile("Running test " + testname + ":(.*?)(Running test |$)", re.DOTALL).search(log)
    return (match and match.groups()[0]) or ""

  def get_build_dir(self, platform):
    for info in self._get_jobs_on_platform(platform):
      if "blob" in info and "logurl" in info["blob"]:
        build_log_url = info["blob"]["logurl"]
        return build_log_url[0:build_log_url.rfind('/')+1] 

    LogError("The try push with revision {rev} does not have a build for platform {platform}.".format(rev=self.rev, platform=platform))
    return ""

  def _url_in_dir_ending_in(self, postfix, dir):
    io = urllib2.urlopen(dir, None, 30)
    html = io.read()
    io.close()
    filename = re.search('"([^"]*' + postfix + ')"', html).groups()[0]
    return dir + filename
