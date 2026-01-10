#!/bin/sh

docker compose down barefoot-map barefoot-tracker barefoot-matcher -v

docker compose up --wait barefoot-map

sleep 20

docker compose up -d barefoot-tracker barefoot-matcher

sleep 20

docker compose ps -a

docker compose down barefoot-map barefoot-tracker barefoot-matcher