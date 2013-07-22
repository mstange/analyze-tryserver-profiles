Analyze Tryserver Profiles
==========================

A few steps to your own Talos comparison profile:

1. Push to try with this patch applied: http://pastebin.mozilla.org/2654935
2. Wait for Talos results to come in, retrigger Talos jobs if necessary
3. `$ python get_profiles.py --rev 6dc4ce261069 1f58befb7d3e --platform win7 --test tpaint`
4. `$ python create_comparison_profile.py --before merged-profile-6dc4ce261069-win7.txt --after merged-profile-1f58befb7d3e-win7.txt -o comparison-profile-win7.txt`
5. Load `comparison-profile-win7.txt` in [this cleopatra instance](http://tests.themasta.com/cleopatra/).

This is a very rough first stab at the problem. At the moment there is support for the platforms winxp, win7, snowleopard, lion and mountainlion, and for the Talos tests tpaint and ts_paint. The python scripts have only been tested on Mac, but they should run on all platforms. It does not matter what platform the profile was collected on, symbolication should work everywhere.

Some of the `sym*` files are copied from the [Snappy Symbolication Server repo](https://github.com/vdjeric/Snappy-Symbolication-Server/).
