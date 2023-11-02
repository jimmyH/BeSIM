import sqlite3
import logging
import contextlib
from enum import Enum

from typing import List
from typing import Union

logger = logging.getLogger(__name__)

class DatabaseType(Enum):
  SQLITE3 = 1,
  UNSET = 2

class DatabaseConnection:
  def __init__(self,databaseType=None,databaseName=None):
    self.databaseType = databaseType
    self.databaseName = databaseName
    self.conn = None

  def connect(self):
    if self.databaseName is not None and self.conn is None:
      self.conn = sqlite3.connect(self.databaseName)
    return self.conn

  def close(self):
    if self.conn is not None:
      self.conn.close()
      self.conn = None

  def getConn(self):
    return self.conn

  def run_sql(self,sql,values=None,log=False) -> List:
    if values is None:
      values = ()
    if log:
      logger.info(sql)
    if self.getConn() is not None:
      with contextlib.closing(self.getConn().cursor()) as cursor: # Use contextlib since sqlite3 cursors do not support __enter__
        cursor.execute(sql,values)
        if cursor.description is None: # sqlite3 will not return anything on a create/insert etc
          result = None
        else:
          cols = [ x[0] for x in cursor.description ]
          result = [ dict(zip(cols,row)) for row in cursor.fetchall() ]
      self.getConn().commit()
      if log:
        logger.info(result)
      return result
    else:
      return None

  def truncate_tables(self,tables: Union[str,List[str]],log=False) -> List:
    if not isinstance(tables,list):
      tables = [ tables ]
    for table in tables:
      if self.getDatabaseType() == DatabaseType.SQLITE3:
        sql = f"delete from {table}"
      else:
        sql = f"truncate table {table}"
      return self.run_sql(sql,log)

