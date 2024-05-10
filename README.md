# NetCheck API

NetCheck API is an simple network monitoring API. It's designed to be used in combination with a monitoring tool. The Docker container exposes endpoints to ping IP addresses, conduct TCP port scans and check available access points. Secure the exposed port and start checking the status of your (local) network.

## Installation
To run the container, use the following command:
```bash
docker run --privileged -d -e PORT=2025 -e API_KEY=123456789 -e DEVICE=wlan0 -e --network host --restart=always purplebite/netcheck-api:latest
```
NetCheck API is now running on http://localhost:2025.

- If the API key is not specified during container startup no API key is required.
- If the DEVICE variable is not passed during container startup, the default value is set to wlan0. If you're unsure about the device name, you can use the `ifconfig` command to find the name of the WiFi interface. To install use `sudo apt install net-tools` .

## Usage
When NetCheck API is running it listens for incoming HTTP requests.Three endpoints are available:

1. Ping: Used for checking the reachability of IP addresses
2. TCP port scans: Employed to scan for open ports on specified IP addresses
3. Access point verification: Enables the examination of available access points

### Ping Endpoint

To check the status of an IP address, send a GET request to `/ping/<ip_address>` with the API key provided as a query parameter. 

**Example Request:**
```
GET http://localhost:2025/ping/192.168.1.1?api_key=123456789
```

**Example Response (Success):**
```json
{
    "status": "success"
}
```

**Example Response (Error):**
```json
{
    "status": "error"
}
```

### TCP Check Endpoint

To conduct a TCP port scan on a specific port of an IP address, send a GET request to `/tcp-check/<ip_address>/<port>` with the API key provided as a query parameter.

**Example Request:**
```
GET http://localhost:2025/tcp-check/192.168.1.2/80?api_key=123456789
```

**Example Response (Success):**
```json
{
    "status": "success"
}
```

**Example Response (Error):**
```json
{
    "status": "error"
}
```

### Access Points Endpoint

To get a list of access points along with their signal strengths, send a GET request to `/accesspoints` with the API key provided as a query parameter.

**Example Request:**
```
GET http://localhost:2025/accesspoints?api_key=123456789
```

**Example Response (Success):**
```json
{
    "access_points": [
        {
            "SSID": "Guest",
            "signal_strength": -26.0
        }
    ],
    "status": "success"
}
```

**Example Response (Error):**
```json
{
    "status": "error"
}
```
## Notes

- NetCheck API is designed for [Raspberry Pi](https://www.raspberrypi.com/), but works on all Linux machines
- The easiest way to secure the exposed port is via a [Cloudflare Tunnel](https://www.reddit.com/r/selfhosted/comments/tp0nqg/cloudflare_has_added_a_web_gui_for_controlling/)


