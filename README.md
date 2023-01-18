# BeSIM

A simulator for the cloud server the BeSMART thermostat/wifi box connects to.

Note that this project is not affiliated to Riello SpA which produces and sells the BeSMART products.

## What is BeSMART?

BeSMART allows you to connect multiple thermostats to your boiler and control them from your tablet or smartphone.

## What is BeSIM?

A way you can control the BeSMART thermostat from within your own home, without having to use the original cloud server.

It consists of two components:
 - A UDP Server which handles the messaging to/from the BeSMART wifi box.
 - A REST API which allows you to get/set parameters from the BeSMART thermostats.

The intent is that you will be able to use a Home Assistant custom component to control your thermostat(s), but currently this has not been implemented.

## Caveats

This project is currently only a proof-of-concept implementation. Use at your own risk.

It does not yet support:
 - Multiple thermostats
 - OpenTherm parameters when connected via OT
 - There is no authentication on the rest api

## How do I use BeSIM?

Currently BeSIM is a standalone python3 script. Just run 'python app.py' to start the server.

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


