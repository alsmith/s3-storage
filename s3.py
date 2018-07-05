import base64
import boto.s3
import random
import string

import db

class S3Sync():
    def __init__(self, pri, sec, log):
        self.buckets = {
          'pri': boto.s3.connect_to_region(pri['region'], aws_access_key_id=pri['access'], aws_secret_access_key=pri['secret']).get_bucket(pri['bucket']),
          'sec': boto.s3.connect_to_region(sec['region'], aws_access_key_id=sec['access'], aws_secret_access_key=sec['secret']).get_bucket(sec['bucket'])
        }
        self.log = log

    def get(self, key, user):
        with db.DatabaseCursor() as cursor:
            cursor.execute('SELECT * FROM `objects` WHERE `key` = %s AND `user` = %s AND `uploading` = %s', (key, user, False))
            items = list(cursor.fetchall())
        if len(items) != 1:
            return None

        try:
            content = self._retrieveKey(items[0]['key'], 'pri')
        except Exception as e:
            self.log.log(msg='Primary retrieval for %s failed: %s' % (items[0]['id'], str(e)), context='GET')
            try:
                content = self._retrieveKey(items[0]['key'], 'sec')
            except Exception as e:
                self.log.log(msg='Secondary retrieval for %s failed: %s' % (items[0]['id'], str(e)), context='GET')
                raise
        return {'name': items[0]['name'], 'content': base64.b64encode(content).decode('ascii'), 'mimeType': items[0]['mimeType']}

    def list(self, user):
        with db.DatabaseCursor() as cursor:
            cursor.execute('SELECT * FROM `objects` WHERE `user` = %s AND `deleteAfter` IS NULL AND `uploading` = %s', (user, False))
            return list(cursor.fetchall())

    def receiveFile(self, name, content, mimeType):
        (id, key) = self._generateKey()
        try:
            self._storeKey(key, content, 'pri')
            with db.DatabaseCursor() as cursor:
                cursor.execute('UPDATE `objects` SET `name` = %s, `mimeType` = %s, `uploading` = %s, `pri` = %s WHERE `key` = %s', (name, mimeType, False, True, key))
        except Exception as e:
            self.log.log(msg='Primary storage for %s failed: %s' % (id, str(e)), context='RECV')
            try:
                self._storeKey(key, content, 'sec')
                with db.DatabaseCursor() as cursor:
                    cursor.execute('UPDATE `objects` SET `name` = %s, `mimeType` = %s, `uploading` = %s, `sec` = %s WHERE `key` = %s', (name, mimeType, False, True, key))
            except Exception as e:
                self.log.log(msg='Secondary storage for %s failed: %s' % (id, str(e)), context='RECV')
                return None
        return key

    def storeFile(self, key, user):
        with db.DatabaseCursor() as cursor:
            cursor.execute('UPDATE `objects` SET `user` = %s WHERE `key` = %s', (user, key))

    def delete(self, user, key):
        with db.DatabaseCursor() as cursor:
            cursor.execute('UPDATE `objects` SET `deleteAfter` = DATE_ADD(NOW(), INTERVAL 10 MINUTE) WHERE `key` = %s AND `user` = %s', (key, user))
        return

    def sync(self):
        with db.DatabaseCursor() as cursor:
            # Remove objects where the upload is taking longer than expected.
            cursor.execute('DELETE FROM `objects` WHERE `uploading` = %s AND NOW() > DATE_ADD(`created`, INTERVAL 15 MINUTE)', (True,))

            # Remove objects that need to be expired
            cursor.execute('SELECT * FROM `objects` WHERE `deleteAfter` < NOW()')
            for obj in list(cursor.fetchall()):
                try:
                    if self._existsKey(obj['key'], 'pri'):
                        self._deleteKey(obj['key'], 'pri')
                    cursor.execute('UPDATE `objects` SET `pri` = %s WHERE `id` = %s', (False, obj['id'],))
                except Exception as e:
                    self.log.log(msg='Primary delete for %s failed: %s' % (obj['id'], str(e)), context='SYNC')
                try:
                    if self._existsKey(obj['key'], 'sec'):
                        self._deleteKey(obj['key'], 'sec')
                    cursor.execute('UPDATE `objects` SET `sec` = %s WHERE `id` = %s', (False, obj['id'],))
                except Exception as e:
                    self.log.log(msg='Secondary delete for %s failed: %s' % (obj['id'], str(e)), context='SYNC')
            cursor.execute('DELETE FROM `objects` WHERE `pri` = %s AND `sec` = %s AND `deleteAfter` < NOW()', (False, False))

            # Sync remaining objects between pri<->sec storage
            cursor.execute('SELECT * FROM `objects` WHERE `uploading` = %s AND deleteAfter IS NULL AND (`pri` = %s OR `sec` = %s)', (False, False, False))
            for obj in list(cursor.fetchall()):
                if obj['pri'] and not obj['sec']:
                    try:
                        content = self._retrieveKey(obj['key'], 'pri')
                        self._storeKey(obj['key'], content, 'sec')
                        cursor.execute('UPDATE `objects` SET `sec` = %s WHERE `id` = %s', (True, obj['id']))
                    except Exception as e:
                        self.log.log(msg='Copy to secondary for %s failed: %s' % (obj['id'], str(e)), context='SYNC')
                if obj['sec'] and not obj['pri']:
                    try:
                        content = self._retrieveKey(obj['key'], 'sec')
                        self._storeKey(obj['key'], content, 'pri')
                        cursor.execute('UPDATE `objects` SET `pri` = %s WHERE `id` = %s', (True, obj['id']))
                    except Exception as e:
                        self.log.log(msg='Copy to primary for %s failed: %s' % (obj['id'], str(e)), context='SYNC')

    def _generateKey(self):
        while True:
            with db.DatabaseCursor() as cursor:
                key = ''.join(random.choice(string.ascii_letters + string.digits) for x in range(256))
                try:
                    cursor.execute('INSERT INTO `objects` (`key`, `uploading`) VALUES (%s, %s)', (key, True))
                    id = cursor.lastrowid()
                    break
                except Exception as e:
                    pass
        return (id, key)

    def _key(self, key, provider):
        return self.buckets[provider].get_key(key)

    def _retrieveKey(self, key, provider):
        return self._key(key, provider).get_contents_as_string()

    def _existsKey(self, key, provider):
        return self._key(key, provider) != None

    def _storeKey(self, keyname, content, provider):
        s3object = boto.s3.key.Key(bucket=self.buckets[provider])
        s3object.key = keyname
        s3object.set_contents_from_string(content)

    def _deleteKey(self, key, provider):
        s3object = self.buckets[provider].get_key(key)
        s3object.delete()

