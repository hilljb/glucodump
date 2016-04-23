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
"Communication with Bayer Contour USB meter"

import usbcomm
import re
import time

class FrameError(Exception):
    pass

class BayerCOMM(object):
    "Framing for Bayer meters"

    framere = re.compile('\x02(?P<check>(?P<recno>[0-7])(?P<text>[^\x0d]*)'
                         '\x0d(?P<end>[\x03\x17]))'
                         '(?P<checksum>[0-9A-F][0-9A-F])\x0d\x0a')

    mode_establish = object
    mode_data = object()
    mode_precommand = object()
    mode_command = object()

    def __init__(self, dev):
        self.dev = dev
        self.currecno = None
        self.state = self.mode_establish

    def checksum(self, text):
        checksum = hex(sum(ord(c) for c in text) % 256).upper().split('X')[1]
        return ('00' + checksum)[-2:]

    def checkframe(self, frame):
        match = self.framere.match(frame)
        if not match:
            raise FrameError("Couldn't parse frame", frame)

        recno = int(match.group('recno'))
        if self.currecno is None:
            self.currecno = recno
        
        if recno + 1 == self.currecno:
            return None
        
        if recno != self.currecno:
            raise FrameError("Bad recno, got %r expected %r" %
                             (recno, self.currecno),
                             frame)

        checksum = self.checksum(match.group('check'))
        if checksum != match.group('checksum'):
            raise FrameError("Checksum error: got %s expected %s" %
                             (match.group('checksum'), checksum),
                             frame)

        self.currecno = (self.currecno + 1) % 8

        print 'text: %r' % match.group('text')
        return match.group('text')
        
    def sync(self):
        """
        Sync with meter and yield received data frames
        """
        tometer = '\x04'
        result = None
        foo = 0
        while True:
            print '>>>', repr(tometer)
            self.dev.write(tometer)
            if result is not None and self.state == self.mode_data:
                yield result
            result = None
            data = self.dev.read()
            print '***', repr(data)
            if self.state == self.mode_establish:
                if data[-1] == '\x15':
                    # got a <NAK>, send <EOT>
                    tometer = chr(foo)
                    foo += 1
                    foo %= 256
                    continue
                if data[-1] == '\x05':
                    # got an <ENQ>, send <ACK>
                    tometer = '\x06'
                    self.currecno = None
                    continue
            if self.state == self.mode_data:
                if data[-1] == '\x04':
                    # got an <EOT>, done
                    self.state = self.mode_precommand
                    break
            stx = data.find('\x02')
            if stx != -1:
                # got <STX>, parse frame
                try:
                    result = self.checkframe(data[stx:])
                    tometer = '\x06'
                    self.state = self.mode_data
                except FrameError, e:
                    print e
                    tometer = '\x15' # Couldn't parse, <NAK>
            else:
                # Got something we don't understand, <NAK> it
                print 'no STX'
                tometer = '\x15'

    def ensurecommand(self):
        if self.state == self.mode_command:
            return

        if self.state in (self.mode_establish, self.mode_data):
            while True:
                self.dev.write('\x15') # send <NAK>
                data = self.dev.read()
                if data[-1] == '\x04':
                    # got <EOT>, meter ready
                    self.state = self.mode_precommand
                    break

        if self.state == self.mode_precommand:
            while True:
                self.dev.write('\x05') # send <ENQ>
                data = self.dev.read()
                if data[-1] == '\x06':
                    self.state = self.mode_command
                    return # Got ack, now in command mode


    def command(self, data):
        """Send a command to the meter

        Enter remote command mode if needed
        """
        self.ensurecommand()

        self.dev.write(data)
        data = self.dev.read()
        if data[-1] != '\x06':
            return None
        return data[:-1]

class Result(object):
    is_control = False

class ContourUSB(object):
    "Class that knows how to parse data from Countour USB meter"

    referencemap = { 'B' : 'whole blood', 'P' : 'plasma', 'C' : 'capillary',
                     'D' : 'deproteinized whole blood' }
    resultflagmap = {
        '<' : 'result low', '>' : 'result high', 'C' : 'control',
        'B' : 'before food', 'A' : 'after food', 'D' : "don't feel right",
        'I' : 'sick', 'S' : 'stress', 'X' : 'activity',
        'Z1' : '0.25 hours after food',
        'Z2' : '0.50 hours after food',
        'Z3' : '0.75 hours after food',
        'Z4' : '1.00 hours after food',
        'Z5' : '1.25 hours after food',
        'Z6' : '1.50 hours after food',
        'Z7' : '1.75 hours after food',
        'Z8' : '2.00 hours after food',
        'Z9' : '2.25 hours after food',
        'ZA' : '2.50 hours after food',
        'ZB' : '2.75 hours after food',
        'ZC' : '3.00 hours after food',
        }

    def __init__(self):
        self.field_sep = '|'
        self.repeat_sep = '\\'
        self.comp_sep = '^'
        self.escape_sep = '&'

        self.result = {}
        self.results = False

    def record(self, text):
        rectype = text[0]
        fn = getattr(self, 'record_' + rectype)
        if fn:
            fn(text)

    def record_H(self, text):
        self.field_sep = text[1]
        self.repeat_sep = text[2]
        self.comp_sep = text[3]
        self.escape_sep = text[4]
        
        fields = text[6:].split(self.field_sep)

        self.password = fields[1]

        (self.meter_product, versions,
         self.meter_serial, self.meter_sku) = fields[2].split(self.comp_sep)
        self.meter_version = versions.split(self.repeat_sep)

        self.device_info = dict(i.split('=') for i in fields[3].split(self.comp_sep))
        self.result_count = int(fields[4])
        self.processing_id = fields[9]
        self.spec_version = fields[10]
        self.header_datetime = fields[11]
        
    def record_P(self, text):
        self.patient_info = int(text.split(self.field_sep)[1])

    def record_O(self, text):
        res = text.split(self.field_sep)
        recno = int(res[1])
        if recno not in self.result:
            self.result[recno] = Result()

        if len(res) >= 12:
            if res[11] == 'Q':
                self.result[recno].is_control = True

    def record_R(self, text):
        res = text.split(self.field_sep)
        recno = int(res[1])
        result = self.result.setdefault(recno, Result())

        result.meastype = res[2].split(self.comp_sep)[3]
        result.value = float(res[3])
        result.unit, result.method = res[4].split(self.comp_sep)
        result.method = self.referencemap[result.method]
        # XXX bug in meter? should probably use '\' as repeat separator
        result.resultflags = [self.resultflagmap[x] for x in res[6].split('/') if x]
        result.testtime = res[8]

    def record_L(self, text):
        res = text.split(self.field_sep)
        if res[3] == 'N':
            self.results = True
