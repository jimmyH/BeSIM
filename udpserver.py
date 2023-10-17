from crccheck.crc import Crc16Xmodem
from enum import IntEnum
import time
import socket
import threading
import struct
import logging
import hexdump
import traceback

from status import getPeerStatus, getRoomStatus, getDeviceStatus, getStatus

logger = logging.getLogger(__name__)

#
# Note:
#    Downlink (DL) is from cloud server to Besmart device.
#    Uplink (UL) is from Besmart device to cloud server.
#

class MsgId(IntEnum):
  #
  # Set the thermostat mode: auto/holiday/party/off etc.
  # DL initiated
  #
  SET_MODE = 0x02

  # 0x03    Unknown (from test probe: deviceid) (invalid)
  # 0x04    Unknown (from test probe: deviceid) (invalid)
  # 0x05    Unknown (from test probe: deviceid) (invalid)
  # 0x06    Unknown (from test probe: deviceid) (invalid)
  # 0x07    Unknown (from test probe: deviceid) (invalid)
  # 0x08    Unknown (from test probe: deviceid) (invalid)
  # 0x09    Unknown (from test probe: deviceid) (invalid)

  #
  # The thermostat daily program (one message per day)
  # UL/DL initiated
  #
  PROGRAM = 0x0a

  #
  # Set the T1/T2/T3 temperatures
  # Values in degC * 10
  # DL initiated
  #
  SET_T3 = 0x0b
  SET_T2 = 0x0c
  SET_T1 = 0x0d

  # 0x0e    Unknown (from test probe: deviceid, roomid) (invalid)
  # 0x0f    Unknown (from test probe: deviceid, long message with lots of 0x0 followed by lots of 0xff) Could this be OpenTherm parameters?
  # 0x10    Unknown (from test probe: deviceid) (invalid)
  # 0x11    Unknown (from test probe: deviceid,byte=0xff)

  #
  # Enable/Disable advance on the thermostat
  # 1 = Advance
  # DL initiated
  #
  SET_ADVANCE = 0x12

  # 0x13    Unknown (from test probe: deviceid) (invalid)
  # 0x14    Unknown (from test probe: deviceid, 4 bytes = 0x0)

  #
  # Get the device software version
  # UL/DL initiated
  #
  SWVERSION = 0x15

  #
  # Set the Temperature Curve (OpenTherm only)
  # Values in degC * 10
  # DL initiated
  #
  SET_CURVE = 0x16

  #
  # Set the thermostat min/max heating setpoints (OpenTherm only)
  # Values in degC * 10
  # DL initiated
  #
  SET_MIN_HEAT_SETP = 0x17
  SET_MAX_HEAT_SETP = 0x18

  #
  # Set the units degC/degF
  # 0 = degC 1 = degF
  # DL initiated
  #
  SET_UNITS = 0x19

  #
  # Set the season heating/cooling
  # 1 = Winter
  # DL initiated
  #
  SET_SEASON = 0x1a

  #
  # Set the sensor influence (OpenTherm only)
  # Values in degC
  # DL initiated
  #
  SET_SENSOR_INFLUENCE = 0x1b

  # 0x1c    Unknown (from test probe: deviceid, roomid, byte=85)

  #
  # No idea what this message is!!
  # DL initiated
  #
  REFRESH = 0x1d

  # 0x1e    Unknown (from test probe: deviceid) (invalid)
  # 0x1f    Unknown (from test probe: deviceid) (invalid)

  #
  # Where to obtain the outside temperature: web/boiler/none (OpenTherm only)
  # 0 = none, 1 = boiler, 2 = web
  # DL initiated
  #
  OUTSIDE_TEMP = 0x20

  # 0x21    Unknown (from test probe: deviceid) (invalid)

  #
  # No idea what this message is!!!
  # UL initiated
  #
  PING = 0x22

  # 0x23    Unknown (from test probe: deviceid) (invalid)

  #
  # Periodic (every 40s) status from the device
  # UL initiated
  #
  STATUS = 0x24

  # 0x25    Unknown (from test probe: deviceid, byte=0x1)
  # 0x26    Unknown (from test probe: deviceid) (invalid)
  # 0x27    Unknown (from test probe: deviceid) (invalid)
  # 0x28    Unknown (from test probe: deviceid) (invalid)

  #
  # Set the time on the device
  # Looks like it only sets daylight savings time.
  # No idea how the device gets the actual time.
  # 1 = DST
  # DL initiated
  #
  DEVICE_TIME = 0x29

  #
  # No idea what this message is!!!
  # Sent by the device after it has sent all the daily programs
  # UL initiated
  #
  PROG_END = 0x2a

  #
  # Not sure what this message is!!!
  # But it triggers the device to send all the daily programs for the specified thermostat
  # DL initiated
  #
  GET_PROG = 0x2b

  # 0x2c    Unknown (from test probe: deviceid, short=0x1c2)
  # 0x2d    Unknown (from test probe: deviceid) (invalid)
  # 0x2e    Unknown (from test probe: deviceid) (invalid)
  # 0x30    Unknown (from test probe: deviceid) (invalid)

  #
  #  Fake ID for unknown ids
  #
  UNKNOWN_ID = 0xff

  @classmethod
  def _missing_(cls,number):
    return cls(cls.UNKNOWN_ID)

#
# Hardcoded header/footer on all messages
#
MAGIC_HEADER=0xd4fa
MAGIC_FOOTER=0xdf2d

#
# Control plane sequence numbers
#
UNUSED_CSEQ = 0xff
MAX_CSEQ = 0xfd

def NextCSeq(device,wait=0):
  current_cseq = device['cseq']
  cseq = current_cseq + 1
  if cseq>MAX_CSEQ:
    cseq = 0
  device['cseq'] = cseq

  device['results'].pop(current_cseq,None) # delete any dangling entries
  if wait:
    device['results'][current_cseq] = { 'wait' : wait, 'ev' : threading.Event(), 'val' : None }

  return current_cseq

def LastCSeq(device):
  cseq = device['cseq']
  if cseq == MAX_CSEQ:
    return 0
  return cseq - 1

def WaitCSeq(device,cseq):
  if cseq in device['results']:
    results = device['results'][cseq]
    results['ev'].wait(results['wait'])
    del device['results'][cseq]
    return results['val']

def SignalCSeq(device,cseq,val):
  if cseq in device['results']:
    device['results'][cseq]['val'] = val
    device['results'][cseq]['ev'].set()

#
# The protocol sends all messages in a UDP datagram with the following framing:
#
#  0xd4fa
#  Payload Length
#  Sequence number
#  Payload Bytes
#  16bit CRC
#  0xdf2d
#

class Frame():
  def __init__(self,payload = None):
    self.seq = None
    self.payload = payload

  def encode(self,seq=0xffffffff):
    self.seq = seq
    buf = struct.pack('<HHI', MAGIC_HEADER, len(self.payload), seq)
    buf += self.payload
    crc = Crc16Xmodem.calc(self.payload)
    buf += struct.pack('<HH', crc, MAGIC_FOOTER)
    return buf

  def decode(self,data):
    offset = 0
    hdr, length, self.seq = struct.unpack_from('<HHI',data,offset)
    offset += 8

    if hdr!=MAGIC_HEADER:
      logger.warn(f'Invalid Header {hdr=:x}')
      return None

    if len(data) != length + 12:
      logger.warn(f'Invalid Length {length=} {len(data)}')
      return None

    self.payload = data[offset:offset+length]
    offset += length
    crc, ftr = struct.unpack_from('<HH',data,offset)

    crcCalc = Crc16Xmodem.calc(self.payload)
    if crcCalc != crc:
      logger.warn(f'Invalid CRC got {crc=:x} {crcCalc=:x}')
      return None

    if ftr!=MAGIC_FOOTER:
      logger.warn(f'Invalid Footer {ftr=:x}')
      return None

    return self.payload

#
# The payload in the frame (see Frame()) uses the following wrapper
# for all the protocol messages
#
# Message Type (see MsgId definitions)
# Flags including:
#      Downlink/Uplink indicator
#      Request/Response indicator
#      Loss of Sync indicator
#      Read/Write indicator
# Length of contents
# Message contents
#

class Wrapper():
  def __init__(self,payload = None):
    self.payload = payload
    self.msgType = None
    self.downlink = None
    self.response = None
    self.write = None
    self.valid = None

    self.flags = None # for debug in case there's other useful data in here

  def decodeUL(self,data):
    offset = 0
    self.msgType, self.flags, msgLen = struct.unpack_from('<BBH',data,offset)
    offset += 4
    msgLen += 8   # Real message length

    # bits 0,3 are always 0
    # bit 1 can be 0 or 1 in uplink (not sure why)
    # bit 2 can be 0 or 1 in uplink (maybe sync indicator?)
    # bit 4 is downlink/uplink flag
    # bit 5 is valid=1/invalid=0
    # bit 6 is read=0/write=1 flag
    # bit 7 is response flag
    self.downlink = (self.flags >> 3) & 0x1

    self.valid = (self.flags >> 2) & 0x1
    self.write = (self.flags >> 1) & 0x1
    self.response = self.flags & 0x1

    self.cloudsynclost = (self.flags >> 5)&0x1

    # Check the other bits are as expected
    if (self.flags>>7) & 0x1 or (self.flags>>4) & 0x1:
      logger.warn(f'Unexpected bit 0/3 in {self.flags=:x}')

    if self.valid!=1:
      # @todo No idea if this is just unsupported message, or includes
      #       other types of errors.
      logger.error(f'Invalid Message {self.flags=:x}')

    if self.downlink!=0:
      logger.warn(f'Unexpected downlink flag')

    return data[offset:offset+msgLen]

  def encodeDL(self,msgType,response,write):
    self.msgType = msgType
    self.downlink = 1
    self.response = response
    self.cloudsynclost = 0
    self.write = write
    self.valid = 1

    # bits 0..3 are always 0 in DL
    # bit 4 is downlink/uplink flag
    # bit 5 is valid=1
    # bit 6 is read=0/write=1
    # bit 7 is response flag
    self.flags = (self.response & 0x1)

    # bit6 = 1 for write, bit6 = 0 for read
    if write:
      self.flags |= (0x1 << 1)

    # bit5 = 1 for valid, bit5 = 0 for invalid
    self.flags |= (self.valid << 2)

    self.flags |= ((self.downlink & 0x1) << 3 )

    buf = struct.pack('<BBH',self.msgType,self.flags,len(self.payload)-8)    # encoded length is -8
    buf += self.payload
    return buf

  def __str__(self):
    return f'msgType={str(MsgId(self.msgType))}({self.msgType:x}) synclost={self.cloudsynclost} downlink={self.downlink} response={self.response} write={self.write} flags={self.flags:x}'

#
# UDP Server for simulating the behaviour of the Besmart cloud server
#

class UdpServer(threading.Thread):
  MAX_DATA = 4096

  def __init__(self,addr):
    threading.Thread.__init__(self)
    self.addr = addr
    self.stop = False

  def run(self):
    logger.info('UDP server is running')
    self.sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.sock.bind(self.addr)
    while(not self.stop):
      data, addr = self.sock.recvfrom(self.MAX_DATA)
      logger.info(f'From {addr} {len(data)} bytes : {hexdump.dump(data)}')
      try:
        self.handleMsg(data,addr)
      except Exception:
        logger.error(traceback.format_exc())
        time.sleep(1)

  def send_PING(self,addr,deviceid,response=0):
    cseq = UNUSED_CSEQ
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    unk3 = 0xf43c
    payload = struct.pack('<BBHIH',cseq,unk1,unk2,deviceid,unk3)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.PING,response,write=1)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)

  def send_GET_PROG(self,addr,device,deviceid,room,response=0,wait=0):
    cseq = NextCSeq(device,wait)
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    unk3 = 0x800fe0
    payload = struct.pack('<BBHIII',cseq,unk1,unk2,deviceid, room, unk3)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.GET_PROG,response,write=0)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_SWVERSION(self,addr,device,deviceid,response=0,wait=0):
    cseq = NextCSeq(device,wait)
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    payload = struct.pack('<BBHI',cseq,unk1,unk2,deviceid)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.SWVERSION,response,write=0)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_PROGRAM(self,addr,device,deviceid,room,day,prog,response=0,write=0,wait=0):
    cseq = UNUSED_CSEQ
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    payload = struct.pack('<BBHIIH24B',cseq,unk1,unk2,deviceid,room,day,*prog)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.PROGRAM,response,write=write)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_STATUS(self,addr,deviceid,lastseen,response=0):
    cseq = UNUSED_CSEQ
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    payload = struct.pack('<BBHII',cseq,unk1,unk2,deviceid,lastseen)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.STATUS,response,write=1)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)

  def send_SET(self,addr,device,deviceid,room,msgType,value,response=0,write=0,wait=0,numBytes=None):
    cseq = NextCSeq(device,wait)
    flags = 0x0 # Always zero in DL
    unk2 = 0x0
    payload = struct.pack('<BBHII',cseq,flags,unk2,deviceid,room)

    if numBytes is None:
      numBytes = self.set_messages_payload_size(msgType)

    if numBytes==4:
      payload += struct.pack('<I',value)
    elif numBytes==2:
      payload += struct.pack('<H',value)
    elif numBytes==1:
      payload += struct.pack('<B',value)
    else:
      raise ValueError('InternalError')

    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(msgType,response,write=write)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_REFRESH(self,addr,device,deviceid,response=0,wait=0):
    cseq = NextCSeq(device,wait)
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    payload = struct.pack('<BBHI',cseq,unk1,unk2,deviceid)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.REFRESH,response,write=0)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_OUTSIDE_TEMP(self,addr,device,deviceid,val,response=0,write=0,wait=0):
    cseq = NextCSeq(device,wait)
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    unk3 = val # External Temperature Management 0 = off 1 = boiler 2 = web
    payload = struct.pack('<BBHIB',cseq,unk1,unk2,deviceid,unk3)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.OUTSIDE_TEMP,response,write=write)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_DEVICE_TIME(self,addr,device,deviceid,val,response=0,write=0,wait=0):
    cseq = NextCSeq(device,wait)
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    unk3 = val # 1 = DST?
    unk4 = 0x0
    payload = struct.pack('<BBHIII',cseq,unk1,unk2,deviceid,unk3,unk4)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.DEVICE_TIME,response,write=write)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)
    return WaitCSeq(device,cseq)

  def send_PROG_END(self,addr,deviceid,room,response=0):
    cseq = UNUSED_CSEQ
    unk1 = 0x0 # Always zero in DL
    unk2 = 0x0
    unk3 = 0xa14
    payload = struct.pack('<BBHIIH',cseq,unk1,unk2,deviceid,room,unk3)
    wrapper = Wrapper(payload=payload)
    payload = wrapper.encodeDL(MsgId.PROG_END,response,write=0)
    logger.info(f'Sending {wrapper}')
    frame = Frame(payload=payload)
    buf = frame.encode()
    logger.info(f'To {addr} {len(buf)} bytes : {hexdump.dump(buf)}')
    self.sock.sendto(buf,addr)

  def set_messages_payload_size(self,msgType):
    if msgType==MsgId.SET_T3 or msgType==MsgId.SET_T2 or msgType==MsgId.SET_T1 or msgType==MsgId.SET_MIN_HEAT_SETP or msgType==MsgId.SET_MAX_HEAT_SETP:
      return 2
    elif msgType==MsgId.SET_UNITS or msgType==MsgId.SET_SEASON or msgType==MsgId.SET_SENSOR_INFLUENCE or msgType==MsgId.SET_CURVE or msgType==MsgId.SET_ADVANCE or msgType==MsgId.SET_MODE:
      return 1
    else:
      return None

  def handleMsg(self,data,addr):

    frame = Frame()
    payload = frame.decode(data)
    seq = frame.seq
    length=len(payload)

    peerStatus = getPeerStatus(addr)
    peerStatus['seq'] = seq # @todo handle sequence number

    # Now handle the payload

    wrapper = Wrapper()
    payload = wrapper.decodeUL(payload)

    msgLen = len(payload)
    logger.info(f'{seq=} {wrapper} {length=} {msgLen=}')

    if wrapper.msgType==MsgId.STATUS:
      offset = 0
      cseq, unk1, unk2, deviceid = struct.unpack_from('<BBHI',payload,offset)
      offset += 8
      logger.info(f'{cseq=:x} {unk1=:x} {unk2=:x} {deviceid=}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      rooms_to_get_prog = set() # Set of rooms for which we need to get the current program

      for n in range(8):        # Supports up to 8 thermostats
        room, byte1, byte2, temp, settemp, t3, t2, t1, maxsetp, minsetp = struct.unpack_from('<IBBHHHHHHH',payload,offset)
        offset += 20

        mode = byte2>>4
        unk9 = byte2 & 0xf
        byte3, byte4, unk13, tempcurve, heatingsetp = struct.unpack_from('<BBHBB',payload,offset)
        offset += 6
        sensorinfluence = (byte3>>3) & 0xf
        units = (byte3>>2) & 0x1
        advance = (byte3>>1) & 0x1
        boost = (byte4>>2) & 0x1
        cmdissued = (byte4>>1) & 0x1
        winter = byte4 & 0x1

        # Assume that if byte1 is zero, then no thermostat is connected for that room
        if byte1!=0:
          logger.info(f'{room=:x} {byte1=:x} {mode=} {temp=} {settemp=} {t3=} {t2=} {t1=} {maxsetp=} {minsetp=} {sensorinfluence=} {units=} {advance=} {boost=} {cmdissued=} {winter=} {tempcurve=} {heatingsetp=}')
          if byte1==0x8f:
            heating = 1
          elif byte1==0x83:
            heating = 0
          else:
            logger.warn(f'Unexpected {byte1=:x}')
            heating = None

          roomStatus = getRoomStatus(deviceid,room)

          roomStatus['heating'] = heating
          roomStatus['temp'] = temp
          roomStatus['settemp'] = settemp
          roomStatus['t3'] = t3
          roomStatus['t2'] = t2
          roomStatus['t1'] = t1
          roomStatus['maxsetp'] = maxsetp
          roomStatus['minsetp'] = maxsetp
          roomStatus['mode'] = mode
          roomStatus['tempcurve'] = tempcurve
          roomStatus['heatingsetp'] = heatingsetp
          roomStatus['sensorinfluence'] = sensorinfluence
          roomStatus['units'] = units
          roomStatus['advance'] = advance
          roomStatus['boost'] = boost
          roomStatus['cmdissued'] = cmdissued
          roomStatus['winter'] = winter

          roomStatus['lastseen'] = int(time.time())

          if len(roomStatus['days'])!=7 or wrapper.cloudsynclost:
            rooms_to_get_prog.add(room)

      # OpenTherm parameters
      # From the manual we expect the following to be present somewhere:
      # tSEt = set-point flow temperature calculated by the thermostat.
      # tFLO = reading of the boiler flow sensor temperature.
      # trEt = reading of the boiler return sensor temperature.
      # tdH = reading of the boiler DHW sensor temperature.
      # tFLU = reading of the boiler flues sensor temperature.
      # tESt = reading of the boiler outdoor sensor temperature (fitted to the boiler or
      # communicated by the web).
      # MOdU = instantaneous percentage of modulation of boiler fan.
      # FLOr = instantaneous domestic hot water flow rate.
      # HOUr = hours worked in high condensation mode.
      # PrES = central heating system pressure.
      # tFL2 = reading of the heating flow sensor on second circuit

      otFlags1, otFlags2 = struct.unpack_from('<BB',payload,offset)
      offset += 2

      boilerHeating = (otFlags1>>5) & 0x1
      dhwMode = (otFlags1>>6) & 0x1

      deviceStatus['boilerOn'] = boilerHeating
      deviceStatus['dhwMode'] = dhwMode

      otUnk1, otUnk2, tFLO, otUnk4, tdH, tESt, otUnk7, otUnk8, otUnk9, otUnk10 = struct.unpack_from('<HHHHHHHHHH',payload,offset)
      offset += 20

      deviceStatus['tFLO'] = tFLO
      deviceStatus['tdH'] = tdH
      deviceStatus['tESt'] = tESt

      # Other params

      wifisignal, unk16, unk17, unk18, unk19, unk20 = struct.unpack_from('<BBHHHH',payload,offset)
      offset += 10

      deviceStatus['wifisignal'] = wifisignal
      deviceStatus['lastseen'] = int(time.time())

      logger.info(getStatus())

      # Send a DL STATUS message
      self.send_STATUS(addr,deviceid,deviceStatus['lastseen'],response=1)

      if wrapper.cloudsynclost:
        #time.sleep(1) # embedded device may not handle lots of messages in a short time
        #self.send_SWVERSION(addr,deviceStatus,deviceid,response=0)
        #time.sleep(1) # embedded device may not handle lots of messages in a short time
        #self.send_REFRESH(addr,deviceStatus,deviceid,response=0)
        #time.sleep(1) # embedded device may not handle lots of messages in a short time
        #self.send_DEVICE_TIME(addr,deviceStatus,deviceid,response=0)
        pass

      # Fetch updated program for any rooms in rooms_to_get_prog set
      for room in rooms_to_get_prog:
        time.sleep(1) # embedded device may not handle lots of messages in a short time
        self.send_GET_PROG(addr,deviceStatus,deviceid,room,response=0)

    elif wrapper.msgType==MsgId.GET_PROG:
      offset = 0
      cseq, unk1, unk2, deviceid, room, unk3 = struct.unpack_from('<BBHIII',payload,offset)
      offset += 16

      logger.info(f'{deviceid=} {room=}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      if cseq != LastCSeq(deviceStatus):
        logger.warn(f'Unexpected {cseq=:x}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 1:
        logger.warn(f'Unexpected {unk2=:x}')

      if unk3 != 0x800fe0:
        logger.warn(f'Unexpected {unk3=:x}')

      if wrapper.response:
        SignalCSeq(deviceStatus,cseq,unk3) # @todo Is there any meaningful data in the response?

    elif wrapper.msgType==MsgId.PING:
      offset = 0
      cseq, unk1, unk2, deviceid, unk3 = struct.unpack_from('<BBHIH',payload,offset)
      offset += 10

      logger.info(f'{deviceid=}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      if cseq != UNUSED_CSEQ:
        logger.warn(f'Unexpected {cseq=}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      # on uplink unk2 is usually 4, but can be zero (when out of sync?)
      if unk2 != 4 and unk2 != 0:
        logger.warn(f'Unexpected {unk2=:x}')

      if unk3 != 1:
        logger.warn(f'Unexpected {unk3=:x}')

      # Send a DL PING message
      self.send_PING(addr,deviceid,response=1)

    elif wrapper.msgType==MsgId.REFRESH:
      offset = 0
      cseq, unk1, unk2, deviceid = struct.unpack_from('<BBHI',payload,offset)
      offset += 8
      # Padding at end ??
      logger.info(f'{deviceid=}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      if cseq != LastCSeq(deviceStatus):
        logger.warn(f'Unexpected {cseq}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 0x1:
        logger.warn(f'Unexpected {unk2=:x}')

      if wrapper.response:
        SignalCSeq(deviceStatus,cseq,unk2) # @todo Is there any meaninngful data in the response?

    elif wrapper.msgType==MsgId.DEVICE_TIME:
      offset = 0
      # It looks like only the 1st byte in DEVICE_TIME is valid
      # 0 = no dst 1 = dst ?
      # The rest of the payload appears to be garbage?
      cseq, unk1, unk2, deviceid, val, unk3, unk4, unk5 = struct.unpack_from('<BBHIBBHI',payload,offset)
      offset += 16
      logger.info(f'{deviceid=} {val=}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      if cseq != LastCSeq(deviceStatus):
        logger.warn(f'Unexpected {cseq=}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 0x1:
        logger.warn(f'Unexpected {unk2=:x}')

      if unk3 != 0x0:
        logger.warn(f'Unexpected {unk3=:x}')

      if unk4 != 0x0:
        logger.warn(f'Unexpected {unk4=:x}')

      if unk5 != 0x0:
        logger.warn(f'Unexpected {unk5=:x}')

      if wrapper.response:
        SignalCSeq(deviceStatus,cseq,val)

    elif wrapper.msgType==MsgId.OUTSIDE_TEMP:
      offset = 0
      cseq, unk1, unk2, deviceid, val = struct.unpack_from('<BBHIB',payload,offset)
      offset += 9

      logger.info(f'{deviceid=} {val=}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      if cseq != LastCSeq(deviceStatus):
        logger.warn(f'Unexpected {cseq=}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 0x1:
        logger.warn(f'Unexpected {unk2=:x}')

      # val  = 0x0 means no external temperature management
      #        0x1 means boiler external temperature management
      #      = 0x2 means web external temperature management

      if wrapper.response:
        SignalCSeq(deviceStatus,cseq,val)

    elif wrapper.msgType==MsgId.PROG_END:
      offset = 0
      cseq, unk1, unk2, deviceid, room, unk3 = struct.unpack_from('<BBHIIH',payload,offset)
      offset += 14
      logger.info(f'{deviceid=} {room=} {unk3=:x}')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      if cseq != UNUSED_CSEQ:
        logger.warn(f'Unexpected {cseq=}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 0x1:
        logger.warn(f'Unexpected {unk2=:x}')

      if unk3 != 0xa14:
        logger.warn(f'Unexpected {unk3=:x}')

      # Send a PROG_END
      if wrapper.response!=1:
        self.send_PROG_END(addr,deviceid,room,response=1)

    elif wrapper.msgType==MsgId.SWVERSION:
      offset = 0
      cseq, unk1, unk2, deviceid, version = struct.unpack_from('<BBHI13s',payload,offset)
      offset += 21
      logger.info(f'{deviceid=} {version=}')
      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      deviceStatus['version'] = str(version)

      if cseq != LastCSeq(deviceStatus):
        logger.warn(f'Unexpected {cseq=}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 1:
        logger.warn(f'Unexpected {unk2=:x}')

      if wrapper.response!=1:
        self.send_SWVERSION(addr,deviceStatus,deviceid,response=1)
      else:
        SignalCSeq(deviceStatus,cseq,str(version))

    elif wrapper.msgType==MsgId.PROGRAM:
      offset = 0
      cseq, unk1, unk2, deviceid, room, day = struct.unpack_from('<BBHIIH',payload,offset)
      offset += 14
      prog = []
      for i in range(24):
        p, = struct.unpack_from('<B',payload,offset)
        offset += 1
        prog.append(p)
      logger.info(f'{deviceid=} {room=} {day=} prog={ [ hex(l) for l in prog ] }')

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      roomStatus = getRoomStatus(deviceid,room)
      roomStatus['days'][day] = prog
      logger.info(getStatus())

      if cseq != UNUSED_CSEQ:
        logger.warn(f'Unexpected {cseq=}')

      if unk1 != 0x2:
        logger.warn(f'Unexpected {unk1=:x}')

      if unk2 != 1:
        logger.warn(f'Unexpected {unk2=:x}')

      # Send a DL PROGRAM message
      if wrapper.response!=1:
        self.send_PROGRAM(addr,deviceStatus,deviceid,room,day,prog,response=1)

    elif self.set_messages_payload_size(wrapper.msgType) is not None:
      offset = 0

      cseq, flags, unk2, deviceid, room = struct.unpack_from('<BBHII',payload,offset)
      offset += 12

      numBytes = self.set_messages_payload_size(wrapper.msgType)

      if numBytes==4:
        value, = struct.unpack_from('<I',payload,offset)
        offset+=numBytes
      elif numBytes==2:
        value, = struct.unpack_from('<H',payload,offset)
        offset+=numBytes
      elif numBytes==1:
        value, = struct.unpack_from('<B',payload,offset)
        offset+=numBytes
      else:
        logger.warn(f'Unrecognised MsgType {wrapper.msgType:x}')
        value = None

      deviceStatus = getDeviceStatus(deviceid)
      peerStatus['devices'].add(deviceid)
      deviceStatus['addr'] = addr

      roomStatus = getRoomStatus(deviceid,room)

      logger.info(f'{cseq=} {deviceid=} {room=} {value=}')

      # Update the device status with the updated value
      if wrapper.msgType == MsgId.SET_T1:
        roomStatus['t1'] = value
      elif wrapper.msgType == MsgId.SET_T2:
        roomStatus['t2'] = value
      elif wrapper.msgType == MsgId.SET_T3:
        roomStatus['t3'] = value
      elif wrapper.msgType == MsgId.SET_MIN_HEAT_SETP:
        roomStatus['minsetp'] = value
      elif wrapper.msgType == MsgId.SET_MAX_HEAT_SETP:
        roomStatus['maxsetp'] = value
      elif wrapper.msgType == MsgId.SET_UNITS:
        roomStatus['units'] = value
      elif wrapper.msgType == MsgId.SET_SEASON:
        roomStatus['winter'] = value
      elif wrapper.msgType == MsgId.SET_ADVANCE:
        roomStatus['advance'] = value
      elif wrapper.msgType == MsgId.SET_MODE:
        roomStatus['mode'] = value
      elif wrapper.msgType == MsgId.SET_SENSOR_INFLUENCE:
        roomStatus['sensorinfluence'] = value
      elif wrapper.msgType == MsgId.SET_CURVE:
        roomStatus['tempcurve'] = value

      if unk2 != 0x1:
        logger.warn(f'Unexpected {unk2=:x}')

      if wrapper.downlink and flags != 0x0:
        logger.warn(f'Unexpected {flags=:x} for downlink')

      if not wrapper.downlink and ( flags != 0x0 and flags != 0x2):
        logger.warn(f'Unexpected {flags=:x} for uplink')

      # Send a DL SET message if this was initiated by the device
      if value is not None:
        if wrapper.response!=1:
          self.send_SET(addr,device,deviceid,room,wrapper.msgType,value,response=1)
        else:
          SignalCSeq(deviceStatus,cseq,value)

    else:
      logger.warn(f'Unhandled message {wrapper.msgType}')

    if offset!=msgLen:
      # Check we have consumed the complete message we received
      logger.warn(f'Internal error {offset=} {msgLen=}')

if __name__ == '__main__':
  udpServer = UdpServer( ('',6199) )
  udpServer.start()
