import logging

from udpserver import UdpServer
from restapi import app

if __name__ == '__main__':

  fmt = '[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s] %(levelname)s: %(message)s'
  logging.basicConfig(format=fmt,level=logging.DEBUG)
  udpServer = UdpServer( ('',6199) )
  udpServer.start()
  app.config['udpServer'] = udpServer
  app.run(debug=False, host='0.0.0.0', port=80)
