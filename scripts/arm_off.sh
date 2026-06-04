#!/bin/bash
# A/B arm OFF: round-robin routing (baseline). N workers via $1 (default 2).
# Only difference vs arm_on.sh is the router mode passed below.
exec "$(dirname "$(readlink -f "$0")")/arm_common.sh" round-robin "${1:-2}"
