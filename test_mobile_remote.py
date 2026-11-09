import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from mobile_sync import make_handler
from mobile_sync_remote import MobileRemote


class RemoteSyncTests(unittest.TestCase):
    def test_public_receiver_auth_host_and_management_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Public side accepts only the per-session token and public host.
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(Path(tmp),'remote-token',hosts={'example.trycloudflare.com'}))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def request(route,token='remote-token',host='example.trycloudflare.com',post=False):
                    req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+route,data=b'' if post else None,headers={'Authorization':'Bearer '+token,'Host':host})
                    return urllib.request.urlopen(req,timeout=3)
                with request('/v1/sync/health') as response:self.assertEqual(response.status,200)
                for path,token,host,post,expected in [('/v1/sync/health','local-token','example.trycloudflare.com',False,401),('/v1/sync/health','remote-token','wrong.host',False,401),('/v1/sync/remote','remote-token','example.trycloudflare.com',True,404),('/v1/materials','remote-token','example.trycloudflare.com',False,404)]:
                    with self.assertRaises(urllib.error.HTTPError) as caught:request(path,token,host,post)
                    self.assertEqual(caught.exception.code,expected)
            finally:server.shutdown();server.server_close();thread.join()

    def test_tunnel_failure_does_not_leave_pairing_or_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=MobileRemote(tmp)
            with patch('mobile_sync_remote.RemoteTransport') as constructor:
                transport=constructor.return_value;transport.start.side_effect=ValueError('fixture failure')
                with self.assertRaises(ValueError):manager.start()
                transport.close.assert_called_once();self.assertEqual(manager.status(),{'status':'stopped'})
                self.assertIsNone(manager.transport)
            manager.shutdown()
            with self.assertRaises(RuntimeError):manager.start()


if __name__=='__main__':unittest.main()
