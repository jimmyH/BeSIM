import logging
import os

from udpserver import UdpServer
from restapi import app

if __name__ == '__main__':

  fmt = '[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s] %(levelname)s: %(message)s'
  logging.basicConfig(format=fmt,level=logging.DEBUG)
  udpServer = UdpServer( ('',6199) )
  udpServer.start()
  app.config['udpServer'] = udpServer

  host=os.getenv('FLASK_HOST', '0.0.0.0')
  port=os.getenv('FLASK_PORT', '80')
  debug=os.getenv('FLASK_DEBUG', False)
  app.run(debug=debug, host=host, port=int(port))
