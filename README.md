# Rachio Notifier

This script leverages the Rachio Smart Irrigation Controller API (cloud-rest.rach.io) to monitor
scheduled watering events and send notifications via [Pushover](https://pushover.net/). I built this as I wanted notifications about changes to scheduled irrigation events that were not available through the Rachio app.

## Features

- Retrieves the next irrigation event time from the Rachio API, then sends push notifications for schedule changes and reminders via Pushover as appropriate
- Stores the schedule and reminder state in a local JSON file to avoid duplicate notifications
- Uses the local timezone for accurate schedule evaluation (configurable via `TIMEZONE` environment variable) 
- Supports execution inside or outside of a container
  - **Container** → logs to stdout  
  - **Non-container** → logs to syslog

## Configuration

The script is configured via environment variables:

| Environment Variable | Description                                     |
|----------------------|-------------------------------------------------|
| `RACHIO_API_TOKEN`   | Rachio API authentication token (Required)      |
| `RACHIO_DEVICE_ID`   | Target Rachio device ID (Required)              |
| `PUSHOVER_USER_KEY`  | Pushover user key for notifications (Required)  |
| `PUSHOVER_API_TOKEN` | Pushover API token for notifications (Required) |
| `TIMEZONE`           | Local timezone (default: `America/Chicago`)     |

Documentation for retrieving your Rachio authentication token can be found [here](https://rachio.readme.io/reference/authentication)

To retrieve your Rachio Device ID:
```shell
# Make a request to fetch your Person ID
curl -H 'Authorization: Bearer <your-auth-token-here>' https://api.rach.io/1/public/person/info | jq -r '.id'
    
# Make another request to fetch your Device ID
curl -H 'Authorization: Bearer <your-auth-token-here>' https://api.rach.io/1/public/person/<your-person-id-here> | jq -r '.devices[].id'
```

## Persistent Data

The script stores state information in a JSON file located at `/var/lib/misc/sprinklers.json`. 
This file contains the last known next run time and reminder status, ensuring that duplicate notifications are not sent.

## Exit Behavior

The script will exit under the following conditions:

- No upcoming irrigation events are scheduled.
- The controller is currently in **WATERING** mode.
- The controller is in **STANDBY** mode.

## Deployment methods

### CronJob
Define a cron that sources a .env file with your environment variables defined, then calls the script.  
*This method will require that the pytz module be installed via pip or your OS package manager*

```
1 */2 * 5-10 * . /path/to/.env; python3 /path/to/rachio_notifier.py
```

### CronJob (Container-Based)
Define a cron that will run the script using the pre-built conatiner image using Docker (or podman). 

- Create a .env file with your environment variables defined, and adjust the `--env-file /path/to/.env` part of the command below appropriately
- Adjust `/path/to/data/` to a location of your choosing as the script will need to write the sprinklers.json file there.

```
1 */2 * 5-10 * docker run --rm --name rachio-notifier --env-file /path/to/.env -v /path/to/data/:/var/lib/misc/:rw ghcr.io/clayoster/rachio-notifier:latest
```

### Kubernetes CronJob
This can also be run as a pre-built container image within a Kubernetes cronjob. This example manifest does the following:

- Creates a namespace
- Requests a PVC to store persistent data
- Creates a secret containing the environment variables needed for the script
- Defines a CronJob that uses the pre-built container image, mounts the environment variables from the secret, and mounts the PVC to /var/lib/misc

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rachio-notifier
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: rachio-notifier-pvc
  namespace: rachio-notifier
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Mi
---
apiVersion: v1
kind: Secret
metadata:
    name: rachio-notifier
    namespace: rachio-notifier
type: Opaque
stringData:
    RACHIO_API_TOKEN: *******
    RACHIO_DEVICE_ID: *******
    PUSHOVER_USER_KEY: *******
    PUSHOVER_API_TOKEN: *******
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rachio-notifier
  namespace: rachio-notifier
spec:
  timeZone: "America/Chicago"
  # Run at 1 minute past every 2nd hour from May to October
  schedule: "1 */2 * 5-10 *"
  successfulJobsHistoryLimit: 1 # Keep the last successful job
  failedJobsHistoryLimit: 1 # Keep the last failed job
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: rachio-notifier
              image: ghcr.io/clayoster/rachio-notifier:latest
              env:
              - name: rachio_api_token
                valueFrom:
                  secretKeyRef:
                    name: rachio-notifier
                    key: rachio_api_token
              - name: rachio_device_id
                valueFrom:
                  secretKeyRef:
                    name: rachio-notifier
                    key: rachio_device_id
              - name: pushover_user_key
                valueFrom:
                  secretKeyRef:
                    name: rachio-notifier
                    key: pushover_user_key
              - name: pushover_api_token
                valueFrom:
                  secretKeyRef:
                    name: rachio-notifier
                    key: pushover_api_token
              volumeMounts:
                - name: rachio-notifier-volume
                  mountPath: /var/lib/misc/
          volumes:
            - name: rachio-notifier-volume
              persistentVolumeClaim:
                claimName: rachio-notifier-pvc

```

## References

- [Rachio API Documentation](https://support.rachio.com/en_us/public-api-documentation-S1UydL1Fv)
- [Rachio API Rate Limiting](https://rachio.readme.io/reference/rate-limiting)
- [Pushover](https://pushover.net/)
