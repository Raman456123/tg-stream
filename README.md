---
title: TG Gallery Streamer
emoji: 🎞️
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
app_port: 7860
---

# TG Gallery Streamer

High-performance Telegram File Streamer for Android Gallery App.

## Deployment

1. Set the following secrets in Space Settings:
   - `API_ID`
   - `API_HASH`
   - `BOT_TOKEN`
   - `BIN_CHANNEL`
   - `PORT` (Must be 7860)

2. Android App connects to `https://THIS_SPACE_URL/api/list`
