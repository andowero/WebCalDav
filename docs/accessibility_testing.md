# Accessibility — manual keyboard test checklist

WebCalDav targets **keyboard operability** (WCAG 2.2: 2.1.1 Keyboard, 2.4.3
Focus Order, 2.4.7 Focus Visible, 2.1.2 No Keyboard Trap) plus **basic
screen-reader semantics on the agenda**. There are no automated browser/E2E
tests (see `CLAUDE.md`), so this checklist is the authoritative "done" for the
accessibility pass: drive the whole app with the keyboard only — no mouse.

Out of scope (deferred): colour-contrast / high-contrast theme, and full
screen-reader support for the month/week/day FullCalendar grids.

## How to run

1. Start the app and open it in a supported browser (Firefox/Chrome).
2. Put the mouse away. Use only: **Tab / Shift+Tab** (move), **Enter / Space**
   (activate), **Arrow keys** (within grids/tabs/pickers), **Escape** (close).
3. Watch that a **visible focus ring** is always present on the focused control.
4. Run once in **light** and once in **dark** theme (the ring must be visible in
   both).

## Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | A **"Skip to calendar"** link is the first thing Tab reaches; activating it jumps focus to the calendar area. | |
| 2 | **Login**: Tab through email → password → Sign in; submit with Enter. A wrong password announces the error (the error has `role="alert"`). | |
| 3 | **First-login change password**: all three fields reachable and submittable by keyboard. | |
| 4 | **Top bar**: Settings and Log out buttons are reachable and show a focus ring. | |
| 5 | **FullCalendar grid**: an event can be focused with Tab and opened with **Enter** (opens the edit modal). | |
| 6 | **Event modal — focus on open**: opening a modal moves focus into it (first control / close button). | |
| 7 | **Event modal — focus trap**: Tab/Shift+Tab cycle within the modal and never reach the page behind it. | |
| 8 | **Event modal — Escape**: closes the modal and returns focus to whatever opened it. | |
| 9 | **Type / Name / Calendar / Priority / Notes**: every field reachable and editable by keyboard. | |
| 10 | **Date field**: type a date into the y/m/d inputs; ▲/▼ stepping via Arrow Up/Down works. | |
| 11 | **Date picker popup (📅)**: the 📅 button is reachable by Tab and opens with Enter; focus moves into the popup. | |
| 12 | **Date picker — arrows**: Left/Right/Up/Down move between days; ‹ › change month; Enter selects a day. | |
| 13 | **Date picker — Escape**: closes the popup and returns focus to the 📅 trigger **without** closing the event modal. | |
| 14 | **Time field**: hh/mm editable by keyboard incl. Arrow Up/Down stepping. | |
| 15 | **AM/PM toggle (12h mode)**: reachable by Tab and toggles with Enter/Space. | |
| 16 | **Reminders**: add-reminder button and each reminder's fields (incl. AM/PM) reachable by keyboard. | |
| 17 | **Recurrence editor**: interval, frequency, end-by-date/count all keyboard-operable. | |
| 18 | **Journal tabs**: Edit/Display reachable; **Left/Right arrows** switch tabs and move focus; selected tab announces as selected. | |
| 19 | **Save**: saving via the footer button works and the modal closes, focus restored. | |
| 19b | **Grid task checkbox in Tab order**: in month/week/day, Tab/Shift+Tab cycle through events **and** their task checkboxes; arrow keys still land on the whole event, never the checkbox. The checkbox toggles with Enter/Space. | |
| 20 | **Agenda view**: each row is reachable with Tab and opens with **Enter/Space**. | |
| 21 | **Agenda task row**: the completion checkbox is separately focusable (Tab) and toggles with Enter/Space (without opening the modal); arrows focus the whole row, not the checkbox. | |
| 21b | **Agenda arrows**: Up/Down move one row at a time; reaching the last loaded row and pressing Down loads the next page. | |
| 21c | **Agenda Home/End**: Home focuses the first row; End focuses the last loaded row (loading a page first). | |
| 21d | **Agenda PageUp/PageDown**: focus the top-/bottom-most visible row, then page the viewport; PageDown at the end triggers an infinite-scroll load. | |
| 22 | **Agenda — screen reader (spot check)**: a row announces a useful single label (time, title, location, kind). | |
| 23 | **Agenda — infinite scroll**: keyboard focus is not lost or stolen as new rows load; the status ("no more / no upcoming") is announced. | |
| 24 | **Settings panel**: opens, traps focus, every preference control reachable, Escape closes and restores focus. | |
| 25 | **Confirm / scope dialogs**: Yes/No (and recurring-scope choices) reachable and activatable; Escape cancels. | |
| 26 | **Share / token / share-result modals**: reachable, trap focus, Escape closes, focus restored. | |
| 27 | **Reduced motion**: with the OS "reduce motion" setting on, modal/sheet slide and spinners don't animate; UI still fully usable. | |
| 28 | **Focus ring visible** on every interactive control, in both light and dark themes (controls clicked by mouse do **not** show a ring — `:focus-visible`). | |

## Calendar grid keyboard shortcuts

Active in the month/week/day views (not the agenda, and never while a modal,
the date picker, or a text field has focus).

| # | Key | Expected |
|---|-----|----------|
| 29 | **PageUp** | Show the previous month / week / day (per current view). | |
| 30 | **PageDown** | Show the next month / week / day. | |
| 31 | **Home** | Jump to today (and, in month view, focus today's cell). | |
| 32 | **Insert** | Create a new event on the focused day. With nothing focused: month → today, day view → the shown day, week view → first day of the week. | |
| 33 | **Delete** | Delete the focused event, after an "are you sure?" confirm (recurring → scope chooser). | |
| 34 | **Arrows (month)** | Move day-by-day (Left/Right) and week-by-week (Up/Down); focus lands on the day's first event, or the empty cell. Navigates across month boundaries. | |
| 34b | **Arrows (week/day)** | Left/Right move between day columns (first event or whole-day column); Up/Down step through a day's events top-to-bottom — the all-day lane events first, then the timed events. | |
| 34c | **Arrows re-enter the grid** | After deleting/creating an event or paging with PageUp/Down, pressing an arrow moves focus back into the grid **without** needing Tab first. | |
| 35 | **Enter on an empty day/column** | Create a new event for that day (same as clicking it). | |
| 36 | **Enter on an event** | Open the event in the edit modal (FullCalendar default; not hijacked). | |
| 37 | **Date field arrows (modal)** | Up/Down on a focused day / month / year field steps it by 1. | |

## Notes

- Event keyboard activation in the grid relies on FullCalendar 6's built-in
  interactive-event behaviour (events become focusable/Enter-activatable because
  an `eventClick` handler is set). If a FullCalendar upgrade regresses this,
  re-check items 5.
- The context menu (right-click / long-press) is intentionally **not** keyboard
  reachable: every action it offers (edit, complete, delete) is available from
  the edit modal, which Enter opens. It stays a mouse/touch convenience.
