#!/usr/bin/env python3

# Rachio Docs
# https://support.rachio.com/en_us/public-api-documentation-S1UydL1Fv
# https://rachio.readme.io/reference/rate-limiting
# Obtaining your API Token
# https://rachio.readme.io/reference/authentication

from datetime import datetime, timedelta
import os
import sys
import syslog
import json
import http.client
import urllib.parse
import urllib.request
import pytz

# Configuration
jsondata = '/var/lib/misc/sprinklers.json'
timezone = os.environ.get('timezone', 'America/Chicago')

# Rachio API Configuration
rachio_api_token = os.environ.get('rachio_api_token', None)
rachio_device_id = os.environ.get('rachio_device_id', None)

# Pushover API Configuration
pushover_user_key = os.environ.get('pushover_user_key', None)
pushover_api_token = os.environ.get('pushover_api_token', None)

# Determine if this is running in a container. Using alpine-release file
# for detection as that is the base image for the container build
container = os.path.exists("/etc/alpine-release")

# If the script is being run in a container, log to stdout
# Otherwise log to syslog
def log_msg(msg):
    if container:
        print(msg)
    else:
        syslog.syslog(msg)

def notification(message):
    #log_msg("i should be notifying!")
    conn = http.client.HTTPSConnection("api.pushover.net:443")
    conn.request("POST", "/1/messages.json",
      urllib.parse.urlencode({
        "token": pushover_api_token,
        "user": pushover_user_key,
        "message": message,
      }), { "Content-type": "application/x-www-form-urlencoded" })
    conn.getresponse()

def load_persistent_data():
    if os.path.isfile(jsondata):
        with open(jsondata, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "nextRun" in data:
                _old_nextRun = data["nextRun"]
            else:
                log_msg("nextRun not found in file")
                _old_nextRun = None

            if "reminder" in data:
                _old_reminder = data["reminder"]
            else:
                log_msg("reminder not found in file")
                _old_reminder = None

            f.close()
            return _old_nextRun, _old_reminder
    else:
        log_msg("file not found: " + jsondata +". Fetch new data and exit")
        _nextRun = get_nextrun()
        _reminder = False
        #notification_sent = "no"
        write_persistent_data(_nextRun,_reminder)
        sys.exit()

def write_persistent_data(_nextRun,_reminder):
    data = {'nextRun': _nextRun, 'reminder': _reminder}
    with open(jsondata, 'w', encoding='utf-8') as f:
        json.dump(data, f)
        f.close()

# Not used currently
def get_nextrun():
    req = urllib.request.Request(url="https://cloud-rest.rach.io/device/listZones/"+rachio_device_id)
    req.add_header('Authorization', 'Bearer '+rachio_api_token)
    responseData = urllib.request.urlopen(req).read().decode()
    _nextRun = json.loads(responseData)['zoneSummary'][0]['zoneState']['nextRun']

    return _nextRun

def get_devicestate():
    req = urllib.request.Request(url="https://cloud-rest.rach.io/device/getDeviceState/"+rachio_device_id)
    req.add_header('Authorization', 'Bearer '+rachio_api_token)
    responseData = urllib.request.urlopen(req).read().decode()
    responseData_State = json.loads(responseData)['state']

    if "state" in responseData_State:
        _deviceState = responseData_State['state']
    else:
        _deviceState = None

    if "nextRun" in responseData_State:
        _nextRun = responseData_State['nextRun']
    else:
        _nextRun = None

    return _deviceState, _nextRun

def time_magic(_nextRun):
    # Convert nextRun string to datetime object
    _myformat = "%Y-%m-%dT%H:%M:%SZ"
    _nextRun_datetime = datetime.strptime(nextRun, _myformat)
    _nextRunDay = datetime.strftime(_nextRun_datetime, "%A")

    # Convert datetime object to UTC
    _utc_timezone = pytz.timezone("UTC")
    _nextRun_datetime_UTC = _utc_timezone.localize(_nextRun_datetime)

    # Convert to local timezone
    _local_timezone = pytz.timezone(timezone)
    _nextRun_datetime_local = _nextRun_datetime_UTC.astimezone(_local_timezone)

    # Capture current time and hour
    _currentTime = datetime.now(_local_timezone)
    _currentTimeHour = int(datetime.strftime(_currentTime, "%-H"))

    # Evaluate nextRun time and date
    _nextRunTime = datetime.strftime(_nextRun_datetime_local, "%-H:%M%p")
    _nextRunDate = datetime.strftime(_nextRun_datetime_local, "%-m/%-d")
    _tomorrowDate = (_currentTime + timedelta(1)).strftime("%-m/%-d")

    # Determine if the nextRun is tomorrow
    _tomorrow = _nextRunDate == _tomorrowDate

    return _currentTimeHour, _nextRunDay, _nextRunTime, _nextRunDate, _tomorrow

old_nextRun, old_reminder = load_persistent_data()
deviceState, nextRun = get_devicestate()

# Only evaluate schedule changes if device is idle
if deviceState == 'IDLE':
    if nextRun != None:
        currentTimeHour, nextRunDay, nextRunTime, nextRunDate, tomorrow = time_magic(nextRun)
    else:
        log_msg('No future watering events scheduled. Exiting script')
        sys.exit()

    if nextRun != old_nextRun:
        # Schedule has changed
        if tomorrow:
            notification("Irrigation Schedule Changed\nNext Run: Tomorrow at " +nextRunTime)
        else:
            notification("Irrigation Schedule Changed\nNext Run: " +nextRunDay + " " + nextRunDate + " at " +nextRunTime)

        # Set reminder to false if the scheduled run is not tomorrow. If it is, a second notification
        # about the schedule would be redundant.
        if not tomorrow:
            reminder = False
        else:
            reminder = True

    # If the hour is between 6pm and 10pm and the next run is tomorrow, send a notification is one
    # hasn't already been sent.
    if 18 <= currentTimeHour <= 22:
        if tomorrow:
            # If nextRun is tomorrow
            if not old_reminder:
                # If a reminder hasn't already been sent
                notification("Sprinklers will run tomorrow at " +nextRunTime)
                reminder = True

    # If the reminder variable was not set in this block, assign it the value from old_reminder
    try:
        reminder
    except NameError:
        reminder = old_reminder

    write_persistent_data(nextRun,reminder)

elif deviceState == 'WATERING':
    log_msg('Sprinklers are currently running, exit')
    sys.exit()
elif deviceState == 'STANDBY':
    log_msg('Controller is in standby mode, no reason to evaluate schedule.')
    sys.exit()
