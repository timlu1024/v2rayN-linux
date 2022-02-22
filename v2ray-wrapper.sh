#!/usr/bin/env bash
set -e
shopt -s nullglob

USG="Usage:
    $(basename -- "$0") [-u] [-t] [-c] [-n] [<cfg>]

Update the v2ray config files, test the current config files, select
the config file to use with its index, and run v2ray.

    <cfg>   Config file of this script. Default is v2ray-wrapper.cfg.
            This file will be sourced, so you can even put your own
            scripts here.

Options:
    -u      Update the config files using the subscription link.
    -t      Test the current config files and remove the unusable ones.
            This is done by trying to access www.google.com via these
            nodes.
    -c      Let the user choose which config file to use (by index).
            If not specified, choose the config file used last time
            (a symlink named last.json).
    -n      Don't run v2ray in the end.

Note that for simplicity the order of the options is fixed (i.e. '-u -c' is
OK but '-c -u' is invalid). And combination (like '-uc') is not supported.
"

SCRIPTDIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# Parse input args
if [ "$1" = -h ] || [ "$1" = --help ]; then
    echo "$USG"
    exit 1
fi
[ "$1" = -u ] && UPDATE=y && shift
[ "$1" = -t ] && TEST=y && shift && parallel --version > /dev/null
[ "$1" = -c ] && CHOOSE=y && shift
[ "$1" = -n ] && NORUN=y && shift
[ "${1:0:1}" = - ] && echo "Unrecognized option: $1" && exit 1
[ -n "$1" ] && WRAPPERCFG="$1" && shift
[ -n "$1" ] && echo "Unrecognized argument: $1" && exit 1

# cd into .cfg directory
WRAPPERCFG="$(realpath -- "${WRAPPERCFG:-v2ray-wrapper.cfg}")"
[ \! -f "$WRAPPERCFG" ] && echo "Invalid WRAPPERCFG=$WRAPPERCFG" && exit 1
cd -- "$(dirname -- "$WRAPPERCFG")"

# Source .cfg file
source -- "$WRAPPERCFG"
TEMPLATE="$(realpath -- "$TEMPLATE")"
[ \! -d "$BINDIR" ] && echo "Invalid BINDIR=$BINDIR" && exit 1

# Fetch subscription
[ -n "$UPDATE" ] && "$SCRIPTDIR"/v2ray-subscr.py -o "$CFGDIR" "$URL"

# Get the list of json config files
CFGLIST="$(find "$CFGDIR"/ -maxdepth 1 -name '[0-9][0-9]-*.json' | sort)"
[ -z "$CFGLIST" ] && echo "json config file not found in $CFGDIR" && exit 1

# Test and remove unusable nodes
test-node () {
    TESTCFG="$1"
    [ \! -f "$TESTCFG" ] && echo "Invalid TESTCFG=$TESTCFG" && return 1
    TESTCFGPATH="$(realpath -- "$TESTCFG")"
    pushd "$BINDIR" &> /dev/null
    set +e
    for i in {1..3}; do
        PORT=$(($RANDOM % (65530-2000) + 2000))
        ./v2ray \
            -c <(echo '{"inbounds": [
                    {"protocol":"socks","port":'$PORT',"listen":"127.0.0.1"}
                 ]}') \
            -c "$TESTCFGPATH" > /dev/null &
        PID=$!
        sleep 2
        ERR="$(curl -sSm 4 -o /dev/null -x "socks5h://127.0.0.1:$PORT" \
                    "http://www.google.com" 2>&1)"
        RC=$?
        kill $PID &> /dev/null
        [ -n "$ERR" ] && echo "$ERR"
        [ $RC -eq 0 ] && break
    done
    set -e
    popd &> /dev/null
    if [ $RC -ne 0 ]; then
        echo "Testing failed, removing config: $TESTCFG"
        rm -f "$TESTCFG" || true
    fi
    return $RC
}
export BINDIR
export -f test-node
[ -n "$TEST" ] && parallel -rj "$TESTJOBS" "test-node {}" <<< "$CFGLIST" || true

# Choose a config file
if [ -n "$CHOOSE" ]; then
    # Select an index
    xargs basename -a <<< "$CFGLIST" | column
    echo -n "Select an index above: "
    read -r CFGIDX
    CFGIDX="$(printf %02d "$CFGIDX")"
    # Verify the index and get the config file name
    CFG=("$CFGDIR"/$CFGIDX-*.json)
    [ ${#CFG[@]} -ne 1 ] && echo "Index matches ${#CFG[@]} files: ${CFG[@]}" && exit 1
    # Create symlink
    pushd "$CFGDIR" &> /dev/null
    ln -fs -- "$(basename -- "${CFG[0]}")" last.json
    popd &> /dev/null
fi

# Run v2ray
CFGDIR="$(realpath -- "$CFGDIR")"
cd "$BINDIR"
echo "*** Using $(readlink "$CFGDIR"/last.json)"
[ -z "$NORUN" ] && exec ./v2ray -c "$TEMPLATE" -c "$CFGDIR"/last.json

