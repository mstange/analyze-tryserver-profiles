import sys
import string
import base64
import zlib
import re
import zipfile
import tempfile
from logging import LogTrace, LogError, LogMessage, SetTracingEnabled


gProfileStringRE = re.compile("Begin SPS Profile:.{0,100}?data:text/x-sps_profile;base64,(.*?)(End SPS Profile.|Begin |DEBUG|$)", re.DOTALL)
gSymbolStringRE = re.compile("Begin system library symbols:.{0,100}?data:application/zip;base64,(.*?)(End system library symbols.|Begin |DEBUG|$)", re.DOTALL)
gBase64RE = re.compile("([A-Za-z0-9+/=]{5,})")

class TalosLogAnalyzer:
  def __init__(self, log):
    self.log = log

  def get_profiles(self):
    profilestrings = gProfileStringRE.findall(self.log)
    for profilestring in profilestrings:
      try:
        base64compressed = self._get_concatenated_base64(profilestring[0])
        compressed = base64.b64decode(base64compressed)
        profile = zlib.decompress(compressed)
        yield profile
      except:
        LogError("decoding or uncompressing failed")

  def get_system_lib_symbols(self):
    symbolstrings = gSymbolStringRE.findall(self.log)
    for symbolstring in symbolstrings:
      try:
        base64d = self._get_concatenated_base64(symbolstring[0])
        compressed = base64.b64decode(base64d)
        path = tempfile.mktemp(".zip")
        f = open(path, "w")
        f.write(compressed)
        f.close()
        yield zipfile.ZipFile(path, "r")
      except:
        LogError("reading system library symbols failed")

  def _get_concatenated_base64(self, str_with_chunked_base64):
    return "".join(gBase64RE.findall(str_with_chunked_base64))
