#!/usr/bin/env sh
# Library script file containing helper methods used in different other scripts.
# Source like this:
# . util.sh

# Retrieves the value of the environment variable with the passed name and parses its value to a boolean.
# This method returns 0 if the string is truthy, 1 if it falsy and stops if the input is invalud.
# It does NOT explicitly parse for falsy values, anything that is not truthy is considered falsy.
# "1|true|yes|y" -> true
# "0|false|no|n|<emptyString>" -> false
is_env_var_true() {
    # get the value of the environment variable passed in $1
    value=$(printenv "${1:-}")

    case "$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|y)    return 0 ;;
        0|false|no|n|"") return 1 ;;
        *) echo "Invalid boolean value for environment variable '$1': '$value'" >&2; exit 1 ;;
    esac
}


# Parses a truthy string to 1 or 0.
# This method returns 0 if the string is truthy, 1 if it falsy and stops if the input is invalid.
# It does NOT explicitly parse for falsy values, anything that is not truthy is considered falsy.
# "1|true|yes|y" -> true, everything else -> false
# "0|false|no|n|<emptyString>" -> false
is_true() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|y)     return 0 ;;
        0|false|no|n|"")  return 1 ;;
        *) echo "Invalid boolean value: '$1'" >&2; exit 1 ;;
    esac
}
