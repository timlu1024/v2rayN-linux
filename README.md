# Fetch v2rayN subscription and test node availability on Linux

Some wrapper scripts for [v2ray-core](https://github.com/v2ray/v2ray-core/releases)
on Linux:

1. Fetch v2rayN subscription link and generate json config files.
2. Test node availability by accessing `www.google.com` via these nodes.
3. Conveniently switch to different nodes by specifying an index.

## Overview

Some important files:

- `v2ray-wrapper.cfg`: configuration for `v2ray-wrapper.sh`.

- `template.json`: template for v2ray config json. This file, together with
  the generated config file (which only has `outbounds`), will be given to
  v2ray.

- `v2ray-wrapper.sh`: the main script file, which can fetch subscription,
  test node availability and select different nodes.

## Usage

### 1. Download v2ray binaries.
Extract into this directory, e.g. `v2ray-4.44.0`. It should contain the
`v2ray` binary.

### 2. Config `v2ray-wrapper.sh`
Copy the `sample-v2ray-wrapper.cfg` to `v2ray-wrapper.cfg` and edit it.

```
# Will be sourced by bash
# Relative paths are based on the script dir

# v2rayN subscription link
URL='https://example.com/...'
# Template json file
TEMPLATE=template.json
# Destination of the generated config files
CFGDIR=example_dir
# The directory that contains the v2ray binary
BINDIR=v2ray-4.44.0
# Number of concurrent instances when testing nodes
TESTJOBS=16
```

### 3. Config `template.json`
Copy the `sample-template.json` to `template.json`. Modify it if necessary (
e.g. change local port, log level...).

### 4. Run `v2ray-wrapper.sh`
The main script file is `v2ray-wrapper.sh`. To use `-t` (test availability),
you have to install [GNU Parallel](https://www.gnu.org/software/parallel/)
command.

```
Usage:
    v2ray-wrapper.sh [-u] [-t] [-c]

Update the v2ray config files, test the current config files, select
the config file to use with its index, and run v2ray.

Options:
    -u      Update the config files using the subscription link.
    -t      Test the current config files and remove the unusable ones.
            This is done by trying to access www.google.com via these
            nodes.
    -c      Let the user choose which config file to use (by index).

Note that for simplicity the order of the options is fixed (i.e. `-u -c` is
OK but `-c -u` is invalid). And combination (like `-uc`) is not supported.
```

To have more control over fetching v2rayN subscription link, you can manually
invoke `v2ray-subscr.py` (it's used internally in `v2ray-wrapper.sh`).

```
usage: v2ray-subscr.py [-h] [-v] [-n] [-o OUTPUT] url

Parse a v2rayN subscription link and generate json config files for v2ray into
a directory. The unused json files in that directory will be removed.

positional arguments:
  url                   v2rayN subsription link

options:
  -h, --help            show this help message and exit
  -v, --verbose         Verbose mode
  -n, --dryrun          Don't modify anything on disk
  -o OUTPUT, --output OUTPUT
                        Output directory

```

