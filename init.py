import argparse
import cherrypy
import os
import socket

class Root():
    favicon_ico = None

class StubbornDBBackgroundTask(cherrypy.process.plugins.BackgroundTask):
    """
    The CherryPy default background task class quits at the first sign of an
    exception. We don't want that, so let's subclass it and overload it and
    don't just reraise the exception but carry on trying to run our function.
    """
    def __init__(self, db, interval, function, args=[], kwargs={}, bus=None):
        super(StubbornDBBackgroundTask, self).__init__(interval, function, args, kwargs, bus)
        self.db = db

    def run(self):
        cherrypy.thread_data.db = self.db()
        self.running = True
        while self.running:
            time.sleep(self.interval)
            if not self.running:
                return
            try:
                self.function(*self.args, **self.kwargs)
            except Exception as e:
                cherrypy.log(msg='Error in background task function: %s' % traceback.format_exc(), context='BACKGROUND')

class Init():
    def __init__(self, service, sourceFile):
        self.service = service
        self.sourceFile = sourceFile

        parser = argparse.ArgumentParser(usage='usage: %s' % os.path.basename(self.sourceFile))

        parser.add_argument('--foreground', action='store_true', help='Don\'t daemonize')
        parser.add_argument('--config', default=os.path.join(os.path.dirname(self.sourceFile), 'config.ini'), help='Path to config.ini')
        args = parser.parse_args()

        if not args.config:
            print('config.ini file not specified')
            return 1

        if not args.foreground:
            cherrypy.process.plugins.Daemonizer(cherrypy.engine).subscribe()

        os.chdir(os.path.dirname(self.sourceFile))
        cherrypy.config.update(args.config)
        for log in ['access_file', 'error_file', 'pid_file']:
            path = cherrypy.config.get('log.%s' % log)
            if not path.startswith('/'):
                cherrypy.config.update({'log.%s' % log: os.path.join(os.path.abspath(os.path.dirname(self.sourceFile)), path)})

        if cherrypy.config.get('syslog.server'):
            h = logging.handlers.SysLogHandler(address=(cherrypy.config['syslog.server'], socket.getservbyname('syslog', 'udp')))
            h.setLevel(logging.INFO)
            h.setFormatter(cherrypy._cplogging.logfmt)
            cherrypy.log.access_log.addHandler(h)

        if cherrypy.config.get('log.pid_file'):
            cherrypy.process.plugins.PIDFile(cherrypy.engine, cherrypy.config.get('log.pid_file')).subscribe()

        cherrypy.config.update({'server.shutdown_timeout': 0})

    def start(self, api, startWebserver=True, backgroundTasks=None, afterStart=None):
        self.api = api
        rootConfig = {'/': {'tools.staticdir.on': True,
                            'tools.staticdir.root': os.path.dirname(os.path.abspath(self.sourceFile)),
                            'tools.staticdir.dir': 'static',
                            'tools.staticdir.index': 'index.html',
                            'tools.gzip.mime_types': ['text/*', 'application/*'],
                            'tools.gzip.on': True,
                            'tools.proxy.on': True,
                            'tools.proxy.local': 'Host'}}
        apiConfig  = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
                            'tools.gzip.mime_types': ['text/*', 'application/*'],
                            'tools.gzip.on': True,
                            'tools.proxy.on': True}}

        if startWebserver:
            cherrypy.tree.mount(Root(), '/', config=rootConfig)
            cherrypy.tree.mount(self.api, '/api/%s/1.0' % self.service, config=apiConfig)

        cherrypy.engine.subscribe('start_thread', Init.assignDatabaseParameters)
        cherrypy.engine.signal_handler.handlers['SIGTERM'] = self.stop
        cherrypy.engine.signal_handler.subscribe()
        cherrypy.engine.start()

        if afterStart:
            afterStart()

        if backgroundTasks:
            for task in backgroundTasks:
                StubbornDBBackgroundTask(Init.databaseParameters, task['interval'], task['function']).start()

        if 'log' in self.api.__dict__ and 'flushLogs' in dir(self.api.log):
            cherrypy.process.plugins.BackgroundTask(5, self.api.log.flushLogs).start()

        cherrypy.engine.block()

    def stop(self):
        cherrypy.engine.stop()
        if 'log' in self.api.__dict__ and 'flushLogs' in dir(self.api.log):
            self.api.log.flushLogs()
        if 'gpioCleanup' in dir(self.api):
            self.api.gpioCleanup()
        cherrypy.engine.signal_handler.bus.exit()

    @staticmethod
    def databaseParameters():
        return {'parameters': {'user':    cherrypy.config.get('database.user'),
                               'passwd':  cherrypy.config.get('database.password'),
                               'db':      cherrypy.config.get('database.name'),
                               'host':    cherrypy.config.get('database.host'),
                               'charset': cherrypy.config.get('database.charset')}}

    @staticmethod
    def assignDatabaseParameters(threadIndex):
        cherrypy.thread_data.db = Init.databaseParameters()

