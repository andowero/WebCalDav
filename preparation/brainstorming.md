Project Name

# Brainstorming

I want to implement simple web calendar application that I can host at calendar.zdeneknovak.one using a reverse proxy. It will connect to my CalDAV server and show and edit calendar events. It will be password protected. Each user will have their own set of calendars.

Each user will be able to select multiple CalDav servers and select multiple calendars from each server. Each calendar will have its own color (default will be color extracted from the CalDav server, or blue).

At first, the app will use simply SQLite for storage (don't forget to securely store the passwords).

I have found existing solutions - AgenDav and InfCloud - but both are old and unmaintained. Reddit consensus is that there are currently no self-hosted options short of NextCloud - which is kinda heavy.

Application doesn't need to implement TLS, it will be hidden behind reverse proxy.

Application will be deployed using docker compose, so DOCKERFILE and some way of publishing the docker image is needed.

The calendar will need to implement month view, week view and day view. It will show events in the colors of their respective calendars. First day of the week must be selectable by the user.
User can select their timezone (default will be taken from the browser, or computer or something like that).
Each event will be clickable and editable. We will try to implement all possible attributes of events.
Event can start and end at specific time or it can be "all day" event that fills the whole day (or days, it can take multiple days).

App must be able to handle reminders and interact with the browser notification solution (I don't know how that works). It should work for firefox, chrome, opera and safari.

The app should work on mobile browsers too, but it is not priority. Mobile devices have appy for that.

App will store user settings, CalDav server credentials (securely) and selected calendar colors. Events will be stored directly to and modified on the CalDav server without any kind of caching.

App should provide monitoring endpoints, maximally standardized, something like `/health` and `/metrics` (active sessions, CalDav request latency, error counts...). App should provide logging with various levels (DEBUG, INFO).

Stack recommendation: Python + FastAPI + FullCalendar.js
Python has `caldav` and `FastAPI` gives us async, auto-OpenAPI docs, and a Prometheus middleware in a few lines. `FullCalendar.js` is the standard calendar widget. Avoid anything that pulls in a heavy framework; this is a small app.


# Questions

## Q1: What are we really trying to do? What are the goals for our project?

We try to view my Radicale calendar in a Web browser. I need to connect to my calendar at work and I don't want to install any software on my work computer. I used Google Calendar but I moved away from Google ecosystem. On Ubuntu I use its native calendar app and on Android I use its native calendar app.

## Q2: What are the milestones of functionality?

+--------------+-------------------------------------------------------+
| MVP          | Secure user loging, read only view of calendar events |
+--------------+-------------------------------------------------------+
| v1           | Editing of calendar events                            |
+--------------+-------------------------------------------------------+
