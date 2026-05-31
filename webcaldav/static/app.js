(function () {
  'use strict';

  function show(id) {
    document.getElementById(id).style.display = '';
  }
  function hide(id) {
    document.getElementById(id).style.display = 'none';
  }
  function showError(id, msg) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.style.display = '';
  }
  function hideError(id) {
    document.getElementById(id).style.display = 'none';
  }

  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  }

  async function apiPatch(path, body) {
    const r = await fetch(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  }

  async function apiDelete(path) {
    const r = await fetch(path, { method: 'DELETE' });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${r.status}`);
    }
  }

  async function apiGet(path) {
    const r = await fetch(path);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  }

  async function apiPut(path, body) {
    const r = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  }

  function initLogin() {
    show('page-login');
    const form = document.getElementById('login-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError('login-error');
      const btn = form.querySelector('button');
      btn.disabled = true;
      try {
        await apiPost('/auth/login', {
          email: document.getElementById('login-email').value,
          password: document.getElementById('login-password').value,
        });
        window.location.href = '/';
      } catch (err) {
        showError('login-error', err.message);
        btn.disabled = false;
      }
    });
  }

  function initChangePassword() {
    show('page-change-pw');
    const form = document.getElementById('change-pw-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError('cpw-error');
      const newPw = document.getElementById('cpw-new').value;
      const confirm = document.getElementById('cpw-confirm').value;
      if (newPw !== confirm) {
        showError('cpw-error', 'Passwords do not match.');
        return;
      }
      const btn = form.querySelector('button');
      btn.disabled = true;
      try {
        await apiPost('/auth/change-password', {
          old_password: document.getElementById('cpw-old').value,
          new_password: newPw,
        });
        window.location.href = '/';
      } catch (err) {
        showError('cpw-error', err.message);
        btn.disabled = false;
      }
    });
  }

  // ── Settings panel ─────────────────────────────────────────────────────────

  let _fcCalendar = null;

  function timeFormatKey() {
    return (window.__SETTINGS__ || {}).time_format || '24h';
  }

  function fcTimeFormats(key) {
    if (key === '12h') {
      return {
        eventTimeFormat: { hour: 'numeric', minute: '2-digit', meridiem: 'short' },
        slotLabelFormat: { hour: 'numeric', minute: '2-digit', omitZeroMinute: true, meridiem: 'short' },
      };
    }
    return {
      eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
      slotLabelFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
    };
  }

  function populateTimezones(selected) {
    const sel = document.getElementById('pref-tz');
    if (sel.options.length === 0) {
      let zones = [];
      try { zones = Intl.supportedValuesOf('timeZone'); } catch (_) {}
      if (!zones.length) zones = ['UTC'];
      if (selected && zones.indexOf(selected) === -1) zones.unshift(selected);
      const frag = document.createDocumentFragment();
      zones.forEach((z) => {
        const o = document.createElement('option');
        o.value = z;
        o.textContent = z;
        frag.appendChild(o);
      });
      sel.appendChild(frag);
    }
    sel.value = selected || 'UTC';
  }

  function applyCalendarPrefs(tz, fdow, timefmt) {
    if (!_fcCalendar) return;
    const fmts = fcTimeFormats(timefmt);
    _fcCalendar.batchRendering(function () {
      _fcCalendar.setOption('timeZone', tz || 'local');
      _fcCalendar.setOption('firstDay', fdow);
      _fcCalendar.setOption('eventTimeFormat', fmts.eventTimeFormat);
      _fcCalendar.setOption('slotLabelFormat', fmts.slotLabelFormat);
      _fcCalendar.refetchEvents();
    });
  }

  function openSettings() {
    show('settings-overlay');
    show('settings-panel');
    loadSettings();
  }

  function closeSettings() {
    hide('settings-overlay');
    hide('settings-panel');
    if (_fcCalendar) _fcCalendar.refetchEvents();
  }

  async function loadSettings() {
    await Promise.all([loadAccounts(), loadCalendars(), loadPrefs()]);
  }

  async function loadAccounts() {
    const list = document.getElementById('accounts-list');
    list.innerHTML = '<p class="loading">Loading…</p>';
    try {
      const accounts = await apiGet('/caldav-accounts');
      if (accounts.length === 0) {
        list.innerHTML = '<p class="empty-note">No accounts yet.</p>';
        return;
      }
      list.innerHTML = '';
      accounts.forEach((a) => {
        const row = document.createElement('div');
        row.className = 'account-row';
        row.innerHTML =
          `<span class="account-url" title="${escHtml(a.url)}">${escHtml(a.username)} — ${escHtml(a.url)}</span>` +
          `<button class="btn-danger-sm" data-id="${a.id}">Remove</button>`;
        row.querySelector('button').addEventListener('click', async () => {
          if (!confirm(`Remove account ${a.url}?`)) return;
          try {
            await apiDelete(`/caldav-accounts/${a.id}`);
            await loadSettings();
          } catch (err) {
            alert(err.message);
          }
        });
        list.appendChild(row);
      });
    } catch (err) {
      list.innerHTML = `<p class="error-note">${escHtml(err.message)}</p>`;
    }
  }

  async function loadCalendars() {
    const list = document.getElementById('calendars-list');
    list.innerHTML = '<p class="loading">Loading…</p>';
    try {
      const cals = await apiGet('/calendars');
      if (cals.length === 0) {
        list.innerHTML = '<p class="empty-note">No calendars found.</p>';
        return;
      }
      list.innerHTML = '';
      cals.forEach((c) => {
        const row = document.createElement('div');
        row.className = 'calendar-row';
        row.innerHTML =
          `<input type="color" class="cal-color" value="${escHtml(c.color)}" data-id="${c.id}">` +
          `<label class="cal-label">` +
            `<input type="checkbox" class="cal-enabled" data-id="${c.id}"${c.enabled ? ' checked' : ''}>` +
            ` ${escHtml(c.display_name)}` +
          `</label>`;
        const colorInput = row.querySelector('.cal-color');
        const enabledInput = row.querySelector('.cal-enabled');
        colorInput.addEventListener('change', async () => {
          try {
            await apiPatch(`/calendars/${c.id}`, { color: colorInput.value });
          } catch (err) {
            alert(err.message);
          }
        });
        enabledInput.addEventListener('change', async () => {
          try {
            await apiPatch(`/calendars/${c.id}`, { enabled: enabledInput.checked });
          } catch (err) {
            alert(err.message);
          }
        });
        list.appendChild(row);
      });
    } catch (err) {
      list.innerHTML = `<p class="error-note">${escHtml(err.message)}</p>`;
    }
  }

  async function loadPrefs() {
    let tz = 'UTC';
    let timefmt = timeFormatKey();
    try {
      const s = await apiGet('/settings');
      tz = s.timezone || 'UTC';
      timefmt = s.time_format || '24h';
      document.getElementById('pref-fdow').value = String(s.first_day_of_week ?? 1);
    } catch (_) {}
    populateTimezones(tz);
    document.getElementById('pref-timefmt').value = timefmt;
  }

  function initSettingsPanel() {
    document.getElementById('btn-settings').addEventListener('click', openSettings);
    document.getElementById('btn-settings-close').addEventListener('click', closeSettings);
    document.getElementById('settings-overlay').addEventListener('click', closeSettings);

    // Add account form
    const addForm = document.getElementById('add-account-form');
    addForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError('add-account-error');
      const btn = addForm.querySelector('button');
      btn.disabled = true;
      btn.textContent = 'Connecting…';
      try {
        await apiPost('/caldav-accounts', {
          url: document.getElementById('acc-url').value,
          username: document.getElementById('acc-user').value,
          password: document.getElementById('acc-pass').value,
        });
        addForm.reset();
        document.getElementById('add-account-details').open = false;
        await loadSettings();
      } catch (err) {
        showError('add-account-error', err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Connect';
      }
    });

    // Prefs form
    const prefsForm = document.getElementById('prefs-form');
    prefsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const msg = document.getElementById('prefs-msg');
      msg.className = '';
      try {
        const tz = document.getElementById('pref-tz').value || 'UTC';
        const fdow = parseInt(document.getElementById('pref-fdow').value, 10);
        const timefmt = document.getElementById('pref-timefmt').value;
        await apiPut('/settings', {
          timezone: tz,
          first_day_of_week: fdow,
          time_format: timefmt,
        });
        window.__SETTINGS__ = window.__SETTINGS__ || {};
        window.__SETTINGS__.timezone = tz;
        window.__SETTINGS__.first_day_of_week = fdow;
        window.__SETTINGS__.time_format = timefmt;
        applyCalendarPrefs(tz, fdow, timefmt);
        msg.textContent = 'Saved.';
        msg.className = 'info-msg';
        msg.style.display = '';
        setTimeout(() => { msg.style.display = 'none'; }, 2000);
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'error-msg';
        msg.style.display = '';
      }
    });
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Event detail modal ──────────────────────────────────────────────────────

  let _currentEvent = null;
  // Previous From/To as luxon DateTimes, so a From change can preserve duration.
  let _prevStart = null;
  let _prevEnd = null;

  function settingsTz() {
    const tz = (window.__SETTINGS__ || {}).timezone;
    return tz && tz !== 'local' ? tz : undefined;
  }

  // The IANA zone events are interpreted in: the user setting, else the
  // browser's resolved zone. Always a concrete name so the server can attach it.
  function effectiveTz() {
    return settingsTz() || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  }

  // Shift a date-only string (YYYY-MM-DD…) by whole days.
  function shiftDateStr(iso, delta) {
    const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    const dt = new Date(Date.UTC(y, (m || 1) - 1, d || 1));
    dt.setUTCDate(dt.getUTCDate() + delta);
    const p = (n) => String(n).padStart(2, '0');
    return `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())}`;
  }

  function applyAllDayToggle() {
    const allDay = document.getElementById('ev-allday').checked;
    document.querySelectorAll('.ev-time').forEach((el) => {
      el.style.display = allDay ? 'none' : '';
    });
  }

  function applyRepeatsToggle() {
    const repeats = document.getElementById('ev-repeats').checked;
    document.getElementById('ev-repeat-details').style.display = repeats ? '' : 'none';
  }

  // Split an ISO instant into { date, hour, minute } as wall-clock time in the
  // given IANA zone, for the date + hh/mm inputs. Uses luxon.
  function isoToInputs(iso, tz) {
    const dt = luxon.DateTime.fromISO(iso, { setZone: true }).setZone(tz || 'local');
    if (!dt.isValid) return { date: '', hour: 0, minute: 0 };
    return { date: dt.toFormat('yyyy-MM-dd'), hour: dt.hour, minute: dt.minute };
  }

  function clampInt(v, lo, hi) {
    const n = parseInt(v, 10);
    if (isNaN(n)) return 0;
    return Math.max(lo, Math.min(hi, n));
  }

  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  // Turn a text input into a zero-padded numeric stepper with ▲▼ buttons.
  // Arrow keys and buttons step by `step`, clamped to [0, max]; blur re-pads.
  function attachStepper(id, step, max, onChange) {
    const input = document.getElementById(id);
    const bump = (delta) => {
      if (input.disabled) return;
      input.value = pad2(clampInt(clampInt(input.value, 0, max) + delta, 0, max));
      onChange();
    };
    const spin = document.createElement('span');
    spin.className = 'ev-spin';
    const up = document.createElement('button');
    up.type = 'button';
    up.className = 'ev-spin-up';
    up.tabIndex = -1;
    up.textContent = '▲';
    const down = document.createElement('button');
    down.type = 'button';
    down.className = 'ev-spin-down';
    down.tabIndex = -1;
    down.textContent = '▼';
    up.addEventListener('click', () => bump(step));
    down.addEventListener('click', () => bump(-step));
    spin.append(up, down);
    input.after(spin);

    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowUp') { e.preventDefault(); bump(step); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); bump(-step); }
    });
    input.addEventListener('blur', () => {
      input.value = pad2(clampInt(input.value, 0, max));
    });
  }

  // Read a From/To row (date + hh/mm) into a luxon DateTime in the given zone.
  function readBoundary(prefix, allDay, tz) {
    const d = document.getElementById(`ev-${prefix}-date`).value;
    if (!d) return null;
    if (allDay) return luxon.DateTime.fromISO(d, { zone: tz });
    const h = clampInt(document.getElementById(`ev-${prefix}-hh`).value, 0, 23);
    const m = clampInt(document.getElementById(`ev-${prefix}-mm`).value, 0, 59);
    return luxon.DateTime.fromObject(
      { year: +d.slice(0, 4), month: +d.slice(5, 7), day: +d.slice(8, 10), hour: h, minute: m },
      { zone: tz },
    );
  }

  function writeBoundary(prefix, dt, allDay) {
    document.getElementById(`ev-${prefix}-date`).value = dt.toFormat('yyyy-MM-dd');
    if (!allDay) {
      document.getElementById(`ev-${prefix}-hh`).value = pad2(dt.hour);
      document.getElementById(`ev-${prefix}-mm`).value = pad2(dt.minute);
    }
  }

  function refreshPrevBoundaries() {
    const allDay = document.getElementById('ev-allday').checked;
    const tz = effectiveTz();
    _prevStart = readBoundary('start', allDay, tz);
    _prevEnd = readBoundary('end', allDay, tz);
  }

  // From changed: keep the same duration by shifting To along with it.
  function onFromChange() {
    if (!_currentEvent || !_currentEvent.editable) return;
    const allDay = document.getElementById('ev-allday').checked;
    const tz = effectiveTz();
    const newStart = readBoundary('start', allDay, tz);
    if (!newStart || !newStart.isValid) return;
    if (_prevStart && _prevStart.isValid && _prevEnd && _prevEnd.isValid) {
      let newEnd;
      if (allDay) {
        const days = Math.round(_prevEnd.diff(_prevStart, 'days').days);
        newEnd = newStart.plus({ days });
      } else {
        newEnd = newStart.plus(_prevEnd.diff(_prevStart));
      }
      writeBoundary('end', newEnd, allDay);
      _prevEnd = newEnd;
    }
    _prevStart = newStart;
  }

  // To changed: leave From alone, but never let To fall before From.
  function onToChange() {
    if (!_currentEvent || !_currentEvent.editable) return;
    const allDay = document.getElementById('ev-allday').checked;
    const tz = effectiveTz();
    const start = readBoundary('start', allDay, tz);
    let newEnd = readBoundary('end', allDay, tz);
    if (!newEnd || !newEnd.isValid) return;
    if (start && start.isValid && newEnd < start) {
      newEnd = start;
      writeBoundary('end', newEnd, allDay);
    }
    _prevStart = start;
    _prevEnd = newEnd;
  }

  function setEditable(on) {
    ['ev-name', 'ev-allday', 'ev-start-date', 'ev-start-hh', 'ev-start-mm',
     'ev-end-date', 'ev-end-hh', 'ev-end-mm', 'ev-location', 'ev-notes'].forEach((id) => {
      document.getElementById(id).disabled = !on;
    });
    document.getElementById('btn-event-save').style.display = on ? '' : 'none';
  }

  function openEventModal(event) {
    const props = event.extendedProps || {};
    hideError('ev-error');

    document.getElementById('ev-title-text').textContent = event.title || 'Event';
    document.getElementById('ev-name').value = event.title || '';
    document.getElementById('ev-allday').checked = !!event.allDay;

    const tz = effectiveTz();
    const rawStart = props.rawStart || (event.start ? event.start.toISOString() : null);
    let rawEnd = props.rawEnd || (event.end ? event.end.toISOString() : rawStart);
    // iCal all-day DTEND is exclusive — show the inclusive last day.
    if (event.allDay && props.rawEnd) rawEnd = shiftDateStr(props.rawEnd, -1);

    if (event.allDay) {
      document.getElementById('ev-start-date').value = String(rawStart || '').slice(0, 10);
      document.getElementById('ev-end-date').value = String(rawEnd || rawStart || '').slice(0, 10);
    } else {
      const from = isoToInputs(rawStart, tz);
      const to = isoToInputs(rawEnd, tz);
      document.getElementById('ev-start-date').value = from.date;
      document.getElementById('ev-start-hh').value = pad2(from.hour);
      document.getElementById('ev-start-mm').value = pad2(from.minute);
      document.getElementById('ev-end-date').value = to.date;
      document.getElementById('ev-end-hh').value = pad2(to.hour);
      document.getElementById('ev-end-mm').value = pad2(to.minute);
    }

    const recurrence = props.recurrence || '';
    document.getElementById('ev-repeats').checked = !!recurrence;
    document.getElementById('ev-rrule').value = recurrence;

    document.getElementById('ev-location').value = props.location || '';
    document.getElementById('ev-notes').value = props.description || '';

    const remEl = document.getElementById('ev-reminders');
    const reminders = props.reminders || [];
    if (reminders.length) {
      remEl.innerHTML = reminders
        .map((r) => `<div class="ev-reminder">${escHtml(r)}</div>`)
        .join('');
    } else {
      remEl.innerHTML = '<div class="ev-reminder empty-note">None</div>';
    }

    // Editing scope (v1): no recurring events, and demo events have no calendar.
    const noteEl = document.getElementById('ev-edit-note');
    let editable = true;
    let note = '';
    if (props.calendarId == null) {
      editable = false;
      note = 'Demo event — connect a CalDAV account to add real events.';
    } else if (recurrence) {
      editable = false;
      note = 'Recurring events can’t be edited yet.';
    }
    noteEl.textContent = note;
    noteEl.style.display = note ? '' : 'none';
    setEditable(editable);

    _currentEvent = { id: event.id, calendarId: props.calendarId, editable };

    refreshPrevBoundaries();
    applyAllDayToggle();
    applyRepeatsToggle();

    show('event-overlay');
    show('event-modal');
  }

  function closeEventModal() {
    hide('event-overlay');
    hide('event-modal');
    _currentEvent = null;
  }

  async function saveEvent() {
    if (!_currentEvent || !_currentEvent.editable) return;
    hideError('ev-error');
    const allDay = document.getElementById('ev-allday').checked;
    const startDate = document.getElementById('ev-start-date').value;
    const endDate = document.getElementById('ev-end-date').value;
    const name = document.getElementById('ev-name').value.trim();

    if (!name) { showError('ev-error', 'Name is required.'); return; }
    if (!startDate) { showError('ev-error', 'Start date is required.'); return; }

    const pad = (n) => String(n).padStart(2, '0');
    const timeStr = (prefix) => {
      const h = clampInt(document.getElementById(`ev-${prefix}-hh`).value, 0, 23);
      const m = clampInt(document.getElementById(`ev-${prefix}-mm`).value, 0, 59);
      return `${pad(h)}:${pad(m)}`;
    };

    const body = {
      calendar_id: _currentEvent.calendarId,
      title: name,
      all_day: allDay,
      location: document.getElementById('ev-location').value,
      description: document.getElementById('ev-notes').value,
      timezone: effectiveTz(),
    };
    if (allDay) {
      body.start = startDate;
      body.end = endDate || startDate;
    } else {
      if (!endDate) {
        showError('ev-error', 'From and To date are required.');
        return;
      }
      body.start = `${startDate}T${timeStr('start')}:00`;
      body.end = `${endDate}T${timeStr('end')}:00`;
    }

    const btn = document.getElementById('btn-event-save');
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      await apiPut(`/events/${encodeURIComponent(_currentEvent.id)}`, body);
      closeEventModal();
      if (_fcCalendar) _fcCalendar.refetchEvents();
    } catch (err) {
      showError('ev-error', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Save';
    }
  }

  function initEventModal() {
    document.getElementById('btn-event-close').addEventListener('click', closeEventModal);
    document.getElementById('btn-event-cancel').addEventListener('click', closeEventModal);
    document.getElementById('btn-event-save').addEventListener('click', saveEvent);
    document.getElementById('event-overlay').addEventListener('click', closeEventModal);
    document.getElementById('ev-allday').addEventListener('change', () => {
      applyAllDayToggle();
      refreshPrevBoundaries();
    });
    ['ev-start-date', 'ev-start-hh', 'ev-start-mm'].forEach((id) => {
      document.getElementById(id).addEventListener('change', onFromChange);
    });
    ['ev-end-date', 'ev-end-hh', 'ev-end-mm'].forEach((id) => {
      document.getElementById(id).addEventListener('change', onToChange);
    });
    attachStepper('ev-start-hh', 1, 23, onFromChange);
    attachStepper('ev-start-mm', 5, 59, onFromChange);
    attachStepper('ev-end-hh', 1, 23, onToChange);
    attachStepper('ev-end-mm', 5, 59, onToChange);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeEventModal();
    });
  }

  // ── Drag / resize editing ───────────────────────────────────────────────────

  // Build a PUT body from an event's current (post-drag/resize) span. Title,
  // location and notes are carried through unchanged so only the times move.
  function eventToBody(event) {
    const props = event.extendedProps || {};
    const body = {
      calendar_id: props.calendarId,
      title: event.title || '',
      all_day: event.allDay,
      location: props.location || '',
      description: props.description || '',
      timezone: effectiveTz(),
    };
    if (event.allDay) {
      // startStr/endStr are 'YYYY-MM-DD'; iCal DTEND is exclusive, so the
      // client-visible inclusive end is endStr − 1 day.
      body.start = event.startStr.slice(0, 10);
      body.end = event.endStr ? shiftDateStr(event.endStr, -1) : body.start;
    } else {
      // startStr/endStr are ISO with the calendar's offset (tz-aware), which
      // the server parses directly.
      body.start = event.startStr;
      body.end = event.endStr || event.startStr;
    }
    return body;
  }

  // Persist a drag (eventDrop) or resize (eventResize); revert on failure.
  async function onEventChange(info) {
    const props = info.event.extendedProps || {};
    if (props.calendarId == null || props.recurrence) {
      info.revert();
      return;
    }
    try {
      await apiPut(`/events/${encodeURIComponent(info.event.id)}`, eventToBody(info.event));
    } catch (err) {
      alert(err.message);
      info.revert();
    }
  }

  // ── Calendar page ───────────────────────────────────────────────────────────

  function initCalendar() {
    show('page-calendar');

    const emailEl = document.getElementById('header-email');
    if (window.__USER_EMAIL__) emailEl.textContent = window.__USER_EMAIL__;

    document.getElementById('btn-logout').addEventListener('click', async () => {
      await fetch('/auth/logout', { method: 'POST' });
      window.location.href = '/';
    });

    initSettingsPanel();
    initEventModal();

    const calendarEl = document.getElementById('calendar');
    const s = window.__SETTINGS__ || {};
    const tf = fcTimeFormats(timeFormatKey());
    _fcCalendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,timeGridWeek,timeGridDay',
      },
      firstDay: s.first_day_of_week != null ? s.first_day_of_week : 1,
      timeZone: s.timezone || 'local',
      eventTimeFormat: tf.eventTimeFormat,
      slotLabelFormat: tf.slotLabelFormat,
      height: '100%',
      // Enable drag-to-move and edge-resize; both start and end edges.
      editable: true,
      eventResizableFromStart: true,
      events: async function (fetchInfo, successCallback, failureCallback) {
        try {
          const params = new URLSearchParams({ from: fetchInfo.startStr, to: fetchInfo.endStr });
          const r = await fetch('/events?' + params.toString());
          if (!r.ok) throw new Error('Failed to fetch events');
          const data = await r.json();
          // Only real (calendar-backed), non-recurring events are editable.
          data.forEach((e) => {
            const p = e.extendedProps || {};
            e.editable = p.calendarId != null && !p.recurrence;
          });
          successCallback(data);
        } catch (err) {
          failureCallback(err);
        }
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        openEventModal(info.event);
      },
      eventDrop: onEventChange,
      eventResize: onEventChange,
    });
    _fcCalendar.render();
  }

  document.addEventListener('DOMContentLoaded', function () {
    const state = window.__STATE__;
    if (state === 'anonymous') initLogin();
    else if (state === 'restricted') initChangePassword();
    else if (state === 'authenticated') initCalendar();
  });
})();
