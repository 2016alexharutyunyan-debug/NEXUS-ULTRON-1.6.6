# NEXUS ULTRON 1.6.6 — Windows Desktop AI & Voice Assistant

NEXUS ULTRON is a Python desktop AI assistant for Windows, combining voice interaction, hand-gesture controls, and cloud-synced chat history. Supabase Auth manages user accounts, while Row Level Security (RLS) keeps each user's cloud data private.

## Features

- Windows desktop AI assistant with voice and gesture controls
- Full-screen account registration and login at startup
- Supabase authentication and per-user cloud chat persistence
- Supabase publishable key with RLS; no service-role key in the desktop app

## Quick start

1. Download or clone this repository on Windows.
2. Run `START_NEXUS_SUPABASE.bat`.
3. Register or log in in the full-screen account window.

## One-time Supabase database setup

The project owner must run [`payload/supabase_schema.sql`](payload/supabase_schema.sql) once in the Supabase SQL Editor. New users can then register in the app. Accounts appear in **Authentication → Users**; profiles and chat history are stored in the `nexus_profiles` and `nexus_messages` tables.

The project URL and publishable key are preconfigured. Do not add a Supabase secret or service-role key to the desktop application. See [`SUPABASE_SETUP_HY.txt`](SUPABASE_SETUP_HY.txt) for setup instructions in Armenian.

## Project details

- Platform: Windows desktop
- Language: Python
- Authentication and cloud database: Supabase
- Repository: [2016alexharutyunyan-debug/NEXUS-ULTRON-1.6.6](https://github.com/2016alexharutyunyan-debug/NEXUS-ULTRON-1.6.6)
