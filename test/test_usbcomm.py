#
# Copyright (C) 2011 Anders Hammarquist <iko@iko.pp.se>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"test lowlevel communication"

from .. import usbcomm
import usb
import array

class FakeDescriptor(object):
    def __init__(self, **kw):
        self._keywords = kw
        self.index = kw.get('index', 42)
        self._readresult = kw.get('read', [])
        self._writeresult = kw.get('write', [])

    def set_configuration(self):
        pass

    def get_active_configuration(self):
        return self

    def is_kernel_driver_active(self, iface):
        pass

    def detach_kernel_driver(self, iface):
        pass

    def read(self, size, timeout=None):
        data = self._readresult.pop(0)
        assert size == len(data)
        return array.array('B', data)

    def write(self, data):
        self._writeresult.append(data)

class FakeUSB(object):
    CLASS_HID = 3
    
    class core(object):
        @staticmethod
        def find(**kw):
            return FakeDescriptor(**kw)

        USBError = usb.core.USBError

    class util(object):
        @staticmethod
        def find_descriptor(config, **kw):
            kwd = {}
            kwd.update(config._keywords)
            kwd.update(kw)
            return FakeDescriptor(**kwd)

class TestUSBComm(object):
    usbdata = [
        'ABC\x3c\x04\x021H|\\^&||uv'
        'mjq4|Bayer7390^0'
        '1.20\\01.04\\04.02'
        '.19^7390-1163170',

        'ABC\x3c^7396-|A=1^C'
        '=63^G=1^I=0200^R'
        '=0^S=1^U=1^V=106'
        '00^X=07007007009',

        'ABC\x3c918013518024'
        '8^Y=360126090050'
        '099050300089^Z=1'
        '|209||||||1|2011',
        
        'ABC\x0f02142249\x0d\x17\x36\x35'
        '\x0d\x0a\x05\0\0\0\0\0\0\0\0\0\0\0\0\0'
        '\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'
        '\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'
        ]

    dataread = \
        '\x04\x021H|\\^&||uvmjq4|Bayer7390^01.20\\01.04\\04.02.19^7390-1163170'\
        '^7396-|A=1^C=63^G=1^I=0200^R=0^S=1^U=1^V=10600^X=07007007009' \
        '9180135180248^Y=360126090050099050300089^Z=1|209||||||1|2011' \
        '02142249\x0d\x1765\x0d\x0a\x05'

    def setup_class(self):
        self._usb = usbcomm.usb
        usbcomm.usb = FakeUSB

    def teardown_class(self):
        usbcomm.usb = self._usb

    def test_simple(self):
        uc = usbcomm.USBComm(idVendor=usbcomm.ids.Bayer,
                             idProduct=usbcomm.ids.Bayer.Contour)

        assert uc

    def test_read(self):
        uc = usbcomm.USBComm(read=self.usbdata)
        data = uc.read()
        assert data == self.dataread

    def test_write(self):
        written = []
        expected = [
            '\0\0\0\x3c' + 'a'*60,
            '\0\0\0\x0a' + 'a'*10
            ]
        
        uc = usbcomm.USBComm(write=written)
        count = uc.write('a'*70)
        assert written == expected
