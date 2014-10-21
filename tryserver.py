import json
import re
import urllib2
import StringIO
import cStringIO
import gzip
import zipfile
from logging import LogTrace, LogError, LogMessage, SetTracingEnabled

class TryserverPush:
  buildernames = {
    "snowleopard": {
      "tart": "Rev4 MacOSX Snow Leopard 10.6 try talos svgr",
      "tpaint": "Rev4 MacOSX Snow Leopard 10.6 try talos other_nol64",
      "ts_paint": "Rev4 MacOSX Snow Leopard 10.6 try talos other_nol64",
      "build": "OS X 10.7 try build"
    },
    "lion": {
      "tart": "Rev4 MacOSX Lion 10.7 try talos svgr",
      "tpaint": "Rev4 MacOSX Lion 10.7 try talos other_nol64",
      "ts_paint": "Rev4 MacOSX Lion 10.7 try talos other_nol64",
      "build": "OS X 10.7 try build"
    },
    "mountainlion": {
      "tart": "Rev5 MacOSX Mountain Lion 10.8 try talos svgr",
      "tpaint": "Rev5 MacOSX Mountain Lion 10.8 try talos other_nol64",
      "ts_paint": "Rev5 MacOSX Mountain Lion 10.8 try talos other_nol64",
      "build": "OS X 10.7 try build"
    },
    "win7": {
      "tpaint": 'Windows 7 32-bit try talos other_nol64',
      "ts_paint": 'Windows 7 32-bit try talos other_nol64',
      "tart": 'Windows 7 32-bit try talos svgr',
      "build": "WINNT 5.2 try build"
    },
    "winxp": {
      "tpaint": 'Windows XP 32-bit try talos other_nol64',
      "ts_paint": 'Windows XP 32-bit try talos other_nol64',
      "tart": 'Windows XP 32-bit try talos svgr',
      "build": "WINNT 5.2 try build"
    },
    "win8": {
      "tart": 'WINNT 6.2 try talos svgr',
      "build": "WINNT 5.2 try build",
      "tresize": 'WINNT 6.2 try talos chromez',
    },
  }

  def __init__(self, rev):
    self.rev = rev
    self.treeherder_data = self._get_json("https://treeherder.mozilla.org/api/project/try/resultset/?count=1&format=json&with_jobs=true&full=true&revision=" + rev)

  def get_talos_testlogs(self, platform, test):
    if not platform in self.buildernames:
      LogError("Unknown try platform {platform}.".format(platform=platform))
      raise StopIteration
    if not test in self.buildernames[platform]:
      LogError("Unknown test {test} on try platform {platform}.".format(platform=platform, test=test))
      raise StopIteration
    for url in self._get_log_urls_for_builders([self.buildernames[platform][test]]):
      LogMessage("Downloading log for talos run {logfilename}...".format(logfilename=url[url.rfind("/")+1:]))
      log = self._get_gzipped_log(url)
      testlog = self._get_test_in_log(log, test)
      yield testlog

  def _get_log_urls_for_builders(self, buildernames):
    job_property_index_id = self.treeherder_data["job_property_names"].index("id")
    job_property_index_buildername = self.treeherder_data["job_property_names"].index("ref_data_name")
    for result in self.treeherder_data["results"]:
      for platform in result["platforms"]:
        for group in platform["groups"]:
          for job in group["jobs"]:
            if job[job_property_index_buildername] not in buildernames:
              continue
            job_id = job[job_property_index_id]
            log_url_info = self._get_json("https://treeherder.mozilla.org/api/project/try/job-log-url/?job_id=%d" % job_id)
            for info in log_url_info:
              yield info["url"]

  def get_build_symbols(self, platform):
    if not platform in self.buildernames:
      LogError("Unknown try platform {platform}.".format(platform=platform))
      return None
    dir = self._get_build_dir(platform)
    if not dir:
      return None
    symbols_zip_url = self._url_in_dir_ending_in("crashreporter-symbols.zip", dir)
    io = urllib2.urlopen(symbols_zip_url, None, 30)
    sio = cStringIO.StringIO(io.read())
    zf = zipfile.ZipFile(sio)
    io.close()
    return zf

  def _get_json(self, url):
    io = urllib2.urlopen(url, None, 30)
    return json.load(io)

  def _get_test_in_log(self, log, testname):
    match = re.compile("Running test " + testname + ":(.*?)(Running test |$)", re.DOTALL).search(log)
    return (match and match.groups()[0]) or ""

  def _get_build_dir(self, platform):
    if not platform in self.buildernames:
      LogError("Unknown try platform {platform}.".format(platform=platform))
      return ""
    buildernames = self.buildernames[platform].values()
    for build_log_url in self._get_log_urls_for_builders(buildernames):
      return build_log_url[0:build_log_url.rfind('/')+1]
    LogError("The try push with revision {rev} does not have a build for platform {platform}.".format(rev=self.rev, platform=platform))
    return ""

  def _get_gzipped_log(self, url):
    try:
      io = urllib2.urlopen(url, None, 30)
    except:
      return ""
    sio = StringIO.StringIO(io.read())
    io.close()
    gz = gzip.GzipFile(fileobj=sio)
    result = gz.read()
    gz.close()
    return result

  def _url_in_dir_ending_in(self, postfix, dir):
    io = urllib2.urlopen(dir, None, 30)
    html = io.read()
    io.close()
    filename = re.search('"([^"]*' + postfix + ')"', html).groups()[0]
    return dir + filename
