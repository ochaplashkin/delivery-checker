#!/bin/sh

# Exit when any command in script file fails
set -e

# Preparation commands

# To install tzdata in docker
# https://dev.to/setevoy/docker-configure-tzdata-and-timezone-during-build-20bk
ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# To download and execute tarantool install script
apt-get update
apt-get -y install curl sudo
