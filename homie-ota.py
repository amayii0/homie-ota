#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__    = 'Jan-Piet Mens <jpmens()gmail.com> & Ben Jones'
__copyright__ = 'Copyright 2016 Jan-Piet Mens'

# wget http://bottlepy.org/bottle.py
# ... or ... pip install bottle
from bottle import get, request, run, static_file, HTTPResponse
import paho.mqtt.client as paho   # pip install paho-mqtt
import StringIO
import os
import logging
import ConfigParser
import atexit
from persist import PersistentDict
import json
import fileinput



# Script name (without extension) used for config/logfile names
APPNAME = os.path.splitext(os.path.basename(__file__))[0]
INIFILE = os.getenv('INIFILE', APPNAME + '.ini')
LOGFILE = os.getenv('LOGFILE', APPNAME + '.log')

# Read the config file
config = ConfigParser.RawConfigParser()
config.read(INIFILE)

# Use ConfigParser to pick out the settings
DEBUG = config.getboolean("global", "DEBUG")
OTA_HOST = config.get("global", "OTA_HOST")
OTA_PORT = config.getint("global", "OTA_PORT")
OTA_ENDPOINT = config.get("global", "OTA_ENDPOINT")
OTA_FIRMWARE_ROOT = config.get("global", "OTA_FIRMWARE_ROOT")

MQTT_HOST = config.get("mqtt", "MQTT_HOST")
MQTT_PORT = config.getint("mqtt", "MQTT_PORT")
SENSOR_PREFIX = config.get("mqtt", "SENSOR_PREFIX")

# Initialise logging
LOGFORMAT = '%(asctime)-15s %(levelname)-5s %(message)s'

if DEBUG:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.DEBUG,
                        format=LOGFORMAT)
else:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.INFO,
                        format=LOGFORMAT)

logging.info("Starting " + APPNAME)
logging.info("INFO MODE")
logging.debug("DEBUG MODE")
logging.debug("INIFILE = %s" % INIFILE)
logging.debug("LOGFILE = %s" % LOGFILE)

db = PersistentDict(os.path.join(OTA_FIRMWARE_ROOT, 'inventory.json'), 'c', format='json')

def exitus():
    db.close()
    print "CIAO"


@get('/')
def index():
    text =  """Homie OTA server running.
    OTA endpoint is: http://{host}:{port}/{endpoint}
    Firmware root is {fwroot}\n""".format(host=OTA_HOST,
            port=OTA_PORT, endpoint=OTA_ENDPOINT, fwroot=OTA_FIRMWARE_ROOT)

    for root, dirs, files in os.walk(OTA_FIRMWARE_ROOT):
        path = root.split('/')
        text = text + "\t%s %s\n" % ((len(path) - 1) * '--', os.path.basename(root))
        for file in files:
            if file[0] == '.':
                continue
            text = text + "\t\t%s %s\n" % (len(path) * '---', file)

    text = text + "\n\n"
    text = text + "Inventory"

    for device in db:
        text = text + db[device]['name']
    return text


# X-Esp8266-Ap-Mac = 1A:FE:34:CF:3A:07
# X-Esp8266-Sta-Mac = 18:FE:34:CF:3A:07
# X-Esp8266-Free-Space = 684032
# X-Esp8266-Chip-Size = 4194304
# X-Esp8266-Mode = sketch
# Content-Length =
# X-Esp8266-Sdk-Version = 1.5.2(7eee54f4)
# Host = 192.168.1.130
# X-Esp8266-Sketch-Size = 360872
# Connection = close
# User-Agent = ESP8266-http-Update
# X-Esp8266-Version = cf3a07e0=h-sensor=1.0.1=1.0.2
# Content-Type = text/plain

@get(OTA_ENDPOINT)
def ota():

    headers = request.headers
    for k in headers:
        logging.debug(k + ' = ' + headers[k])

    # TODO: check free space vs .bin file on disk and refuse

    try:
        device, firmware_name, have_version, want_version = headers.get('X-Esp8266-Version', None).split('=')
    except:
        logging.warn("Can't find X-Esp8266-Version in headers; returning 403")
        return HTTPResponse(status=403, body="Not permitted")

    logging.info("Homie firmware=%s, have=%s, want=%s on device=%s" % (firmware_name, have_version, want_version, device))

    # <firmware_root>/<firmware_name>/<firmware_name-x.x.x.bin
    # e.g. './h-sensor/h-sensor-1.0.3.bin'
    firmware_path = "%s/%s" % (OTA_FIRMWARE_ROOT, firmware_name)
    binary = "%s-%s.bin" % (firmware_name, want_version)
    binary_path = "%s/%s" % (firmware_path, binary)

    if not os.path.exists(binary_path):
        logging.warn("%s not found; returning 403" % (binary_path))
        return HTTPResponse(status=403, body="Firmware not found")

    logging.info("Return OTA firmware %s" % (binary_path))
    return static_file(binary, root=firmware_path)


def on_connect(mosq, userdata, rc):
    for suffix in [ '$signal', '$uptime', '$name', '$online', '$fwname', '$fwversion' ]:
        mqttc.subscribe("%s/+/%s" % (SENSOR_PREFIX, suffix), 0)


def on_message(mosq, userdata, msg):
    print "%s (qos=%s, r=%s) %s" % (msg.topic, str(msg.qos), msg.retain, str(msg.payload))

    t = str(msg.topic)
    t = t[len(SENSOR_PREFIX) + 1:]      # remove SENSOR_PREFIX/ from begining of topic
    
    device, key = t.split('/')
    key = key[1:]                       # remove '$'
    
    if device not in db:
        db[device] = {}
    db[device][key] = str(msg.payload)

def on_disconnect(mosq, userdata, rc):

    reasons = {
       '0' : 'Connection Accepted',
       '1' : 'Connection Refused: unacceptable protocol version',
       '2' : 'Connection Refused: identifier rejected',
       '3' : 'Connection Refused: server unavailable',
       '4' : 'Connection Refused: bad user name or password',
       '5' : 'Connection Refused: not authorized',
    }
    reason = reasons.get(rc, "code=%s" % rc)
    print "Disconnected: ", reason

def on_log(mosq, userdata, level, string):
    print(string)

if __name__ == '__main__':

    mqttc = paho.Client("%s-%d" % (APPNAME, os.getpid()), clean_session=True, userdata=None, protocol=paho.MQTTv311)
    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    # Uncomment to enable debug messages
    #mqttc.on_log = on_log

    # mqttc.username_pw_set('john', 'secret')

    mqttc.connect("localhost", MQTT_PORT, 60)

    mqttc.loop_start()

    atexit.register(exitus)

    try:
        run(host=OTA_HOST, port=OTA_PORT, debug=DEBUG)
    except KeyboardInterrupt:
        mqttc.loop_stop()
        mqttc.disconnect()
        sys.exit(0)
    except:
        raise
