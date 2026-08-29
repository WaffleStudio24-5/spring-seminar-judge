#!/usr/bin/env bash
set -euo pipefail

work_directory=$(mktemp -d)
cp -R /submission/. "$work_directory"
cd "$work_directory"

exec bash ./gradlew test --offline --no-daemon
