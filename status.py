#
# This is where we store the status of any connected peers/devices
#
Status = { 'peers' : {}, 'devices' : {} }

def getStatus():
  return Status

def getPeerStatus(addr):
  if addr not in Status['peers']:
    Status['peers'][addr] = { 'devices' : set() }
  return Status['peers'][addr]

def getDeviceStatus(deviceid):
  if deviceid not in Status['devices']:
    # cseq is control plane sequence number, 0..0xfd
    # results is a dict holding the results from a request
    # 'results' = { <sequence number of request sent> : { 'ev' : <threading.Event>, 'val' : <result of requested operation> }, ... }
    Status['devices'][deviceid]={ 'rooms' : {}, 'cseq' : 0x0, 'results' : {} }
  return Status['devices'][deviceid]

def getRoomStatus(deviceid,room):
  deviceStatus = getDeviceStatus(deviceid)
  if room not in deviceStatus['rooms']:
    deviceStatus['rooms'][room] = { 'days' : {} }
  return deviceStatus['rooms'][room]
