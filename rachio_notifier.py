#!/usr/bin/env python3

"""
Evalutes the next scheduled run time for a Rachio sprinkler controller
and sends a notification if the schedule has changed
"""

from datetime import datetime, timedelta
import os
import sys
import syslog
import json
import http.client
import urllib.parse
import pytz

# Configuration
JSONDATA = '/var/lib/misc/sprinklers.json'
TIMEZONE = os.environ.get('TIMEZONE', 'America/Chicago')

# Rachio API Configuration
RACHIO_API_TOKEN = os.environ.get('RACHIO_API_TOKEN', None)
RACHIO_DEVICE_ID = os.environ.get('RACHIO_DEVICE_ID', None)

# Pushover API Configuration
PUSHOVER_USER_KEY = os.environ.get('PUSHOVER_USER_KEY', None)
PUSHOVER_API_TOKEN = os.environ.get('PUSHOVER_API_TOKEN', None)

# Determine if this is running in a container. Using alpine-release file
# for detection as that is the base image for the container build
container = os.path.exists("/etc/alpine-release")

# If the script is being run in a container, log to stdout
# Otherwise log to syslog
def log_msg(msg):
    """ Log message to stdout or syslog depending on if we are in a container or not"""
    if container:
        print(msg)
    else:
        syslog.syslog(msg)

def notification(message):
    """ Send notification via Pushover """
    conn = http.client.HTTPSConnection("api.pushover.net:443", timeout=10)
    conn.request("POST", "/1/messages.json",
      urllib.parse.urlencode({
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "message": message,
      }), { "Content-type": "application/x-www-form-urlencoded" })
    conn.getresponse()
    conn.close()

def load_persistent_data():
    """ Load persistent data from JSON file """
    if os.path.isfile(JSONDATA):
        with open(JSONDATA, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "next_run" in data:
                _old_next_run = data["next_run"]
            else:
                log_msg("next_run not found in file")
                _old_next_run = None

            if "reminder" in data:
                _old_reminder = data["reminder"]
            else:
                log_msg("reminder not found in file")
                _old_reminder = None

            f.close()
            return _old_next_run, _old_reminder
    else:
        log_msg("file not found: " + JSONDATA +". Fetch new data and exit")
        _device_state, _next_run = get_devicestate()
        _reminder = False
        #notification_sent = "no"
        write_persistent_data(_next_run,_reminder)
        sys.exit()

def write_persistent_data(_next_run,_reminder):
    """ Write persistent data to JSON file """
    data = {'next_run': _next_run, 'reminder': _reminder}
    with open(JSONDATA, 'w', encoding='utf-8') as f:
        json.dump(data, f)
        f.close()

# Not used currently
def get_nextrun():
    """ Get the next scheduled run time from the Rachio API """
    conn = http.client.HTTPSConnection("cloud-rest.rach.io", timeout=10)
    headers = {"Authorization": "Bearer " + RACHIO_API_TOKEN}
    conn.request("GET", "/device/listZones/" + RACHIO_DEVICE_ID, headers=headers)
    response = conn.getresponse()
    response_data = response.read().decode()
    conn.close()

    _next_run = json.loads(response_data)["zoneSummary"][0]["zoneState"]["nextRun"]
    return _next_run

def get_devicestate():
    """ Get the device state and next scheduled run time from the Rachio API """
    conn = http.client.HTTPSConnection("cloud-rest.rach.io", timeout=10)
    headers = {"Authorization": "Bearer " + RACHIO_API_TOKEN}
    conn.request("GET", "/device/getDeviceState/" + RACHIO_DEVICE_ID, headers=headers)
    response = conn.getresponse()
    response_data = response.read().decode()
    conn.close()

    response_data_state = json.loads(response_data)["state"]

    if "state" in response_data_state:
        _device_state = response_data_state['state']
    else:
        _device_state = None
        msg = "Unable to determine device state from Rachio API"
        log_msg(msg)

    if "nextRun" in response_data_state:
        _next_run = response_data_state['nextRun']
    else:
        _next_run = None
        msg = "No future watering events are scheduled."
        log_msg(msg)

    return _device_state, _next_run

def time_magic(_next_run):
    """ Convert next_run time to local timezone and deterine if next_run time is tomorrow """
    # Convert next_run string to datetime object
    _myformat = "%Y-%m-%dT%H:%M:%SZ"
    _next_run_datetime = datetime.strptime(_next_run, _myformat)
    _next_run_day = datetime.strftime(_next_run_datetime, "%A")

    # Convert datetime object to UTC
    _utc_timezone = pytz.timezone("UTC")
    _next_run_datetime_utc = _utc_timezone.localize(_next_run_datetime)

    # Convert to local timezone
    _local_timezone = pytz.timezone(TIMEZONE)
    _next_run_datetime_local = _next_run_datetime_utc.astimezone(_local_timezone)

    # Capture current time and hour
    _current_time = datetime.now(_local_timezone)
    _current_time_hour = int(datetime.strftime(_current_time, "%-H"))

    # Evaluate next_run time and date
    _next_run_time = datetime.strftime(_next_run_datetime_local, "%-H:%M%p")
    _next_run_date = datetime.strftime(_next_run_datetime_local, "%-m/%-d")
    _tomorrow_date = (_current_time + timedelta(1)).strftime("%-m/%-d")

    # Determine if the next_run is tomorrow
    _tomorrow = _next_run_date == _tomorrow_date

    return _current_time_hour, _next_run_day, _next_run_time, _next_run_date, _tomorrow

def main(): # pylint: disable=too-many-branches
    """ Main function """
    # Fetch persistent data and device state
    old_next_run, old_reminder = load_persistent_data()
    device_state, next_run = get_devicestate()

    # Only evaluate schedule changes if device is idle
    if device_state == 'IDLE':
        if next_run is not None:
            (
                current_time_hour, next_run_day, next_run_time, next_run_date, tomorrow
            ) = time_magic(next_run)
        else:
            sys.exit()

        if next_run != old_next_run:
            # Schedule has changed
            if tomorrow:
                msg = "Next Run: Tomorrow at " +next_run_time
                log_msg("Irrigation Schedule Changed - " + msg)
                notification("Irrigation Schedule Changed\n" + msg)
            else:
                msg = (
                    "Next Run: " +next_run_day + " " + next_run_date + " at " + next_run_time
                )
                log_msg("Irrigation Schedule Changed - " + msg)
                notification("Irrigation Schedule Changed\n" + msg)

            # Set reminder to false if the scheduled run is not tomorrow.
            # If it is, a second notification about the schedule would be redundant.
            if not tomorrow:
                reminder = False
            else:
                reminder = True

        else:
            msg = "No change to irrigation schedule was detected"
            log_msg(msg)

        # If the hour is between 6pm and 10pm and the next run is tomorrow,
        # send a notification is one hasn't already been sent.
        if 18 <= current_time_hour <= 22:
            if tomorrow:
                # If next_run is tomorrow
                if not old_reminder:
                    # If a reminder hasn't already been sent
                    msg = "Sprinklers will run tomorrow at " + next_run_time
                    log_msg("Reminder: " + msg)
                    notification("Reminder\n" + msg)
                    reminder = True

        # If the reminder variable was not set in this block, assign it the value from old_reminder
        try:
            reminder # pylint: disable=used-before-assignment
        except NameError:
            reminder = old_reminder

        write_persistent_data(next_run,reminder)

    elif device_state == 'WATERING':
        log_msg('Sprinklers are currently running. Not evaluating the schedule at this time.')
        sys.exit()
    elif device_state == 'STANDBY':
        log_msg('Controller is in hibernation mode. No schedule to evaluate.')
        sys.exit()

# Call main function
if __name__ == "__main__":
    main()
