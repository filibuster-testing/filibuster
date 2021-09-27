#!/usr/bin/env bash

find . -name ".coverage*" -exec cp -Rpv {} . \;
coverage combine
coverage html --omit="/usr/local/lib*,*site-packages*" --include="*app.py*"