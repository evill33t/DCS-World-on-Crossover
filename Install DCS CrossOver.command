#!/bin/bash
# Keep this launcher beside setup_dcs_crossover.py.
cd -- "$(dirname -- "$0")" || exit 1
runner=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
        runner="$candidate"
        break
    fi
done
if [ -z "$runner" ]; then
    printf '%s\n' 'Python 3.9 or newer is required. Install Python 3 from python.org, then run this launcher again.'
    read -r -p 'Press Return to close.'
    exit 1
fi
if [ "$#" -eq 0 ]; then
    "$runner" setup_dcs_crossover.py --wizard
else
    "$runner" setup_dcs_crossover.py "$@"
fi
result=$?
printf '\n'
read -r -p 'Press Return to close.'
exit "$result"
