#!/usr/bin/python3

import os, sys
import argparse
import base64
import boto.s3
import cherrypy
import queue
import random
import socket
import string
import threading
import time

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import db
import helpers
import init

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "openid"))
import openid

class S3Sync():
    def __init__(self):
        pri = boto.s3.connect_to_region(cherrypy.config['s3.pri.region'], aws_access_key_id=cherrypy.config['s3.pri.access'], aws_secret_access_key=cherrypy.config['s3.pri.secret'])
        sec = boto.s3.connect_to_region(cherrypy.config['s3.sec.region'], aws_access_key_id=cherrypy.config['s3.sec.access'], aws_secret_access_key=cherrypy.config['s3.sec.secret'])

        self.buckets = {}
        self.buckets['pri'] = pri.get_bucket(cherrypy.config['s3.pri.bucket'], validate=False)
        self.buckets['sec'] = sec.get_bucket(cherrypy.config['s3.sec.bucket'], validate=False)

    def get(self, handle, user):
        with db.DatabaseCursor() as cursor:
            cursor.execute('SELECT * FROM objects WHERE handle = %s AND user = %s', (handle, user))
            items = list(cursor.fetchall())
        if len(items) != 1:
            return None

        try:
            content = self._retrieveFile(items[0]['handle'], 'pri')
        except Exception as e:
            try:
                content = self._retrieveFile(items[0]['handle'], 'sec')
            except Exception as e:
                cherrypy.log('get():%s' % str(e))
                raise
        return {'name': items[0]['name'], 'content': base64.b64encode(content).decode('ascii'), 'mimeType': items[0]['mimeType']}

    def list(self, user):
        with db.DatabaseCursor() as cursor:
            cursor.execute('SELECT * FROM objects WHERE user = %s AND deleteAt IS NULL AND inProgress = %s', (user, False))
            return list(cursor.fetchall())

    def receiveFile(self, name, content, mimeType):
        handle = self._generateHandle()
        cherrypy.log('handle: %s' % handle)

        try:
            self._storeFile(handle, content, 'pri')
            with db.DatabaseCursor(logQueries=True) as cursor:
                cursor.execute('UPDATE objects SET name = %s, mimeType = %s, inProgress = %s, pri = %s WHERE handle = %s', (name, mimeType, False, True, handle))
        except Exception as e:
            try:
                self._storeFile(handle, content, 'sec')
                with db.DatabaseCursor(logQueries=True) as cursor:
                    cursor.execute('UPDATE objects SET name = %s, mimeType = %s, inProgress = %s, sec = %s WHERE handle = %s', (name, mimeType, False, True, handle))
            except Exception as e:
                raise cherrypy.HTTPError(500)
        return handle

    def storeFile(self, handle, user):
        with db.DatabaseCursor() as cursor:
            cursor.execute('UPDATE objects SET user = %s WHERE handle = %s', (user, handle))

    def delete(self, user, handle):
        with db.DatabaseCursor() as cursor:
            cursor.execute('UPDATE objects SET deleteAt = DATE_ADD(NOW(), INTERVAL 1 WEEK) WHERE handle = %s AND user = %s', (handle, user))
        return

    def sync(self):
        with db.DatabaseCursor() as cursor:
            cursor.execute('DELETE FROM objects WHERE inProgress = %s AND NOW() > DATE_ADD(createdAt, INTERVAL 1 MINUTE)', (True,))

        with db.DatabaseCursor() as cursor:
            cursor.execute('SELECT * FROM objects WHERE pri = %s OR sec = %s', (False, False))
            for obj in list(cursor.fetchall()):
                try:
                    if obj['pri'] and not obj['sec']:
                        content = self._retrieveFile(obj['handle'], 'pri')
                        self._storeFile(obj['handle'], content, 'sec')
                        cursor.execute('UPDATE objects SET sec = %s WHERE id = %s', (True, obj['id']))
                    if obj['sec'] and not obj['pri']:
                        content = self._retrieveFile(obj['handle'], 'sec')
                        self._storeFile(obj['handle'], content, 'pri')
                        cursor.execute('UPDATE objects SET pri = %s WHERE id = %s', (True, obj['id']))
                except Exception as e:
                    cherrypy.log('sync():%s' % str(e))

        with db.DatabaseCursor() as cursor:
            cursor.execute('SELECT * FROM objects WHERE deleteAt < NOW()')
            for obj in list(cursor.fetchall()):
                try:
                    self._deleteFile(obj['handle'], 'pri')
                    cursor.execute('UPDATE objects SET pri = %s where id = %s', (False, obj['id'],))
                except Exception as e:
                    cherrypy.log('sync():%s' % str(e))
                try:
                    self._deleteFile(obj['handle'], 'sec')
                    cursor.execute('UPDATE objects SET sec = NULL where id = %s', (False, obj['id'],))
                except Exception as e:
                    cherrypy.log('sync():%s' % str(e))
            cursor.execute('DELETE FROM objects WHERE pri = %s AND sec = %s AND deleteAt < NOW()', (False, False))

    def  _generateHandle(self):
        while True:
            handle = ''.join(random.choice(string.ascii_letters + string.digits) for x in range(256))
            with db.DatabaseCursor() as cursor:
                try:
                    cursor.execute('INSERT INTO objects (handle, inProgress) VALUES (%s, 1)', (handle,))
                    break
                except Exception as e:
                    pass
        return handle

    def _retrieveFile(self, handle, provider):
        s3object = self.buckets[provider].get_key(handle)
        return s3object.get_contents_as_string()

    def _storeFile(self, keyname, content, provider):
        s3object = boto.s3.key.Key(bucket=self.buckets[provider])
        s3object.key = keyname
        s3object.set_contents_from_string(content)

    def _deleteFile(self, handle, provider):
        s3object = self.buckets[provider].get_key(handle)
        s3object.delete()

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

        @cherrypy.tools.json_out()
        def GET(self, handle):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)

            return self.api.s3.get(handle, user)

        @cherrypy.tools.json_in()
        @cherrypy.tools.json_out()
        def PUT(self):
            return {}

        @cherrypy.tools.json_in()
        def DELETE(self, *vpath):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)

            if len(vpath) != 1:
                raise cherrypy.HTTPError(400)

            self.api.s3.delete(user, vpath[0])
            return

    class Upload():
        def __init__(self, api):
            self.api = api
            self.GET = helpers.notImplemented
            self.DELETE = helpers.notImplemented

        def POST(self, upload):
            name = upload.filename
            cherrypy.log('%s'%name)
            cherrypy.log('%s'%type(name))
            content = upload.file.read()
            cherrypy.log('%s'%content)
            mimeType = str(upload.content_type)
            cherrypy.log('%s'%mimeType)
            cherrypy.log('%s'%type(mimeType))
            handle = self.api.s3.receiveFile(name, content, mimeType)

            text = '<span id="handle">%s</span>' % handle
            text += '<script type="text/javascript">parent.$(\'body\').trigger(\'iframeLoaded\');</script>';
            return text

        @cherrypy.tools.json_in()
        def PUT(self):
            user = self.api.openid.validateAccessToken('s3')
            if not user:
                raise cherrypy.HTTPError(403)

            request = cherrypy.request.json
            if 'handle' not in request:
                raise cherrypy.HTTPError(400)

            self.api.s3.storeFile(request['handle'], user)

    def __init__(self):
        self.openid = openid.OpenID('s3')
        self.s3 = S3Sync()

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

