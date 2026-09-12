#!/usr/bin/env sh
# Library script file containing helper methods used in different other scripts.
# Source like this:
# . util.sh

# Parse a truthy string to 1 or 0.
# This method returns 0 if the string is truthy, otherwise false.
# It does NOT explicitly parse for falsy values, anything that is not truthy is considered falsy.
# "1|true|yes|y" -> true, everything else -> false
# Returns 0 if argument is truthy, otherwise 1
is_true() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|y) return 0 ;;
        *)            return 1 ;;
    esac
}