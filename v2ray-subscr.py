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


def parseVmessSubscr(urlParseRes):
    """
    Parse a VMESS subscription url.
    @urlParseRes: the result of urllib.parse.urlparse().
    @verbose: verbose mode.
    @return: <dict>.
    """
    assert urlParseRes.scheme == "vmess"
    encNodeConfigText = urlParseRes.netloc
    encNodeConfigBytes = encNodeConfigText.encode("ascii")
    decNodeConfigBytes = base64.b64decode(encNodeConfigBytes)
    decNodeConfigText = decNodeConfigBytes.decode("utf-8")
    logger.debug("VMESS node config text: %s", decNodeConfigText)
    nodeConfig = json.loads(decNodeConfigText)
    logger.debug("VMESS node config: %s", repr(nodeConfig))
    return nodeConfig


def parseVlessSubscr(urlParseRes):
    """
    Parse a VLESS subscription url.
    https://github.com/XTLS/Xray-core/issues/91
    @urlParseRes: the result of urllib.parse.urlparse().
    @verbose: verbose mode.
    @return: nodeConfig <dict>.
    """
    assert urlParseRes.scheme == "vless" or urlParseRes.scheme == "trojan"
    nodeConfig = {}

    m = re.match(r"^([-\da-f]+)@([^:]+):(\d+)$", urlParseRes.netloc)
    nodeConfig["n_uuid"] = m[1]
    nodeConfig["n_host"] = m[2]
    nodeConfig["n_port"] = int(m[3])

    # In a query string, a key may have multiple values. So the format of
    # qsParseRes is: {key1: [vals1], key2: [vals2], ...}
    qsParseRes = urllib.parse.parse_qs(urlParseRes.query, keep_blank_values=True)
    for qk, qv in qsParseRes.items():
        k = "q_" + qk
        v = qv[0]
        assert len(qv) >= 1
        if len(qv) > 1:
            logger.warning("Query string key '%s' has multiple values: %s",
                           qk, str(qv))
        nodeConfig[k] = v

    logger.debug("VLESS node config: %s", repr(nodeConfig))
    return nodeConfig


def parseV2rayNSubscr(url, userAgent):
    """
    Get the content of a v2rayN subscribe link.
    @userAgent: if not empty, override the default user agent.
    @return: array of (type<string>, desc<string>, config<dict>)
    """

    # Get the content of subscription link
    logger.debug("Getting the content of v2rayN subscription link %s...", url)
    request = urllib.request.Request(url)
    if userAgent:
        request.add_header("User-Agent", userAgent)
    with urllib.request.urlopen(request, timeout=20) as response:
        encBytes = response.read()
    decBytes = base64.b64decode(encBytes)
    decText = decBytes.decode("utf-8")
    lines = decText.splitlines()
    lines = filter(None, lines)   # Remove empty lines

    # Parse each line of the subscription
    ret = []
    for line in lines:
        logger.debug("v2rayN subscription line: %s", line)
        urlParseRes = urllib.parse.urlparse(line)
        logger.debug("URL parse result: %s", repr(urlParseRes))
        nodeType = urlParseRes.scheme
        nodeConfig = None
        if nodeType == "vmess":
            nodeConfig = parseVmessSubscr(urlParseRes)
        elif nodeType == "vless" or nodeType == "trojan":
            nodeConfig = parseVlessSubscr(urlParseRes)

        desc = "<unknown>"
        if nodeType == "vmess":
            desc = nodeConfig["ps"]
        elif nodeType == "vless" or nodeType == "trojan":
            desc = urlParseRes.fragment

        ret.append((nodeType, desc, nodeConfig))

    return ret


def genVmessStreamSettings(nodeConfig):
    """
    Generate "streamSettings" object for VMESS.
    https://www.v2fly.org/config/transport.html#streamsettingsobject
    @nodeConfig: <dict>
    @return: <dict> or None
    """
    ret = {}
    ret["network"] = nodeConfig["net"]
    ret["security"] = nodeConfig["tls"]
    if ret["security"] == "":
        ret["security"] = "none"

    if ret["security"] == "tls":
        ret["tlsSettings"] = {
            "serverName": nodeConfig["host"],
        }
    elif ret["security"] == "none":
        pass
    else:
        logger.warning("Failed to generate streamSettings: "
                       "security=%s is unsupported",
                       ret["security"])
        return None

    if ret["network"] == "tcp":
        pass
    elif ret["network"] == "ws":
        ret["wsSettings"] = {
            "path": nodeConfig["path"],
        }
    else:
        logger.warning("Failed to generate streamSettings: "
                       "network=%s is unsupported",
                       ret["network"])
        return None

    return ret;


def genVlessStreamSettings(nodeConfig):
    """
    Generate "streamSettings" object for VLESS.
    https://www.v2fly.org/config/transport.html#streamsettingsobject
    @nodeConfig: <dict>
    @return: <dict> or None
    """
    ret = {}
    ret["network"] = nodeConfig["q_type"]
    ret["security"] = nodeConfig["q_security"]

    if ret["security"] == "tls":
        if "q_sni" in nodeConfig and nodeConfig["q_host"] != nodeConfig["q_sni"]:
            logger.warning("'host' and 'sni' not match for %s@%s:%d",
                           nodeConfig["n_uuid"], nodeConfig["n_host"],
                           nodeConfig["n_port"])
        ret["tlsSettings"] = {
            "serverName": nodeConfig["q_host"],
        }
    elif ret["security"] == "xtls":
        if "q_sni" in nodeConfig and nodeConfig["q_host"] != nodeConfig["q_sni"]:
            logger.warning("'host' and 'sni' not match for %s@%s:%d",
                           nodeConfig["n_uuid"], nodeConfig["n_host"],
                           nodeConfig["n_port"])
        ret["xtlsSettings"] = {
            "serverName": nodeConfig["q_host"],
        }
    else:
        logger.warning("Failed to generate streamSettings: " +
                       "security=%s is unsupported",
                       ret["security"])
        return None

    if ret["network"] == "tcp":
        pass
    elif ret["network"] == "ws":
        ret["wsSettings"] = {
            "path": nodeConfig["q_path"],
        }
    else:
        logger.warning("Failed to generate streamSettings: " +
                       "network=%s is unsupported",
                       ret["network"])
        return None

    return ret;


def nodeConfigToV2rayConfig(nodeType, nodeConfig):
    """
    @nodeType: <string>
    @nodeConfig: <dict>
    @return: <dict> or None
    """
    ret = {}

    if nodeType == "vmess":
        streamSettings = genVmessStreamSettings(nodeConfig)
        if not streamSettings:
            return None
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
                "streamSettings": streamSettings,
            },
        ]
    elif nodeType == "vless":
        streamSettings = genVlessStreamSettings(nodeConfig)
        if not streamSettings:
            return None
        ret["outbounds"] = [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": nodeConfig["n_host"],
                            "port": nodeConfig["n_port"],
                            "users": [
                                {
                                    "id": nodeConfig["n_uuid"],
                                    "encryption": nodeConfig["q_encryption"],
                                    "flow": nodeConfig["q_flow"],
                                },
                            ],
                        }
                    ],
                },
                "streamSettings": streamSettings,
            },
        ]
    elif nodeType == "trojan":
        streamSettings = genVlessStreamSettings(nodeConfig)
        if not streamSettings:
            return None
        ret["outbounds"] = [
            {
                "protocol": "trojan",
                "settings": {
                    "servers": [
                        {
                            "address": nodeConfig["n_host"],
                            "port": nodeConfig["n_port"],
                            "password": nodeConfig["n_uuid"],
                            "flow": nodeConfig["q_flow"],
                        }
                    ],
                },
                "streamSettings": streamSettings,
            },
        ]
    else:
        logger.warning("Unsupported nodeType=%s", nodeType)
        return None

    return ret


def writeJsonFile(path, content, dryRun=False):
    """
    Write JSON string into a file. If the file already exists, check its
    content, only update it when the original content is different from
    current content.
    @path: JSON file path
    @content: JSON content <dict>
    @return: whether the file is updated or not <bool>
    """
    dryRunPrefix = ""
    if dryRun:
        dryRunPrefix = "(dryrun) "

    # Get original config file content, if any.
    outCfgContentOrig = ""
    if os.path.exists(path):
        with open(path, "r") as outCfgFile:
            outCfgContentOrig = outCfgFile.read()

    # Write to config file if needed.
    outCfgContent = json.dumps(content, indent=4)
    if outCfgContent != outCfgContentOrig:
        if not dryRun:
            with open(path, "w") as outCfgFile:
                outCfgFile.write(outCfgContent)
        logger.info("%sUpdated: outCfgPath=%s", dryRunPrefix, path)
        return True
    else:
        logger.debug("Already up-to-date: outCfgPath=%s", path)
        return False


def overrideServerWithTlsName(v2rayConfig):
    """
    Override the server address with the TLS serverName. This may solve
    some connection issues.
    @v2rayConfig: result of v2rayConfig <dict>
    @return: <dict> if overridden, or None if TLS name doesn't exist.
        The returned dict is a copy of @v2rayConfig, which means the
        original dict won't be modified.
    """
    ret = None
    streamSettings = v2rayConfig["outbounds"][0]["streamSettings"]
    tlsName = ""
    if streamSettings["security"] == "tls":
        tlsName = streamSettings["tlsSettings"]["serverName"]
    elif streamSettings["security"] == "xtls":
        tlsName = streamSettings["xtlsSettings"]["serverName"]

    if tlsName:
        ret = copy.deepcopy(v2rayConfig)
        if "vnext" in ret["outbounds"][0]["settings"]:
            ret["outbounds"][0]["settings"]["vnext"][0]["address"] = tlsName
        elif "servers" in ret["outbounds"][0]["settings"]:
            ret["outbounds"][0]["settings"]["servers"][0]["address"] = tlsName
        else:
            return None

    return ret


def main(url, outDir, userAgent="", tlsNameAsServer=False, dryRun=False):
    """
    Fetch url, generate json config files, remove unused config files.
    @url: <string>
    @outDir: <string>
    @userAgent: the user agent string used to send HTTP requests
    @tlsNameAsServer: Generate a copy of the original config, where the
        server address is overridden by the TLS serverName. This may fix
        some connection issues.
    @dryRun: <bool>
    """
    # Create output directory
    os.makedirs(outDir, exist_ok=True)

    # Fetch url.
    parseResults = parseV2rayNSubscr(url, userAgent)
    dryRunPrefix = ""
    if dryRun:
        dryRunPrefix = "(dryrun) "

    # Some stats.
    numSkipped   = 0
    numUpdated   = 0
    numAlready   = 0
    numDeleted   = 0
    usedCfgNames = set()

    # For each node, generate json config file(s).
    idx = 0
    for res in parseResults:
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
        outCfgName  = "%03d-%s.json" % (idx, strToFileName(nodeDesc))
        idx += 1
        outCfgPath  = os.path.join(outDir, outCfgName)
        usedCfgNames.add(outCfgName)
        logger.debug("nodeType=%s, nodeDesc=%s, outCfgPath=%s",
                     nodeType, nodeDesc, outCfgPath)

        # Write to the output config file.
        updated = writeJsonFile(outCfgPath, v2rayConfig, dryRun)
        if updated:
            numUpdated += 1
        else:
            numAlready += 1

        # Generate a copy of the original config file, with server address
        # overridden by the TLS serverName.
        if tlsNameAsServer:
            newV2rayConfig = overrideServerWithTlsName(v2rayConfig)
            if newV2rayConfig:
                outCfgName  = "%03d-%s-tlsServ.json" % (idx, strToFileName(nodeDesc))
                idx += 1
                outCfgPath  = os.path.join(outDir, outCfgName)
                usedCfgNames.add(outCfgName)
                logger.debug("nodeType=%s, nodeDesc=%s, outCfgPath=%s",
                             nodeType, nodeDesc, outCfgPath)
                updated = writeJsonFile(outCfgPath, newV2rayConfig, dryRun)
                if updated:
                    numUpdated += 1
                else:
                    numAlready += 1

    # Delete config files not used by the subscription
    cfgNameRe = re.compile(r"^\d\d\d-.*\.json$")
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
    parser.add_argument("-a", "--agent", type=str, default="",
                        help="User agent for the HTTP request")
    parser.add_argument("--tlsNameAsServer", action="store_true",
                        help="Generate a copy of the original config, where "
                             "the server address is overridden by the TLS "
                             "serverName. This may fix some connection issues. "
                             "The copy will have '-tlsServ.json' suffix.")
    parser.add_argument("url", type=str,
                        help="v2rayN subsription link")
    args = parser.parse_args()

    # Initialize logger
    logLevel = logging.INFO
    if args.verbose:
        logLevel = logging.DEBUG
    logger.setLevel(logLevel)
    logHandler = logging.StreamHandler()
    logFormatter = logging.Formatter("[%(levelname)s] %(message)s")
    logHandler.setFormatter(logFormatter)
    logger.addHandler(logHandler)

    logger.debug("args=%s", repr(args))

    # Run main function
    rc = main(args.url, args.output, args.agent, args.tlsNameAsServer,
              args.dryrun)
    sys.exit(rc)

