import subprocess,unittest
from unittest.mock import patch
from scene_wifi import local_ip

class AddressTests(unittest.TestCase):
 def test_physical_address_selected_instead_of_tunnel(self):
  with patch('scene_wifi.os.name','nt'),patch('scene_wifi.subprocess.run',return_value=subprocess.CompletedProcess([],0,'198.18.0.1\n10.66.67.241\n','')) as run:
   self.assertEqual(local_ip(),'10.66.67.241')
   self.assertIn('HardwareInterface',run.call_args.args[0][-1])
 def test_no_physical_address_does_not_fall_back_to_tunnel(self):
  with patch('scene_wifi.os.name','nt'),patch('scene_wifi.subprocess.run',return_value=subprocess.CompletedProcess([],0,'198.18.0.1\n','')):
   with self.assertRaises(ValueError):local_ip()

if __name__=='__main__':unittest.main()
