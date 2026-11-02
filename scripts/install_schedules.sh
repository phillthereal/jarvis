#!/bin/sh
# Usage: install_schedules.sh [--uninstall]. Plists carry a __HOME__ placeholder, replaced with $HOME on install.
D="$(cd "$(dirname "$0")/.." && pwd)/launchd"; L="$HOME/Library/LaunchAgents"; U="gui/$(id -u)"
mkdir -p "$L" "$D/../data/logs"
for p in "$D"/com.filip.aos-*.plist; do
  n=$(basename "$p")
  launchctl bootout "$U/${n%.plist}" 2>/dev/null
  if [ "$1" = "--uninstall" ]; then rm -f "$L/$n"; echo "removed $n"
  else sed "s#__HOME__#$HOME#g" "$p" > "$L/$n" && launchctl bootstrap "$U" "$L/$n" && echo "installed $n"; fi
done
