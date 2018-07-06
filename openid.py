# Dummy ID-verifier class - basically does nothing really useful...

class OpenID():
    def __init__(self, service):
        self.service = service

    def validateAccessToken(self, service, token=None, scope=None):
        return 'username'

