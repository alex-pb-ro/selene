#!/usr/bin/bash

docker build -t selene .

docker run -it --rm -v "$(pwd)":/workspace selene
