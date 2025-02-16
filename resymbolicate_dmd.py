import os
import symbolication
from urllib.request import urlopen
from io import BytesIO
import zipfile
from symFileManager import SymFileManager
from symbolicationRequest import SymbolicationRequest
import re

# Symbolicate out.dmd from a tryserver build built with --enable-dmd using the build's crashreporter symbols.
# as used in bug 1033679

symbols_zip_url = "http://ftp.mozilla.org/pub/mozilla.org/firefox/try-builds/tnikkel@gmail.com-4fc291a89c09/try-macosx64-debug/firefox-33.0a1.en-US.mac64.crashreporter-symbols.zip"
inputdmd = open('/Users/mstange/Downloads/out_badsyms.dmd', 'r')
outputdmd = open('/Users/mstange/Downloads/out_sym.dmd', 'w')

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

symbolicator = symbolication.ProfileSymbolicator(gSymbolicationOptions)
io = urlopen(symbols_zip_url, timeout=30)
sio = BytesIO(io.read())
zf = zipfile.ZipFile(sio)
symbolicator.integrate_symbol_zip(zf)
moduleDict = {}
for lib in zf.namelist():
    x = lib.split("/")
    if len(x) > 1:
        moduleDict[x[0]] = [x[0], x[1]]

def find_symbol(lib_name, offset):
    rawRequest = { "stacks": [[[0, int(offset, 0)]]], "memoryMap": [moduleDict[lib_name]], "version": 3, "osName": "Windows", "appName": "Firefox" }
    request = SymbolicationRequest(symbolicator.sym_file_manager, rawRequest)
    symbolicated_stack = request.Symbolicate(0)
    return symbolicated_stack[0]

reStackLine = re.compile("^   .*\[(.*)/([^/]+) \+(0x[0-9a-fA-F]+)\](.*)$", re.DOTALL)

def process_line(line):
    result = reStackLine.match(line)
    if not result or result.group(2) not in moduleDict:
        return line
    return "   " + find_symbol(result.group(2), result.group(3)) + "[" + result.group(1) + "/" + result.group(2) + " +" + result.group(3) + "]" + result.group(4)

for line in inputdmd:
    outputdmd.write(process_line(line))

inputdmd.close()
outputdmd.close()
