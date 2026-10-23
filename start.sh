#!/bin/sh
# API on an internal port; the web server on Render's public $PORT proxies /api/* to it.
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API=$!
cd /web && PORT=${PORT:-10000} node server.js &
WEB=$!
# If either process exits, stop the container so Render restarts it.
while kill -0 $API 2>/dev/null && kill -0 $WEB 2>/dev/null; do sleep 5; done
kill $API $WEB 2>/dev/null
exit 1
