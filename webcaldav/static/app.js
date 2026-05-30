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

  function settingsTz() {
    const tz = (window.__SETTINGS__ || {}).timezone;
    return tz && tz !== 'local' ? tz : undefined;
  }

  // Shift a date-only string (YYYY-MM-DD…) by whole days.
  function shiftDateStr(iso, delta) {
    const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    const dt = new Date(Date.UTC(y, (m || 1) - 1, d || 1));
    dt.setUTCDate(dt.getUTCDate() + delta);
    const p = (n) => String(n).padStart(2, '0');
    return `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())}`;
  }

  // Format an event boundary respecting timezone + time-format settings.
  // Returns { date, time }; time is '' for all-day events.
  function formatBoundary(iso, allDay) {
    if (!iso) return { date: '', time: '' };
    if (allDay) {
      const datePart = String(iso).slice(0, 10);
      const [y, m, d] = datePart.split('-').map(Number);
      const local = new Date(y, (m || 1) - 1, d || 1);
      const dateFmt = new Intl.DateTimeFormat(undefined, {
        year: 'numeric', month: 'short', day: '2-digit', weekday: 'short',
      });
      return { date: dateFmt.format(local), time: '' };
    }
    const dt = new Date(iso);
    if (isNaN(dt.getTime())) return { date: String(iso), time: '' };
    const tz = settingsTz();
    const dateFmt = new Intl.DateTimeFormat(undefined, {
      year: 'numeric', month: 'short', day: '2-digit', weekday: 'short', timeZone: tz,
    });
    const timeFmt = new Intl.DateTimeFormat(undefined, {
      hour: '2-digit', minute: '2-digit', hour12: timeFormatKey() === '12h', timeZone: tz,
    });
    return { date: dateFmt.format(dt), time: timeFmt.format(dt) };
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

  function openEventModal(event) {
    const props = event.extendedProps || {};

    document.getElementById('ev-title-text').textContent = event.title || 'Event';
    document.getElementById('ev-name').value = event.title || '';

    document.getElementById('ev-allday').checked = !!event.allDay;

    const rawStart = props.rawStart || (event.start ? event.start.toISOString() : null);
    let rawEnd = props.rawEnd || (event.end ? event.end.toISOString() : rawStart);
    // iCal all-day DTEND is exclusive — show the inclusive last day.
    if (event.allDay && props.rawEnd) rawEnd = shiftDateStr(props.rawEnd, -1);
    const from = formatBoundary(rawStart, event.allDay);
    const to = formatBoundary(rawEnd, event.allDay);
    document.getElementById('ev-start-date').value = from.date;
    document.getElementById('ev-start-time').value = from.time;
    document.getElementById('ev-end-date').value = to.date;
    document.getElementById('ev-end-time').value = to.time;

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

    applyAllDayToggle();
    applyRepeatsToggle();

    show('event-overlay');
    show('event-modal');
  }

  function closeEventModal() {
    hide('event-overlay');
    hide('event-modal');
  }

  function initEventModal() {
    document.getElementById('btn-event-close').addEventListener('click', closeEventModal);
    document.getElementById('event-overlay').addEventListener('click', closeEventModal);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeEventModal();
    });
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
      events: async function (fetchInfo, successCallback, failureCallback) {
        try {
          const params = new URLSearchParams({ from: fetchInfo.startStr, to: fetchInfo.endStr });
          const r = await fetch('/events?' + params.toString());
          if (!r.ok) throw new Error('Failed to fetch events');
          successCallback(await r.json());
        } catch (err) {
          failureCallback(err);
        }
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        openEventModal(info.event);
      },
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
