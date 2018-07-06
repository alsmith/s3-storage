import cherrypy
import pymysql
import time

class DatabaseCursor():
    def __init__(self, cursorClass=pymysql.cursors.DictCursor, maxErrors=5, autoCommit=True, logQueries=False):
        self.errorCount = 0
        self.cursorClass = cursorClass
        self.maxErrors = maxErrors
        self.autoCommit = autoCommit
        self.logQueries = logQueries

    def __enter__(self):
        self.cursor = self.testConnection()
        return self

    def __exit__(self, type, value, traceback):
        if self.autoCommit:
            self.cursor.execute('COMMIT')
        self.cursor.close()

    def __iter__(self):
        return self.cursor.__iter__()

    def next(self):
        return self.cursor.next()

    def connectToDatabase(self):
        return pymysql.connect(cursorclass=self.cursorClass, **cherrypy.thread_data.db['parameters'])

    def testConnection(self):
        if not cherrypy.thread_data.db['parameters']:
            return None

        while True:
            try:
                if 'connection' not in cherrypy.thread_data.db:
                    cherrypy.thread_data.db['connection'] = self.connectToDatabase()
                cursor = cherrypy.thread_data.db['connection'].cursor()
                cursor.execute('SELECT 0')
                cursor.fetchall()
                if self.errorCount > 0:
                    cherrypy.log(msg='Database connection restored', context='MYSQL')
                    self.errorCount = 0
                break
            except Exception as e:
                self.errorCount += 1
                cherrypy.log(msg='%s failure%s: %s' % (self.errorCount, '' if self.errorCount == 1 else 's', str(e)), context='MYSQL')
                if self.maxErrors is not None and self.errorCount == self.maxErrors:
                    raise
                if 'connection' in cherrypy.thread_data.db:
                    try:
                        cherrypy.thread_data.db['connection'].close()
                    except:
                        pass
                    del cherrypy.thread_data.db['connection']
                time.sleep(2)
        return cursor

    def execute(self, *args, **kwargs):
        start = time.time()
        rc = self.cursor.execute(*args, **kwargs)
        if self.logQueries:
            cherrypy.log(msg='%.3fs: %s' % (time.time()-start, args), context='CURSOR-EXECUTE')
        return rc

    def fetchall(self, *args, **kwargs):
        start = time.time()
        rc = self.cursor.fetchall(*args, **kwargs)
        if self.logQueries:
            cherrypy.log(msg='%.3fs: %s' % (time.time()-start, args), context='CURSOR-FETCHALL')
        return rc

    def fetchone(self, *args, **kwargs):
        start = time.time()
        rc = self.cursor.fetchone(*args, **kwargs)
        if self.logQueries:
            cherrypy.log(msg='%.3fs: %s' % (time.time()-start, args), context='CURSOR-FETCHONE')
        return rc

    def lastrowid(self):
        return self.cursor.lastrowid

    def rowcount(self):
        return self.cursor.rowcount

