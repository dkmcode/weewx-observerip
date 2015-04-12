#!/usr/bin/python
"""weewx driver for Ambient ObserverIP

To use this driver: see readme.txt
For the default configuration see the  ObserverIPConfEditor class or run
   bin/wee_config_device weewx.conf --defaultconfig
"""


from __future__ import with_statement
import syslog
import time
import io
import socket
import sys
import urllib
import urllib2

import weewx
import weewx.drivers
from weeutil.weeutil import to_int, to_float, to_bool

DRIVER_NAME = 'ObserverIP'
DRIVER_VERSION = "0.1"

if weewx.__version__ < "3":
    raise weewx.UnsupportedFeature("weewx 3 is required, found %s" %
                                   weewx.__version__)

def logmsg(dst, msg):
    syslog.syslog(dst, 'observerip: %s' % msg)
    #sys.stdout.write('observerip: %s\n' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logcrt(msg):
    logmsg(syslog.LOG_CRIT, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)

def loader(config_dict, engine):
    return ObserverIP(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return ObserverIPConfEditor()

def configurator_loader(_):
    return ObserverIPConfigurator()

class OpserverIPHardware():
    """
    Interface to communicate directly with ObserverIP
    """

    def __init__(self, **stn_dict):
        self.versionmap = {'wh2600USA_v2.2.0',('3.0.0')}
        self.calibrationbound = {'RainGain': (to_float, 0.1, 5.0),
                                 'AbsOffset': (to_float, -23.62, 23.62),
                                 'outTempOffset': (to_float, -18.0, 18.0),
                                 'windDirOffset': (to_float, -180.0, 180.0),
                                 'luxwm2': (to_float, 1.0, 1000.0),
                                 'SolarGain': (to_float, 0.1, 5.0),
                                 'WindGain': (to_float, 0.1, 5.0),
                                 'inTempOffset': (to_float, -18.0, 18.0),
                                 'UVGain': (to_float, 0.1, 5.0),
                                 'outHumiOffset': (to_float, -10.0, 10.0),
                                 'inHumiOffset': (to_float, -10.0, 10.0),
                                 'RelOffset': (to_float, -23.62, 23.62)
                             }
        self.hostname = stn_dict.get('hostname',None)

        self.max_tries = int(stn_dict.get('max_tries', 5))
        self.retry_wait = int(stn_dict.get('retry_wait', 2))
        self.infopacket = None
        self.infopacket = self.infoprobe()
        if not self.infopacket:
            #should raise exception
            logerr('ObserverIP network probe failed')
            exit(1)

    def infoprobe(self):
        if self.hostname:
            UDP_IP = self.hostname
        else:
            UDP_IP = "255.255.255.255"
        UDP_PORT = 25122
        MESSAGE = "ASIXXISA\x00"
        sock = socket.socket(socket.AF_INET, # Internet
                             socket.SOCK_DGRAM) # UDP
        if not self.hostname:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for count in range(self.max_tries):
            try:
                sock.sendto(MESSAGE, (UDP_IP,UDP_PORT))
                sock.settimeout(self.retry_wait)
                recv_data, (addr,port) = sock.recvfrom(1024)
                return recv_data
                break
            except socket.timeout:
                loginf("socket timeout %d of %d" % (count+1, self.max_tries))
            except socket.gaierror:
                logerr("%s: incorrect hostname or IP" % self.hostname)
                return None
        else:
            return None

    def packetstr(self,ind):
        es = self.infopacket.find('\x00',ind)
        return self.infopacket[ind:es]

    def packetip(self,ind):
        return "%d.%d.%d.%d" % (ord(self.infopacket[ind]),
                                ord(self.infopacket[ind + 1]),
                                ord(self.infopacket[ind + 2]),
                                ord(self.infopacket[ind + 3]))

    def packetport(self, ind):
        return ord(self.infopacket[ind]) * 256 + ord(self.infopacket[ind+1])

    def getinfopacket(self):
        return self.infopacket

    def dhcp(self):
        flag=ord(self.infopacket[0x20]) & 0x40
        if (flag == 0 ):
            return False
        else:
            return True

    def ipaddr(self):
        return self.packetip(0x22)

    def staticipaddr(self):
        return self.packetip(0x26)

    def portuk(self):
        return self.packetport(0x2a)

    def porta(self):
        return self.packetport(0x2c)

    def portb(self):
        return self.packetport(0x2e)

    def port(self):
        return self.packetport(0x34)

    def netmask(self):
        return self.packetip(0x36)

    def staticgateway(self):
        return self.packetip(0x3a)

    def staticdns(self):
        return self.packetip(0x3e)

    def updatehost(self):
        return self.packetstr(0x4b)

    def ipaddruk(self):
        return self.packetip(0x6f)

    def version(self):
        return self.packetstr(0x73)

    def page_to_dict(self, url,Value=True):
        dat={}

        for count in range(self.max_tries):
            try:
                response = urllib2.urlopen(url)
                break
            except urllib2.URLError:
                logerr('data retrieval failed attempt %d of %d: %s' %
                       (count+1, self.max_tries, ''))
                time.sleep(self.retry_wait)
        else:
            logerr('data retrieval failed after %d tries' % self.max_tries)
            return dat

        for line in response:
            try:
                line.index('<input')
                es = line.index('name="')
                ee = line.index('"',es+6)
                name = line[es+6:ee]
                es = line.index('value="')
                ee = line.index('"',es+7)
                val = line[es+7:ee]
                dat[name]=val
            except ValueError:
                try:
                    line.index('<select')
                    es = line.index('name="')
                    ee = line.index('"',es+6)
                    name = line[es+6:ee]
                    while True:
                        nextline=response.readline()
                        sl = nextline.find('selected')
                        if ( sl != -1): break
                    if Value:
                        es = nextline.index('value="')
                        ee = nextline.index('"',es+7)
                        val = nextline[es+7:ee]
                        dat[name]=val
                    else:
                        es = nextline.index('>',sl)
                        ee = nextline.index('<',es)
                        val = nextline[es+1:ee]
                        dat[name]=val
                except ValueError:
                    pass
        for i in ('Cancel', 'Apply', 'corr_Default', 'rain_Default', 'reboot', 'restore'):
            if i in dat: del dat[i]
        return dat

    def dict_to_param(self, dict):
        param=""
        for i in dict:
            if param:
                param = param + "&"
            param = param + "%s=%s" % (i,dict[i])
        return param

    def boundcheck(self, bound, data):
        for i in data:
            if i in bound:
                if ( bound[i][0](data[i]) < bound[i][0](bound[i][1]) or bound[i][0](data[i]) > bound[i][0](bound[i][2])):
                    logerr("%s bound error: range: %s-%s value: %s" % (i, bound[i][1], bound[i][2], data[i] ))
                    exit(1)
            else:
                logerr("%s not bound" % i)
                exit(1)

    def getnetworksettings(self,Readable=False):
        return self.page_to_dict('http://%s/bscsetting.htm' % self.ipaddr(),not Readable)
    def setnetworksettings(self):
        response = urllib2.urlopen("http://%s/bscsetting.htm" % self.ipaddr(),
                                   self.dict_to_param(calibdata) + "&Apply=Apply")
    def setnetworkdefault(self):
        #print 'Not implemented'
        pass
    def reboot(self, wait=True):
        #print 'Not implemented'
        if wait:
            self.infopacket = None
            self.infopacket = self.infoprobe()
            #if self.infopacket:
            #    print 'reboot succeded'
            #else:
            #    print 'cant find station'

    def getidpasswd(self):
        return self.page_to_dict('http://%s/weather.htm' % self.ipaddr())
    def setidpasswd(self, id, passwd):
        """set id and passwd"""
        response = urllib2.urlopen("http://%s/weather.htm" % self.ipaddr(),
                                   "stationID=%s&stationPW=%s&Apply=Apply" % (id, passwd))

    def getstationsettings(self,Readable=False):
        return self.page_to_dict('http://%s/station.htm' % self.ipaddr(),not Readable)
    def setstationsettings(self,settings):
        if 'WRFreq' in settings: del settings['WRFreq']
        response = urllib2.urlopen("http://%s/station.htm" % self.ipaddr(),
                                   self.dict_to_param(settings) + "&Apply=Apply")

    def data(self):
        return self.page_to_dict('http://%s/livedata.htm' % self.ipaddr())

    def getcalibration(self):
        return self.page_to_dict('http://%s/correction.htm' % self.ipaddr())
    def setcalibration(self, calibdata):
        self.boundcheck(self.calibrationbound ,calibdata)
        print self.dict_to_param(calibdata)
        #response = urllib2.urlopen("http://%s/correction.htm" % self.ipaddr(),
        #                           self.dict_to_param(calibdata) + "&Apply=Apply")
    def setcalibrationdefault(self):
        #print "defaults"
        response = urllib2.urlopen('http://%s/msgcoredef.htm' % self.ipaddr())
        #print response.read()

# =============================================================================

class ObserverIP(weewx.drivers.AbstractDevice):
    """
    weewx driver to download data from ObserverIP
    """

    def __init__(self, **stn_dict):
        loginf("version is %s" % DRIVER_VERSION)

        self.xferfile = stn_dict['xferfile']
        self.poll_interval = float(stn_dict.get('poll_interval', 10))
        self.dup_interval = float(stn_dict.get('dup_interval', 5))
        self.max_tries = int(stn_dict.get('max_tries', 5))
        self.retry_wait = int(stn_dict.get('retry_wait', 2))
        self.directtx = to_bool(stn_dict.get('direct', False))
        self.check_calibration = to_bool(stn_dict.get('check_calibration',False))
        self.set_calibration = to_bool(stn_dict.get('set_calibration', False))

        self.lastrain = None
        self.lastpacket = 0
        self.expected_units = {'unit_Wind': 'mph',
                               'u_Rainfall': 'in',
                               'unit_Pressure': 'inhg',
                               'u_Temperature': 'degF',
                               'unit_Solar': 'w/m2'}
        self.directmap = {
            'wh2600USA_v2.2.0' : {
                'dateTime' : ('epoch', to_int),
                'inTemp' : ('inTemp', to_float),
                'inHumidity' : ('inHumi', to_float),
                'pressure' : ('AbsPress', to_float),
                'outTemp' : ('outTemp',to_float),
                'outHumidity' : ('outHumi', to_float),
                'windDir' : ('windir', to_float),
                'windSpeed' : ('avgwind', to_float),
                'windGust' : ('gustspeed', to_float),
                'radiation' : ('solarrad', to_float),
                'UV' : ('uvi', to_float),
                'rain' : ('rainofyearly', to_float),
                'inTempBatteryStatus' : ('inBattSta',self.norm),
                'outTempBatteryStatus' : ('outBattSta1',self.norm)
            },
            'default' : {
                'dateTime' : ('epoch', to_int),
                'inTemp' : ('inTemp', to_float),
                'inHumidity' : ('inHumi', to_float),
                'pressure' : ('AbsPress', to_float),
                'outTemp' : ('outTemp',to_float),
                'outHumidity' : ('outHumi', to_float),
                'windDir' : ('windir', to_float),
                'windSpeed' : ('avgwind', to_float),
                'windGust' : ('gustspeed', to_float),
                'radiation' : ('solarrad', to_float),
                'UV' : ('uvi', to_float),
                'rain' : ('rainofyearly', to_float),
            },
            'wu' : {
                'dateTime' : ('epoch', to_int),
                'outTemp' : ('tempf',to_float),
                'outHumidity' : ('humidity', to_float),
                'dewpoint' : ('dewptf', to_float),
                'windchill' : ('windchillf', to_float),
                'windDir' : ('winddir', to_float),
                'windSpeed' : ('windspeedmph', to_float),
                'windGust' : ('windgustmph', to_float),
                'rain' : ('yearlyrainin', to_float),
                'radiation' : ('solarradiation', to_float),
                'UV' : ('UV', to_float),
                'inTemp' : ('indoortempf', to_float),
                'inHumidity' : ('indoorhumidity', to_float),
                'pressure' : ('baromin', to_float),
                'txBatteryStatus' : ('lowbatt', to_float),
            }
        }
                
        if (self.directtx):
            self.obshardware = OpserverIPHardware(**stn_dict)
            if self.chkunits(self.expected_units):
                logerr("calibration error: %s is expexted to be %f but is %f" % 
                          (i, to_float(calibdata[i]), to_float(stcalib[i])))
                exit(1)
            if self.obshardware.version() in self.directmap:
                self.map = self.directmap[self.obshardware.version()]
            else:
                loginf("Unknown firmware version: %s" % self.obshardware.version())
                self.map = self.directmap['default']
        else:
            self.map = self.directmap['wu']
            if self.check_calibration:
                self.obshardware = OpserverIPHardware(**stn_dict)
                if self.chkunits(self.expected_units):
                    exit(1)

        if 'calibration' in stn_dict and self.check_calibration:
            if self.chkcalib(stn_dict['calibration']):
                if(self.set_calibration):
                    self.obshardware.setcalibration(stn_dict['calibration'])
                    if self.chkcalib(stn_dict['calibration']):
                        logerr("Setting calibration unsuccessful")
                        exit(1)
                else:
                    exit(1)
                
        loginf("polling interval is %s" % self.poll_interval)

    @property
    def hardware_name(self):
        return "ObserverIP"

    def genLoopPackets(self):
        while True:    
            if (self.directtx):
                data = self.get_data_direct()
            else:
                data = self.get_data()
            packet = {}
            packet.update(self.parse_page(data))
            if packet:
                yield packet
                        
                if (self.directtx):
                    sleeptime = self.poll_interval
                else:
                    #print time.time()
                    #print to_int(packet['dateTime'])
                    sleeptime = self.poll_interval - time.time() + to_int(packet['dateTime'])
                    #print sleeptime
                if ( sleeptime < 0 ):
                    sleeptime=self.dup_interval
                time.sleep(sleeptime)
            else:
                #loginf('No data or duplicate packet')
                time.sleep(self.dup_interval)

    def get_data(self):
        data = {}
        for count in range(self.max_tries):
            try:
                with open(self.xferfile,'r') as f:
                    for line in f:
                        eq_index = line.index('=')
                        name = line[:eq_index].strip()
                        data[name] = line[eq_index + 1:].strip()
                f.close
                return data
            except (IOError, ValueError):
                logerr('data retrieval failed attempt %d of %d: %s' %
                       (count+1, self.max_tries, ''))
                time.sleep(self.retry_wait)
        else:
            logerr('data retrieval failed after %d tries' % self.max_tries)
        return None

    def get_data_direct(self):
        data = self.obshardware.data()
        data['epoch'] = to_int(time.time())
        return data

    def parse_page(self, data):
        packet = {}
        if data is not None:
            packet['usUnits'] = weewx.US
            for obs in self.map:
                try:
                    packet[obs]=self.map[obs][1](data[self.map[obs][0]])
                except KeyError:
                    loginf("packet missing %s" % obs)
                    packet = {}
                    break

            if packet:
                currrain = packet['rain']
                if self.lastrain is not None:
                    if (currrain >= self.lastrain):
                        packet['rain'] = currrain - self.lastrain
                else:
                    del packet['rain']
                self.lastrain = currrain

                if self.lastpacket >= packet['dateTime']:
                    loginf("duplicate packet or out of order packet")
                    packet = {}
                else:
                    logdbg("packet interval %s" % (to_int(packet['dateTime']) - self.lastpacket))
                    self.lastpacket = packet['dateTime']
        
        return packet

    def norm(self, val):
        if (val == 'Normal'):
            return 0
        else:
            return 1

    def chkcalib(self,calibdata):
        stcalib = self.obshardware.getcalibration()
        for i in calibdata:
            if(to_float(calibdata[i]) != to_float(stcalib[i])):
                logerr("calibration error: %s is expexted to be %f but is %f" % 
                       (i, to_float(calibdata[i]), to_float(stcalib[i])))
                return True
        return False

    def chkunits(self, bound):
        data = self.obshardware.getstationsettings(True);
        for i in bound:
            if i in data:
                if ( bound[i] != data[i]):
                    logerr("%s expexted in unit %s but is in %s" % (i, bound[i], data[i]))
                    return True
        return False



# =============================================================================



class ObserverIPConfEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[ObserverIP]
    # This section is for the weewx ObserverIP driver

    # hostname - hostname or IP address of the ObserverIP, not required

    # direct is the method for obtaining the data from the station
    # 	   direct - communicate directly with the station
    #	   indirect - get station data from the CGI intermediary
    direct = true

    # poll_interval
    #	direct=true  - The time (in seconds) between LOOP packets (should be 16)
    #	direct=false - Time to wait for new packet ( 17 is a good value)
    poll_interval = 16

    # dup_interval
    #	direct=true  - time to wait if there is an error getting a packet
    #	direct=false - subsequent time to wait if new packet has not arived after poll_interval
    dup_interval = 2

    # xferfile
    #	direct=true  - unused
    #	direct=false - file where the CGI script puts the data from the observerip
    xferfile = /path/to/transfer/file

    # retry_wait - time to wait after failed network attempt

    # check_calibration - check to make sure the calibration in the station is as expected
    check_calibration = true

    # set_calibration - set calibration in station if it is not as expected, only meaningful if check_calibration is true
    # not implemented
    set_calibration = false

    # The driver to use:
    driver = user.observerip

    # The calibration the driver expects from the station, only useful if check_calibration is set. Items that are not set,
    # are not checked
    [[calibration]]
	RainGain=1.00
	windDirOffset=0
	inHumiOffset=0
	AbsOffset=0.00
	UVGain=1.00
	SolarGain=1.00
	WindGain=1.00
	#RelOffset=0.00
	luxwm2=126.7
	outHumiOffset=0
	outTempOffset=0.0
	inTempOffset=0.0
"""


# =============================================================================


class ObserverIPConfigurator(weewx.drivers.AbstractConfigurator):
    @property
    def description(self):
        return """Configures the Ambient ObserverIP"""

    #@property
    #def usage(self):
    #    return """Usage: """

    def add_options(self, parser):
        super(ObserverIPConfigurator, self).add_options(parser)

        parser.add_option("--findobserver", dest="findobserver",
                          action="store_true",
                          help="Find the observerIP on the network")

        parser.add_option("--getdata", dest="getdata",
                          action="store_true",
                          help="print weather data from the station")

        parser.add_option("--defaultconfig", dest="defconf",
                          action="store_true",
                          help="show the default configuration for weewx.conf")

    def do_options(self, options, parser, config_dict, prompt):
        driver_dict=config_dict['ObserverIP']
        obshardware = OpserverIPHardware(**driver_dict)

        if options.findobserver:
            sys.stdout.write("http://%s\n" % obshardware.ipaddr())
            try:
                hostname = socket.gethostbyaddr(obshardware.ipaddr())[0]
                print "or"
                sys.stdout.write("http://%s\n" % hostname)
            except:
                pass

        if options.getdata:
            data=obshardware.data()
            for obs in data:
                sys.stdout.write("%s=%s\n" % (obs, data[obs]))

        if options.defconf:
            stconf = ObserverIPConfEditor()
            print stconf.default_stanza

    def areyousure(self, prompt=True, msg=''):
        if prompt:
            print msg
            ans = ''
            while ans not in ['y', 'n']:
                ans = raw_input("Are you sure you wish to proceed (y/n)? ")
                if ans == 'y':
                    return True
                elif ans == 'n':
                    print 'Aborting'
                    return False
        else:
            return True


# =============================================================================

# To test this driver, do the following:
#   PYTHONPATH=/home/weewx/bin python /home/weewx/bin/user/observerip.py
if __name__ == "__main__":
    usage = """%prog [options]"""
    import optparse
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--xferfile', dest='xferfile',
                      help='Transfer file')
    parser.add_option('--test-driver', dest='test_driver', action='store_true',
                      help='test the driver')
    parser.add_option('--test-parser', dest='test_parser', action='store_true',
                      help='test the parser')
    (options, args) = parser.parse_args()
    if options.test_parser:
        data = []
        with open('testfile.xml') as f:
            for line in f:
                data.append(line)
        parser = WLParser()
        parser.feed(''.join(data))
        print parser.get_data()
    else:
        import weeutil.weeutil
        station = ObserverIP(xferfile=options.xferfile)
        for p in station.genLoopPackets():
            print weeutil.weeutil.timestamp_to_string(p['dateTime']), p

