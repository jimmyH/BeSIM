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

