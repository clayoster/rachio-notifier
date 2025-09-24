#!/usr/bin/env python3

# Rachio Docs
# https://support.rachio.com/en_us/public-api-documentation-S1UydL1Fv
# https://rachio.readme.io/reference/rate-limiting
# Obtaining your API Token
# https://rachio.readme.io/reference/authentication

from datetime import datetime, timedelta
import pytz
import os.path
import http.client
import urllib.request
import json
import syslog

# Configuration
jsondata = '/var/lib/misc/sprinklers.json'
timezone = 'America/Chicago'

# Rachio API Configuration
rachio_api_token = os.environ.get('rachio_api_token', None)
rachio_device_id = os.environ.get('rachio_device_id', None)

# Pushover API Configuration
pushover_user_key = os.environ.get('pushover_user_key', None)
pushover_api_token = os.environ.get('pushover_api_token', None)

def syslog_msg(msg):
    #syslog.syslog(msg)
    print(msg)

def notification(message):
    #syslog_msg("i should be notifying!")
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
        with open(jsondata, 'r') as f:
            data = json.load(f)
            if "nextRun" in data:
                old_nextRun = data["nextRun"]
            else:
                syslog_msg("nextRun not found in file")
                old_nextRun = None

            if "reminder" in data:
                old_reminder = data["reminder"]
            else:
                syslog_msg("reminder not found in file")
                old_reminder = None

            f.close()
            return old_nextRun, old_reminder
    else:
        syslog_msg("file not found: " +jsondata +". Fetch new data and exit")
        nextRun = get_nextrun()
        reminder = None
        #notification_sent = "no"
        write_persistent_data(nextRun,reminder)
        exit()

def write_persistent_data(nextRun,reminder):
    data = {'nextRun': nextRun, 'reminder': reminder}
    with open(jsondata, 'w') as f:
        json.dump(data, f)
        f.close()

# Not used currently
def get_nextrun():
    req = urllib.request.Request(url="https://cloud-rest.rach.io/device/listZones/"+rachio_device_id)
    req.add_header('Authorization', 'Bearer '+rachio_api_token)
    responseData = urllib.request.urlopen(req).read().decode()
    nextRun = json.loads(responseData)['zoneSummary'][0]['zoneState']['nextRun']

    return nextRun

def get_devicestate():
    req = urllib.request.Request(url="https://cloud-rest.rach.io/device/getDeviceState/"+rachio_device_id)
    req.add_header('Authorization', 'Bearer '+rachio_api_token)
    responseData = urllib.request.urlopen(req).read().decode()
    responseData_State = json.loads(responseData)['state']

    if "state" in responseData_State:
        deviceState = responseData_State['state']
    else:
        deviceState = None

    if "nextRun" in responseData_State:
        nextRun = responseData_State['nextRun']
    else:
        nextRun = None

    return deviceState, nextRun

def time_magic(nextRun):
    epoch = datetime(1970, 1, 1)

    #mytime = "2009-03-08T00:27:31.807Z"
    myformat = "%Y-%m-%dT%H:%M:%SZ"
    nextRun_datetime = datetime.strptime(nextRun, myformat)
    nextRunSeconds = (nextRun_datetime - epoch).total_seconds()
    nextRunDay = datetime.strftime(nextRun_datetime, "%A")

    # Convert datetime object to UTC
    utc_timezone = pytz.timezone("UTC")
    nextRun_datetime_UTC = utc_timezone.localize(nextRun_datetime)

    # Convert to local timezone
    local_timezone = pytz.timezone(timezone)
    nextRun_datetime_local = nextRun_datetime_UTC.astimezone(local_timezone)

    # Capture current time and hour
    currentTime = datetime.now()
    currentTimeHour = int(datetime.strftime(currentTime, "%-H"))

    # Evaluate nextRun time and date
    nextRunTime = datetime.strftime(  nextRun_datetime_local, "%-H:%M%p")
    nextRunDate = datetime.strftime(  nextRun_datetime_local, "%-m/%-d")
    tomorrowDate = (datetime.now() + timedelta(1)).strftime("%-m/%-d")

    if nextRunDate == tomorrowDate:
        tomorrow = True
    else:
        tomorrow = False

    return currentTimeHour, nextRunSeconds, nextRunDay, nextRunTime, nextRunDate, tomorrow

old_nextRun, old_reminder = load_persistent_data()
deviceState, nextRun = get_devicestate()

# Only evaluate schedule changes if device is idle
if deviceState == 'IDLE':
    if nextRun != None:
        currentTimeHour, nextRunSeconds, nextRunDay, nextRunTime, nextRunDate, tomorrow = time_magic(nextRun)
    else:
        syslog_msg('No future watering events scheduled. Exiting script')
        exit()

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
    if currentTimeHour in range(18, 22):
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
    syslog_msg('Sprinklers are currently running, exit')
    exit()
elif deviceState == 'STANDBY':
    syslog_msg('Controller is in standby mode, no reason to evaluate schedule.')
    exit()
