# NEXUS ULTRON 1.6.6

Windows desktop assistant with Supabase Auth and per-user cloud chat persistence.

## First-time database setup

Run `payload/supabase_schema.sql` once in the Supabase SQL Editor. After that, users only need to create an account or log in from NEXUS Settings. Accounts appear under **Authentication → Users**; chat rows are stored in `nexus_messages`.

The application uses the Supabase publishable key with row-level security. Never put a Supabase secret or service-role key in the desktop application.

## Launch

Run `START_NEXUS_SUPABASE.bat` on Windows. See `SUPABASE_SETUP_HY.txt` for Armenian setup notes.
