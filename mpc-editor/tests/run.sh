#!/usr/bin/env bash
set -euo pipefail

project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
: "${MPC_SDK:?Set MPC_SDK to the path of the MPC Plugin Builder SDK checkout}"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

"${CXX:-c++}" -std=c++17 -O2 -Wall -Wextra -fPIC -shared -pthread \
    "$project/tests/fake_alsa.cpp" -Wl,-soname,libasound.so.2 -o "$scratch/libasound.so.2"
"${CXX:-c++}" -std=c++17 -O2 -Wall -Wextra -I"$MPC_SDK/framework" \
    "$project/tests/round_trip.cpp" "$scratch/libasound.so.2" -ldl -pthread -o "$scratch/round_trip"

LD_LIBRARY_PATH="$scratch${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$scratch/round_trip" "${1:-$project/build/native/pc44-editor.so}"
