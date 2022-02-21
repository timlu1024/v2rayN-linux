#!/usr/bin/env bash
set -e
shopt -s nullglob

USG="Usage:
    $(basename -- "$0") [-u] [-t] [-c]

Update the v2ray config files, test the current config files, select
the config file to use with its index, and run v2ray.

Options:
    -u      Update the config files using the subscription link.
    -t      Test the current config files and remove the unusable ones.
            This is done by trying to access www.google.com via these
            nodes.
    -c      Let the user choose which config file to use (by index).
            If not specified, choose the config file used last time
            (a symlink named last.json).

Note that for simplicity the order of the options is fixed (i.e. '-u -c' is
OK but '-c -u' is invalid). And combination (like '-uc') is not supported.
"

SCRIPT_DIR=$(cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd)
cd -- "$SCRIPT_DIR"
source -- "v2ray-wrapper.cfg"


# Parse input args
if [ "$1" == -h ] || [ "$1" == --help ]; then
    echo "$USG"
    exit 1
fi
[ "$1" == -u ] && UPDATE=y && shift
[ "$1" == -t ] && TEST=y && shift && parallel --version > /dev/null
[ "$1" == -c ] && CHOOSE=y && shift
[ -n "$1" ] && echo "Unrecognized argument: $1" && exit 1
TEMPLATE="$(realpath -- "$TEMPLATE")"
[ \! -d "$BINDIR" ] && echo "Invalid BINDIR=$BINDIR" && exit 1

# Fetch subscription
[ -n "$UPDATE" ] && ./v2ray-subscr.py -o "$CFGDIR" "$URL"

# Test and remove unusable nodes
test_node () {
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
export -f test_node
[ -n "$TEST" ] && parallel -j "$TESTJOBS" "test_node {}" \
    ::: "$CFGDIR"/[0-9][0-9]-*.json || true

# Choose a config file
if [ -n "$CHOOSE" ]; then
    # Select an index
    ls -1q "$CFGDIR"/[0-9][0-9]-*.json | xargs basename -a | column
    echo -n "Select an index above: "
    read -r CFGIDX
    CFGIDX="$(printf %02d "$CFGIDX")"
    # Verify the index and get the config file name
    CFG=("$CFGDIR"/$CFGIDX-*.json)
    [ ${#CFG[@]} -ne 1 ] && echo "Index matches ${#CFG[@]} files: ${CFG[@]}" && exit 1
    CFG="$(realpath -- "${CFG[0]}")"
    # Create symlink
    ln -fs -- "$CFG" "$BINDIR/last.json"
fi

# Run v2ray
cd "$BINDIR"
echo "*** Using $(readlink last.json)"
exec ./v2ray -c "$TEMPLATE" -c last.json

