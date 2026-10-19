#
# This is where we store the status of any connected peers/devices
#

from typing import Dict

STATUS: Dict[str, Dict] = {"peers": {}, "devices": {}}


def getStatus():
    return STATUS


def getPeerStatus(addr):
    if addr not in STATUS["peers"]:
        STATUS["peers"][addr] = {"devices": set()}
    return STATUS["peers"][addr]


def getDeviceStatus(deviceid):
    if deviceid not in STATUS["devices"]:
        # cseq is control plane sequence number, 0..0xfd
        # results is a dict holding the results from a request
        # 'results' = { <sequence number of request sent> : { 'ev' : <threading.Event>, 'val' : <result of requested operation> }, ... }
        STATUS["devices"][deviceid] = {"rooms": {}, "cseq": 0x0, "results": {}}
    return STATUS["devices"][deviceid]


def getRoomStatus(deviceid, room):
    status = getDeviceStatus(deviceid)

    if room not in status["rooms"]:
        status["rooms"][room] = {"days": {}}
    return status["rooms"][room]
