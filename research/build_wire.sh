#!/usr/bin/env bash
# Build the pin driver from the checked-out RTL and its assembled P1 source.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
python3 "$here/check_inputs.py" >&2
out=$(realpath -m "${1:-/tmp/forg-chameleon-wire-$UID}")
mkdir -p "$out"
inc=$(verilator -getenv VERILATOR_ROOT)/include
python3 "$root/p1.py" "$root/examples/adaptive_poll.p1" | python3 -c '
import json, sys
program = json.load(sys.stdin)
def values(v):
    return ",".join(map(str, v))
print("constexpr int image[] = {" + values(program["image"]) + "};")
print("constexpr int settings[][2] = {" + ",".join("{"+values(p)+"}" for p in program["settings"]) + "};")
print("constexpr int program_run = " + str(program["run"]) + ";")
' > "$out/poll_image.h"
verilator --cc --build -Wno-fatal -j 2 -CFLAGS "-fPIC" --top-module tt_um_forg_protocol_chameleon \
    --prefix Vwire --Mdir "$out/obj" "$root"/src/*.v >&2
g++ -std=c++17 -shared -O2 -fPIC -pthread -I"$out" -I"$out/obj" -I"$inc" -I"$inc/vltstd" \
    "$here/wire.cpp" "$out/obj/Vwire__ALL.a" "$inc/verilated.cpp" "$inc/verilated_threads.cpp" \
    -o "$out/libwire.so"
printf '%s\n' "$out/libwire.so"
