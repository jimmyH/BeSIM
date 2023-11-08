import logging
import os
import sys

from udpserver import UdpServer
from restapi import app
from database import Database

if __name__ == '__main__':

  fmt = '[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s] %(levelname)s: %(message)s'
  logging.basicConfig(format=fmt,level=logging.DEBUG)

  database_name=os.getenv('BESIM_DATABASE', 'besim.db')
  database = Database(name=database_name)
  if not database.check_migrations():
    sys.exit(1) # error should already have been logged
  database.purge(365*2) # @todo currently only purging old records at startup

  udpServer = UdpServer( ('',6199) )
  udpServer.start()
  app.config['udpServer'] = udpServer

  host=os.getenv('FLASK_HOST', '0.0.0.0')
  port=os.getenv('FLASK_PORT', '80')
  debug=os.getenv('FLASK_DEBUG', False)
  app.run(debug=debug, host=host, port=int(port))
