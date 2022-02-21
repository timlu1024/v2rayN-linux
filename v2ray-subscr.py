#!/usr/bin/env python3
import urllib.request
import urllib.parse
import base64
import json
import logging
import copy
import argparse
import re
import sys
import os

logger = logging.getLogger(__name__)


def strToFileName(str):
    """
    Remove the special characters for a file name.
    @return: <string>
    """
    str = re.sub(r"[^\w\s-]", "", str)
    str = re.sub(r"[-\s]+", "-", str)
    return str


def parseV2rayNSubscr(url):
    """
    Get the content of a v2rayN subscribe link.
    @return: array of (type<string>, desc<string>, config<dict>)
    """

    # Get the content of subscription link
    logger.debug("Getting the content of v2rayN subscription link %s...", url)
    with urllib.request.urlopen(url, timeout=10) as response:
        encBytes = response.read()
    decBytes = base64.b64decode(encBytes)
    decText = decBytes.decode("utf-8")
    lines = decText.splitlines()
    lines = [line for line in lines if line]   # Remove empty lines

    # Parse each line of the subscription
    ret = []
    sample = 2
    for line in lines:
        if sample:
            logger.debug("Sample v2rayN subscription line: %s", line)
        urlParseRes = urllib.parse.urlparse(line)
        if sample:
            logger.debug("Sample URL parse result: %s", repr(urlParseRes))
        nodeType = urlParseRes.scheme
        encNodeConfigText = urlParseRes.netloc
        encNodeConfigBytes = encNodeConfigText.encode("ascii")
        decNodeConfigBytes = base64.b64decode(encNodeConfigBytes)
        decNodeConfigText = decNodeConfigBytes.decode("utf-8")
        if sample:
            logger.debug("Sample node config text: %s", decNodeConfigText)
        nodeConfig = json.loads(decNodeConfigText)
        if sample:
            logger.debug("Sample node config: %s", repr(nodeConfig))

        desc = "<unknown>"
        if nodeType == "vmess":
            desc = nodeConfig["ps"]

        ret.append((nodeType, desc, nodeConfig))

        if sample:
            sample -= 1

    return ret


def nodeConfigToV2rayConfig(nodeType, nodeConfig):
    """
    @nodeType: <string>
    @nodeConfig: <dict>
    @return: <dict> or None
    """
    ret = {}

    if nodeType == "vmess":
        ret["outbounds"] = [
            {
                "protocol": "vmess",
                "settings": {
                    "vnext": [
                        {
                            "address": nodeConfig["add"],
                            "port": nodeConfig["port"],
                            "users": [
                                {
                                    "id": nodeConfig["id"],
                                    "alterId": nodeConfig["aid"],
                                },
                            ],
                        }
                    ],
                },
                "streamSettings": {
                    "network": nodeConfig["net"],
                    "wsSettings": {
                        "path": nodeConfig["path"],
                        "host": nodeConfig["host"],
                    },
                    "security": nodeConfig["tls"],
                },
            },
        ]
    else:
        logger.warning("Unsupported nodeType=%s", nodeType)
        return None

    return ret


def main(url, outDir, dryRun=False):
    """
    Fetch url, generate json config files, remove unused config files.
    @url: <string>
    @outDir: <string>
    @dryRun: <bool>
    """
    logger.debug("url=%s, outDir=%s, dryRun=%d", url, outDir, dryRun)

    # Create output directory
    os.makedirs(outDir, exist_ok=True)

    # Fetch url.
    parseResults = parseV2rayNSubscr(url)
    dryRunPrefix = ""
    if dryRun:
        dryRunPrefix = "(dryrun) "

    # Some stats.
    numSkipped   = 0
    numUpdated   = 0
    numAlready   = 0
    numDeleted   = 0
    usedCfgNames = set()

    # For each node, generate a json config file.
    for idx, res in enumerate(parseResults):
        nodeType    = res[0]
        nodeDesc    = res[1]
        nodeConfig  = res[2]

        # Generate v2ray config dict.
        v2rayConfig = nodeConfigToV2rayConfig(nodeType, nodeConfig)
        if not v2rayConfig:
            numSkipped += 1
            logger.warning("Skipped: nodeType=%s, nodeDesc=%s",
                           nodeType, nodeDesc)
            continue

        # Construct output config file name.
        outCfgName  = "%02d-%s.json" % (idx, strToFileName(nodeDesc))
        outCfgPath  = os.path.join(outDir, outCfgName)
        usedCfgNames.add(outCfgName)
        logger.debug("nodeType=%s, nodeDesc=%s, outCfgPath=%s",
                     nodeType, nodeDesc, outCfgPath)

        # Get original config file content, if any.
        outCfgContentOrig = ""
        if os.path.exists(outCfgPath):
            with open(outCfgPath, "r") as outCfgFile:
                outCfgContentOrig = outCfgFile.read()

        # Write to config file if needed.
        outCfgContent = json.dumps(v2rayConfig, indent=4)
        if outCfgContent != outCfgContentOrig:
            if not dryRun:
                with open(outCfgPath, "w") as outCfgFile:
                    outCfgFile.write(outCfgContent)
            numUpdated += 1
            logger.info("%sUpdated: nodeDesc=%s, outCfgPath=%s",
                        dryRunPrefix, nodeDesc, outCfgPath)
        else:
            numAlready += 1
            logger.debug("Already up-to-date: nodeDesc=%s, outCfgPath=%s",
                         nodeDesc, outCfgPath)

    # Delete config files not used by the subscription
    cfgNameRe = re.compile(r"^\d\d-.*\.json$")
    for fileName in os.listdir(outDir):
        if fileName not in usedCfgNames and cfgNameRe.match(fileName):
            if not dryRun:
                os.remove(os.path.join(outDir, fileName))
            numDeleted += 1
            logger.info("%sDeleted: outCfgPath=%s",
                        dryRunPrefix, outCfgPath)

    logger.info("Summary: %snumUpdated=%d, %snumDeleted=%d, numAlready=%d, "
                "numSkipped=%d",
                dryRunPrefix, numUpdated, dryRunPrefix, numDeleted,
                numAlready, numSkipped)

    return 0


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Parse a v2rayN subscription link and generate json "
                    "config files for v2ray into a directory. The unused "
                    "json files in that directory will be removed.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose mode")
    parser.add_argument("-n", "--dryrun", action="store_true",
                        help="Don't modify anything on disk")
    parser.add_argument("-o", "--output", type=str, default=".",
                        help="Output directory")
    parser.add_argument("url", type=str,
                        help="v2rayN subsription link")
    args = parser.parse_args()

    # Initialize logger
    logLevel = logging.INFO
    if args.verbose:
        logLevel = logging.DEBUG
    logger.setLevel(logLevel)
    logHandler = logging.StreamHandler()
    logFormatter = logging.Formatter("[%(levelname)s]: %(message)s")
    logHandler.setFormatter(logFormatter)
    logger.addHandler(logHandler)

    # Run main function
    rc = main(args.url, args.output, args.dryrun)
    sys.exit(rc)

