import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scene_usb


class UsbTests(unittest.TestCase):
    def test_private_server_is_registered_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); adb=root/'tools/android/platform-tools/adb.exe';adb.parent.mkdir(parents=True);adb.write_bytes(b'fixture')
            runtime=root/'out/scene/runtime.json';runtime.parent.mkdir(parents=True);runtime.write_text(json.dumps({'token':'fixture-token'}),encoding='utf-8')
            calls=[];ports=[]
            class Connected:
                def __enter__(self): return self
                def __exit__(self,*args): pass
            def connect_socket(address,timeout):
                ports.append(address[1])
                if len(ports)<=2: raise OSError('not listening')
                return Connected()
            def run(args,**kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=0,stdout='List of devices attached\n',stderr='')
            with patch.dict('os.environ',{'AUDIO_MEMORY_REGISTRY_PATH':'fixture-registry','AUDIO_MEMORY_REGISTRY_EXECUTABLE':'fixture-node'}), patch('scene_usb.socket.create_connection',side_effect=connect_socket), patch('scene_usb.subprocess.Popen') as popen, patch('scene_usb.subprocess.run',side_effect=run):
                with self.assertRaisesRegex(ValueError,'尚未检测到可用手机'):
                    scene_usb.connect(root,tools_root=root)
                self.assertIn('fixture-registry',popen.call_args.args[0]);self.assertTrue(json.loads(runtime.read_text(encoding='utf-8'))['adbOwned'])
                scene_usb.cleanup(root,tools_root=root)
                self.assertTrue(any('kill-server' in row for row in calls))

    def test_shared_adb_connect_and_cleanup_does_not_stop_shared_server(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); adb=root/'tools/android/platform-tools/adb.exe'; adb.parent.mkdir(parents=True);adb.write_bytes(b'fixture')
            runtime=root/'out/scene/runtime.json';runtime.parent.mkdir(parents=True);runtime.write_text(json.dumps({'token':'fixture-token'}),encoding='utf-8')
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=0,stdout='List of devices attached\nfixture\tdevice\n' if 'devices' in args else '',stderr='')
            with patch('scene_usb.socket.create_connection') as connection, patch('scene_usb.subprocess.run',side_effect=run):
                connection.return_value.__enter__.return_value=None
                message=scene_usb.connect(root,tools_root=root)
                self.assertIn('手机采集页',message)
                self.assertTrue(any('reverse' in row and '--no-rebind' in row for row in calls))
                state=json.loads(runtime.read_text(encoding='utf-8'));self.assertFalse(state['adbOwned']);self.assertEqual(state['usbSerial'],'fixture')
                scene_usb.cleanup(root,tools_root=root)
                self.assertTrue(any('--remove' in row for row in calls))
                self.assertFalse(any('kill-server' in row for row in calls))

    def test_missing_adb_has_clear_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'缺少安卓USB工具'):
                scene_usb.connect(Path(folder),tools_root=Path(folder))


if __name__=='__main__': unittest.main()
