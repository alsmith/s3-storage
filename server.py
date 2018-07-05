#!/usr/bin/python3

import os, sys
import cherrypy

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import helpers
import init
import log

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'openid'))
import openid

class API():
    class List():
        def __init__(self, api):
            self.api = api
            self.DELETE = helpers.notImplemented
            self.POST = helpers.notImplemented
            self.PUT = helpers.notImplemented

        @cherrypy.tools.json_out(handler=helpers.dumper)
        def GET(self):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)
            return self.api.s3.list(user)

    class Object():
        def __init__(self, api):
            self.api = api
            self.POST = helpers.notImplemented
            self.PUT = helpers.notImplemented

        @cherrypy.tools.json_out()
        def GET(self, key):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)

            content = self.api.s3.get(key, user)
            if not content:
                raise cherrypy.HTTPError(500)
            self.api.log.log(msg='%s/%s' % (user, key[:16]), context='GET')
            return content

        @cherrypy.tools.json_in()
        def DELETE(self, *vpath):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)

            if len(vpath) != 1:
                raise cherrypy.HTTPError(400)

            self.api.s3.delete(user, vpath[0])
            self.api.log.log(msg='%s/%s' % (user, vpath[0][:16]), context='DELETE')
            return

    class Upload():
        def __init__(self, api):
            self.api = api
            self.GET = helpers.notImplemented
            self.DELETE = helpers.notImplemented

        def POST(self, upload):
            name = upload.filename
            content = upload.file.read()
            mimeType = str(upload.content_type)
            key = self.api.s3.receiveFile(name, content, mimeType)

            text = '<span id="key">%s</span>' % key
            text += '<script type="text/javascript">parent.$(\'body\').trigger(\'iframeLoaded\');</script>';
            self.api.log.log(msg='%s' % (key[:16],), context='UPLOAD1')
            return text

        @cherrypy.tools.json_in()
        def PUT(self):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)

            request = cherrypy.request.json
            if 'key' not in request:
                raise cherrypy.HTTPError(400)

            self.api.s3.storeFile(request['key'], user)
            self.api.log.log(msg='%s/%s' % (user, request['key'][:16]), context='UPLOAD2')

    def __init__(self):
        self.openid = openid.OpenID('s3')
        self.log = log.Log('s3')
        self.s3 = s3.S3Sync(pri={'region': cherrypy.config['s3.pri.region'],
                                 'bucket': cherrypy.config['s3.pri.bucket'],
                                 'access': cherrypy.config['s3.pri.access'],
                                 'secret': cherrypy.config['s3.pri.secret']},
                            sec={'region': cherrypy.config['s3.sec.region'],
                                 'bucket': cherrypy.config['s3.sec.bucket'],
                                 'access': cherrypy.config['s3.sec.access'],
                                 'secret': cherrypy.config['s3.sec.secret']},
                            log=self.log)

        self.list = self.List(self)
        self.list.exposed = True
        self.object = self.Object(self)
        self.object.exposed = True
        self.upload = self.Upload(self)
        self.upload.exposed = True

def main():
    service = init.Init('s3', __file__)
    api = API()
    service.start(api, backgroundTasks=[{'function': api.s3.sync, 'interval': 60}])

if __name__ == '__main__':
    sys.exit(main())

