# BeSIM

A simulator for the cloud server the BeSMART thermostat/wifi box connects to.

Note that this project is not affiliated to Riello SpA which produces and sells the BeSMART products.

Meteorological data is kindly provided by: The Norwegian Meteorological Institute

## What is BeSMART?

BeSMART allows you to connect multiple thermostats to your boiler and control them from your tablet or smartphone.

## What is BeSIM?

A way you can control the BeSMART thermostat from within your own home, without having to use the original cloud server.

It consists of two components:
 - A UDP Server which handles the messaging to/from the BeSMART wifi box.
 - A REST API which allows you to get/set parameters from the BeSMART thermostats.

A few ways you can control the thermostat:
 - via the REST API (see curl examples below)
 - via Home Assistant, see https://github.com/jimmyH/ha-besim
 - via a (very) basic angular app, see https://github.com/jimmyH/BeSIM-GUI
 - via an Alexa Skill, if anyone is interested I'll find some time to create an example repository

## Caveats

This project is currently only a **proof-of-concept** implementation. Use at your own risk.

It does not yet support:
 - Multiple thermostats
 - OpenTherm parameters when connected via OT (partly: see "OpenTherm pass-through" below)
 - There is no authentication on the rest api

Note: that CORS (Cross-origin resource sharing) headers are set on the server.

Note: that currently when you modify a value the API may return the old value for up to 40s (the thermostat sends periodic status reports every 40s).

## How do I use BeSIM?

BeSIM can either be run as a standalone python3 script (tested on python3.12 only).
 - It is recommended to run from a virtual environment, and you can install the dependencies from requirements.txt `pip install -r requirements.txt`.
 - To start the server, just run 'python app.py'.

Or run as a container from docker/podman:
 - `docker build . -t besim:latest`
 - `docker run -it -p 80:80 -p 6199:6199/udp besim:latest`

To have the server get the weather at the server location, you need to set your location using environment variables eg:
 - `docker run -it -e LONGITUDE=1.234 -e LATITUDE=-1.234 -p 80:80 -p 6199:6199/udp besim:latest`

The server logs the thermostat status in an sqlite3 database. You can make this persistent by using a docker volume, eg:
 - `docker run -it -e LONGITUDE=1.234 -e LATITUDE=-1.234 -e BESIM_DATABASE=/database/besim.db -v besim_database:/database -p 80:80 -p 6199:6199/udp besim:latest`

The BeSMART thermostat connects:
 - api.besmart-home.com:6199 (udp)
 - api.besmart-home.com:80 (tcp, http get)
 - www.cloudwarm.com:80 (tcp, http post)

To redirect the traffic to BeSIM you need to do one of the following:
 - Configure your NAT router to redirect outgoing traffic with destination api.besmart-home.com to your BeSIM instance. You will probably also need to flush the connection tracking state in the router so it picks up the new destination.
 - Update DNS on your router to change the IP address for api.besmart-home.com to your BeSIM instance. You will probably need to reboot the BeSMART wifi box so it picks up the new IP address.

You should then see traffic arriving on BeSIM from your BeSMART device.

You can then use the rest api to query the state, for example (replace 192.168.0.10 with the IP address of your BeSIM instance):
 - Get a list of connected devices: `curl http://192.168.0.10/api/v1.0/devices`
 - Get a list of rooms (thermostats) from the device: `curl http://192.168.0.10/api/v1.0/devices/<deviceid>/rooms`
 - Get the state of the thermostat: `curl http://192.168.0.10/api/v1.0/devices/<deviceid>/rooms/<roomid>`
 - Set T3 temperature (to 19.2degC): `curl http://192.168.0.10/api/v1.0/devices/<deviceid>/rooms/<roomid>/t3 -H "Content-Type: application/json" -X PUT -d 192`
 - ...

## OpenTherm pass-through

When the wifi box is connected to the boiler via OpenTherm, the cloud can send OpenTherm frames to
the boiler through the wifi box (message type 0x0e). The BeSMART app uses this for its boiler
information screen (modulation, return/flue temperature, operating hours, ...). BeSIM exposes it:

 - Ask the boiler for one OpenTherm data id, e.g. 17 (relative modulation): `curl -X PUT http://192.168.0.10/api/v1.0/devices/<deviceid>/ot/17`
 - Read the answers received so far: `curl http://192.168.0.10/api/v1.0/devices/<deviceid>/ot`
   - `type` is the OpenTherm message type of the answer: 4 READ-ACK, 5 WRITE-ACK, 6 DATA-INVALID, 7 UNKNOWN-DATA-ID
   - `hi`/`lo`/`u16` is the data value; its format depends on the data id (f8.8 for temperatures and modulation, s16 for the flue temperature, ...)
 - Indexed data ids (11 = transparent slave parameters, 13 = fault history buffer) take the index in `hi`: `curl -X PUT "http://192.168.0.10/api/v1.0/devices/<deviceid>/ot/11?hi=22"`, answers per index: `curl http://192.168.0.10/api/v1.0/devices/<deviceid>/ot/11`
 - Writing (`&lo=<value>&write=1`) sends a WRITE-DATA frame. Boiler parameters are normally set by a service technician - only write what you understand.

Notes:
 - The wifi box fits these requests between its own OpenTherm traffic and often does not answer the first time: repeat a request (about once a second, a few times) until the answer arrives.
 - Do not flood it: with many requests in a short time the wifi box stops sending its status reports for a minute or so.
 - Examples of data ids answered by a Beretta MySmart 28 C.S.I.: 17 modulation (%), 25 flow and 28 return temperature, 33 flue temperature, 10 number of transparent slave parameters, 12/13 fault history, 48/49 DHW/CH setpoint bounds, 56 DHW setpoint, 57 max CH setpoint.

Message type 0x0f returns the fault/event history (shown as "Error codes" in the app). There is also a read-only probe for exploring other message types: `curl -X PUT http://192.168.0.10/api/v1.0/devices/<deviceid>/probe/<msgtype>`; replies to message types BeSIM does not handle are logged raw.
