import logging
from databaseConnection import DatabaseType,DatabaseConnection
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

class Database(metaclass=Singleton):

  def __init__(self,name,log=False):
    self.name = name
    self.log = log

  def create_tables(self,conn=None):
    if not conn:
      conn = self.get_connection()
      closeit = True
    else:
      closeit = False
    sql = "create table if not exists besim_outside_temperature(ts DATETIME, temp NUMERIC)"
    conn.run_sql(sql,log=self.log)
    sql = "create table if not exists besim_temperature(ts DATETIME, thermostat TEXT, temp NUMERIC, settemp NUMERIC)"
    conn.run_sql(sql,log=self.log)
    if closeit:
      conn.close()

  def get_connection(self):
    dbConnection = DatabaseConnection(DatabaseType.SQLITE3,self.name)
    dbConnection.connect()
    return dbConnection

  def log_outside_temperature(self,temp,conn=None):
    if not conn:
      conn = self.get_connection()
      closeit = True
    else:
      closeit = False
    now = datetime.now(timezone.utc).astimezone().isoformat()
    sql = "insert into besim_outside_temperature(ts, temp) values (?,?)"
    values = (now,temp)
    conn.run_sql(sql,values,log=self.log)
    if closeit:
      conn.close()

  def log_temperature(self,thermostat,temp,settemp,conn=None):
    if not conn:
      conn = self.get_connection()
      closeit = True
    else:
      closeit = False
    now = datetime.now(timezone.utc).astimezone().isoformat()
    sql = "insert into besim_temperature(ts, thermostat, temp, settemp) values (?,?,?,?)"
    values = (now,thermostat,temp,settemp)
    conn.run_sql(sql,values,log=self.log)
    if closeit:
      conn.close()

  def purge(self,daysToKeep,conn=None):
    if not conn:
      conn = self.get_connection()
      closeit = True
    else:
      closeit = False
    now = datetime.now(timezone.utc).astimezone()
    limit = now - timedelta(days=daysToKeep)
    sql = "delete from besim_outside_temperature where ts < '" + limit.isoformat() + "'"
    conn.run_sql(sql,log=self.log)
    sql = "delete from besim_temperature where ts < '" + limit.isoformat() + "'"
    conn.run_sql(sql,log=self.log)
    if closeit:
      conn.close()

  def get_outside_temperature(self,date_from=None,date_to=None,conn=None):
    if date_from is None:
      date_from = (datetime.now(timezone.utc).astimezone() - timedelta(days=14)).isoformat()
    if date_to is None:
      date_to = datetime.now(timezone.utc).astimezone().isoformat()

    if not conn:
      conn = self.get_connection()
      closeit = True
    else:
      closeit = False
    sql = "select ts,temp from besim_outside_temperature where ts between ? and ?"
    values = (date_from,date_to)
    rc = conn.run_sql(sql,values,log=self.log)
    if closeit:
      conn.close()
    return rc

  def get_temperature(self,thermostat,date_from=None,date_to=None,conn=None):
    if date_from is None:
      date_from = (datetime.now(timezone.utc).astimezone() - timedelta(days=14)).isoformat()
    if date_to is None:
      date_to = datetime.now(timezone.utc).astimezone().isoformat()

    if not conn:
      conn = self.get_connection()
      closeit = True
    else:
      closeit = False
    sql = "select ts,temp,settemp from besim_temperature where thermostat = ? and ts between ? and ?"
    values = (thermostat,date_from,date_to)
    rc = conn.run_sql(sql,values,log=self.log)
    if closeit:
      conn.close()
    return rc

