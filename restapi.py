from flask import Flask, request
from flask_restful import reqparse, abort, Api, Resource
from flask_cors import CORS
import json
import time
import logging
import os
import requests
from cachetools import cached, TTLCache
from threading import RLock

from webargs import fields,validate
from webargs.flaskparser import use_kwargs,use_args

from udpserver import MsgId
from status import getStatus,getDeviceStatus,getRoomStatus
from database import Database

logger = logging.getLogger(__name__)

class SetEncoder(json.JSONEncoder):
  def default(self,o):
    if isinstance(o,set):
      return list(o)
    return json.JSONEncoder.default(self,o)

app = Flask(__name__)
CORS(app)
api = Api(app)

def getUdpServer():
  return app.config['udpServer']

@cached(cache=TTLCache(maxsize=1, ttl=3600), lock=RLock())
def getWeather():
  # Uses met.no to get the weather at the servers' latitude, longitude
  # See https://api.met.no/doc/TermsOfService and https://api.met.no/doc/License
  url = 'https://api.met.no/weatherapi/locationforecast/2.0/complete'

  # Get the lat/long from environment
  latitude = os.getenv('LATITUDE',None)
  longitude = os.getenv('LONGITUDE',None)

  if latitude is None or longitude is None:
    return { }, 500

  try:
    latitude = float(latitude)
    longitude = float(longitude)
  except ValueError:
    return { }, 500

  params = { 'lat':latitude, 'lon':longitude }
  headers = { 'User-Agent': 'BeSim/0.1 github.com/jimmyH/BeSIM' }

  r = requests.get(url,params=params,headers=headers)
  if r.status_code==200:
    js = r.json()

    temp = js['properties']['timeseries'][0]['data']['instant']['details']['air_temperature']
    Database().log_outside_temperature(temp)

    return js, 200
  else:
    return { }, r.status_code

#
# Endpoints to replicate Besmart/Cloudwarm behaviour
#

# api.besmart-home.com
@app.route('/fwUpgrade/PR06549/version.txt', methods=['GET'])
def getVersion():
  logger.debug(f'{request.args}')
  return '1+0654918011102+http://www.besmart-home.com/fwUpgrade/PR06549/0654918011102.bin'

# api.besmart-home.com
# Returns ascii temperature (degC) or E_1 for error
# The app gets the temperature autonomously, don't *think* the besmart device reports the temperature it gets from here
# The besmart device fetches the temperature hourly
@app.route('/WifiBoxInterface_vokera/getWebTemperature.php', methods=['GET'])
def getWebTemperature():
  logger.debug(f'{request.args}')
  deviceId = request.args.get('deviceId')
  weather, status_code  = getWeather()
  if status_code != 200:
    return "E_1"
  else:
    return str(round(weather['properties']['timeseries'][0]['data']['instant']['details']['air_temperature']))

# www.cloudwarm.com
#json_data={"wifi_box_id":"165XXXXXXX","start_time":"1672552802","sys_run_time":"9173915","continued_time":"3576","type":"2","value":"0"}'
@app.route('/BeSMART_test_on_cloudwarm/v1/api/gateway/boilers/records', methods=['POST'])
def postBoilerRecords():
  logger.debug(f'{request.args}')
  data = request.json
  # @todo do something with the POSTed data

#
#
#

@app.route('/')
def index():
  return "Web server is running"

#
# REST API
#

class Peers(Resource):
  def get(self):
    return json.dumps(getStatus()['peers'],cls=SetEncoder) # @todo need to make flask_restful use the custom encoder

class Devices(Resource):
  def get(self):
    return list(getStatus()['devices'].keys())

class Device(Resource):
  def get(self, deviceid):
    return getDeviceStatus(deviceid)

class Rooms(Resource):
  def get(self, deviceid):
    rooms = []
    # We only return rooms we have seen in the last 10 minutes
    for k,v in getDeviceStatus(deviceid)['rooms'].items():
      if 'lastseen' in v and v['lastseen'] > time.time()-600:
        rooms.append(k)
    return rooms

class Room(Resource):
  def get(self, deviceid, roomid):
    return getRoomStatus(deviceid,roomid)

class ReadonlyParamResource(Resource):
  def __init__(self, **kwargs):
    self.param = kwargs['param']

  def get(self, deviceid, roomid=None):
    if roomid is not None:
      return getRoomStatus(deviceid,roomid)[self.param]
    else:
      return getDeviceStatus(deviceid)[self.param]


class WriteableParamResource(Resource):
  def __init__(self, **kwargs):
    self.param = kwargs['param']
    self.msgId = kwargs['msgId']

  def get(self, deviceid, roomid):
    return getRoomStatus(deviceid,roomid)[self.param]

  def put(self, deviceid, roomid):
    data = request.json
    val = data
    addr = getDeviceStatus(deviceid)['addr']
    new_val = getUdpServer().send_SET(addr,getDeviceStatus(deviceid),deviceid,roomid,self.msgId,val,response=0,write=1,wait=1)
    if new_val!=val:
      return { 'message' : 'ERROR' }, 500
    else:
      return { 'message' : 'OK' }, 200

class FakeBoostResource(Resource):
  def get(self, deviceid, roomid):
    roomStatus = getRoomStatus(deviceid,roomid)
    return roomStatus['fakeboost']

  def put(self, deviceid, roomid):
    data = request.json
    val = data
    addr = getDeviceStatus(deviceid)['addr']
    new_val = getUdpServer().send_FAKE_BOOST(addr,getDeviceStatus(deviceid),deviceid,roomid,val)
    if new_val!=val:
      return { 'message' : 'ERROR' }, 500
    else:
      return { 'message' : 'OK' }, 200

class Days(Resource):
  def get(self, deviceid, roomid):
    return list(getRoomStatus(deviceid,roomid)['days'].keys())

class Day(Resource):
  def get(self, deviceid, roomid, dayid):
    return getRoomStatus(deviceid,roomid)['days'][dayid]

  def put(self, deviceid, roomid, dayid):
    data = request.json
    val = data
    addr = getDeviceStatus(deviceid)['addr']
    new_val = getUdpServer().send_PROGRAM(addr,getDeviceStatus(deviceid),deviceid,roomid,dayid,val,response=0,write=1,wait=1)
    if new_val!=val:
      return { 'message' : 'ERROR' }, 500
    else:
      return { 'message' : 'OK' }, 200

class TimeResource(Resource):
  def get(self, deviceid):
    val = 0
    addr = getDeviceStatus(deviceid)['addr']
    return getUdpServer().send_DEVICE_TIME(addr,getDeviceStatus(deviceid),deviceid,val,response=0,write=0,wait=1)

  def put(self, deviceid):
    data = request.json
    val = data
    addr = getDeviceStatus(deviceid)['addr']
    new_val = getUdpServer().send_DEVICE_TIME(addr,getDeviceStatus(deviceid),deviceid,val,response=0,write=1,wait=1)
    if new_val!=val:
      return { 'message' : 'ERROR' }, 500
    else:
      return { 'message' : 'OK' }, 200

class OutsideTempResource(Resource):
  def put(self, deviceid):
    data = request.json
    val = data
    addr = getDeviceStatus(deviceid)['addr']
    new_val = getUdpServer().send_OUTSIDE_TEMP(addr,getDeviceStatus(deviceid),deviceid,val,response=0,write=1,wait=1)
    if new_val!=val:
      return { 'message' : 'ERROR' }, 500
    else:
      return { 'message' : 'OK' }, 200

class Weather(Resource):
  def get(self):
    return getWeather()

class WeatherHistory(Resource):
  @use_args(
    {
      "from" : fields.Str(),
      "to" : fields.Str(),
    },
    location = "query")
  def get(self, query):
    getWeather()
    return Database().get_outside_temperature(query.get('from',None),query.get('to',None))

class TemperatureHistory(Resource):
  @use_args(
    {
      "from" : fields.Str(),
      "to" : fields.Str(),
    },
    location = "query")
  def get(self, query, deviceid, roomid):
    return Database().get_temperature(roomid,query.get('from',None),query.get('to',None))

api.add_resource(Devices,'/api/v1.0/devices', endpoint = 'devices')
api.add_resource(Device,'/api/v1.0/devices/<int:deviceid>', endpoint = 'device')

api.add_resource(Rooms,'/api/v1.0/devices/<int:deviceid>/rooms', endpoint = 'rooms')
api.add_resource(Room,'/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>', endpoint = 'room')

api.add_resource(TimeResource,'/api/v1.0/devices/<int:deviceid>/time', endpoint = 'time')
api.add_resource(OutsideTempResource,'/api/v1.0/devices/<int:deviceid>/outsidetemp', endpoint = 'outsidetemp')

api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/t1', endpoint = 't1', resource_class_kwargs = { 'param' : 't1', 'msgId' : MsgId.SET_T1 })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/t2', endpoint = 't2', resource_class_kwargs = { 'param' : 't2', 'msgId' : MsgId.SET_T2 })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/t3', endpoint = 't3', resource_class_kwargs = { 'param' : 't3', 'msgId' : MsgId.SET_T3 })

api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/tempcurve', endpoint = 'tempcurve', resource_class_kwargs = { 'param' : 'tempcurve', 'msgId' : MsgId.SET_CURVE })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/minsetp', endpoint = 'minsetp', resource_class_kwargs = { 'param' : 'minsetp', 'msgId' : MsgId.SET_MIN_HEAT_SETP })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/maxsetp', endpoint = 'maxsetp', resource_class_kwargs = { 'param' : 'maxsetp', 'msgId' : MsgId.SET_MAX_HEAT_SETP })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/units', endpoint = 'units', resource_class_kwargs = { 'param' : 'units', 'msgId' : MsgId.SET_UNITS })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/winter', endpoint = 'winter', resource_class_kwargs = { 'param' : 'winter', 'msgId' : MsgId.SET_SEASON })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/sensorinfluence', endpoint = 'sensorinfluence', resource_class_kwargs = { 'param' : 'sensorinfluence', 'msgId' : MsgId.SET_SENSOR_INFLUENCE })

api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/advance', endpoint = 'advance', resource_class_kwargs = { 'param' : 'advance', 'msgId' : MsgId.SET_ADVANCE })
api.add_resource(WriteableParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/mode', endpoint = 'mode', resource_class_kwargs = { 'param' : 'mode', 'msgId' : MsgId.SET_MODE })

api.add_resource(ReadonlyParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/boost', endpoint = 'boost', resource_class_kwargs = { 'param' : 'boost' }) # Thermostat does not support setting boost
api.add_resource(FakeBoostResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/fakeboost', endpoint = 'fakeboost') # Use fake boost to simulate boost behaviour

api.add_resource(ReadonlyParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/temp', endpoint = 'temp', resource_class_kwargs = { 'param' : 'temp' })
api.add_resource(ReadonlyParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/settemp', endpoint = 'settemp', resource_class_kwargs = { 'param' : 'settemp' })
api.add_resource(ReadonlyParamResource, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/cmdissued', endpoint = 'cmdissued', resource_class_kwargs = { 'param' : 'cmdissued' })

api.add_resource(TemperatureHistory, '/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/history', endpoint = 'temperaturehistory')

api.add_resource(Peers,'/api/v1.0/peers', endpoint = 'peers')

api.add_resource(Days,'/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/days', endpoint = 'days')
api.add_resource(Day,'/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/days/<int:dayid>', endpoint = 'day')

#api.add_resource(Weather,'/api/v1.0/weather/<float(signed=True):latitude>/<float(signed=True):longitude>', endpoint='weather')
api.add_resource(Weather,'/api/v1.0/weather', endpoint='weather')

api.add_resource(WeatherHistory,'/api/v1.0/weather/history', endpoint='history')

# OpenTherm parameters
for endpoint in [ 'boilerOn', 'dhwMode', 'tFLO', 'trEt', 'tdH', 'tFLU', 'tESt', 'MOdU', 'FLOr', 'HOUr', 'PrES', 'tFL2' ]:
  api.add_resource(ReadonlyParamResource, f'/api/v1.0/devices/<int:deviceid>/{endpoint}', endpoint=endpoint, resource_class_kwargs = { 'param' : endpoint })

#
# Following endpoint is for development only
#

class TestResource(Resource):
  @use_kwargs(
    {
      "msgId" : fields.Str(),
      "numBytes" : fields.Int(),
    },
    location = "query")
  def get(self, deviceid, roomid, msgId=None, numBytes=None):
    if msgId is not None:
      msgId = int(msgId,0)
      print(f'Setting id={id}')
    else:
      return None

    if numBytes is not None:
      print(f'Setting numBytes={numBytes}')

    val = 0
    addr = getDeviceStatus(deviceid)['addr']
    return getUdpServer().send_SET(addr,getDeviceStatus(deviceid),deviceid,roomid,msgId,val,response=0,write=0,wait=1,numBytes=numBytes)

#api.add_resource(TestResource,'/api/v1.0/devices/<int:deviceid>/rooms/<int:roomid>/test', endpoint = 'test')


if __name__ == '__main__':
  host=os.getenv('FLASK_HOST', '0.0.0.0')
  port=os.getenv('FLASK_PORT', '80')
  debug=os.getenv('FLASK_DEBUG', False)
  app.run(debug=debug, host=host, port=int(port))
