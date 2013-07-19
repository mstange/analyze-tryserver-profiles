Analyze Tryserver Profiles
==========================

A few steps to your own Talos comparison profile:

1. Push to try with this patch applied: http://pastebin.mozilla.org/2654935
2. Wait for Talos results to come in, retrigger Talos jobs if necessary
3. `$ python get_profiles.py --rev 6dc4ce261069 1f58befb7d3e --platform win7 --test tpaint`
4. `$ python create_comparison_profile.py --before merged-profile-6dc4ce261069-win7.txt --after merged-profile-1f58befb7d3e-win7.txt -o comparison-profile-win7.txt`
5. Load `comparison-profile-win7.txt` in [this cleopatra instance](http://tests.themasta.com/cleopatra/).

This is a very rough first stab at the problem. At the moment there is only support for platforms winxp and win7 and Talos test tpaint. The python scripts run on Mac though (I've only tested them on Mac, don't know if they work on Windows).

The `sym*` files are copied from the [Snappy Symbolication Server repo](https://github.com/vdjeric/Snappy-Symbolication-Server/).
