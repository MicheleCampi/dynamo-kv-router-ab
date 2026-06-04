#!/bin/bash
# A/B arm ON: KV-aware routing. N workers via $1 (default 2).
# Only difference vs arm_off.sh is the router mode passed below.
exec "$(dirname "$(readlink -f "$0")")/arm_common.sh" kv "${1:-2}"
