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
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  }

  async function apiPatch(path, body) {
    const r = await fetch(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  }

  async function apiDelete(path) {
    const r = await fetch(path, { method: 'DELETE', headers: { 'X-Requested-With': 'fetch' } });
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
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
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

  function dateFormatKey() {
    return (window.__SETTINGS__ || {}).date_format || 'YYYY-MM-DD';
  }

  // Map the stored date_format setting to a luxon format string (the luxon3
  // FullCalendar plugin lets us pass string formats to *Format options).
  function luxonDateFmt(key) {
    if (key === 'MM/DD/YYYY') return 'MM/dd/yyyy';
    if (key === 'DD/MM/YYYY') return 'dd/MM/yyyy';
    return 'yyyy-MM-dd';
  }

  // Per-view date formats so week/day headers honor the user's date_format.
  function fcViewFormats(dateKey) {
    const ds = luxonDateFmt(dateKey);
    return {
      timeGridWeek: { dayHeaderFormat: 'EEE ' + ds },
      timeGridDay: { dayHeaderFormat: 'EEEE ' + ds, titleFormat: ds },
    };
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

  function applyCalendarPrefs(tz, fdow, timefmt, datefmt) {
    if (!_fcCalendar) return;
    const fmts = fcTimeFormats(timefmt);
    _fcCalendar.batchRendering(function () {
      _fcCalendar.setOption('timeZone', tz || 'local');
      _fcCalendar.setOption('firstDay', fdow);
      _fcCalendar.setOption('eventTimeFormat', fmts.eventTimeFormat);
      _fcCalendar.setOption('slotLabelFormat', fmts.slotLabelFormat);
      _fcCalendar.setOption('views', fcViewFormats(datefmt));
      _fcCalendar.refetchEvents();
    });
    // The agenda renders dates/times itself, so re-run it on a prefs change.
    if (_agendaActive) { agendaReset(); agendaLoadMore(); }
  }

  function openSettings() {
    show('settings-overlay');
    show('settings-panel');
    loadSettings();
  }

  function closeSettings() {
    hide('settings-overlay');
    hide('settings-panel');
    // Calendars may have changed; drop the create-modal picker cache.
    _calendarsCache = null;
    refreshViews();
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
          `</label>` +
          `<label class="cal-default-label" title="Default calendar for new events">` +
            `<input type="checkbox" class="cal-default" data-id="${c.id}"${c.is_default ? ' checked' : ''}>` +
            ` Default` +
          `</label>`;
        const colorInput = row.querySelector('.cal-color');
        const enabledInput = row.querySelector('.cal-enabled');
        const defaultInput = row.querySelector('.cal-default');
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
        defaultInput.addEventListener('change', async () => {
          try {
            await apiPatch(`/calendars/${c.id}`, { is_default: defaultInput.checked });
            // Server allows only one default; reload to clear the others' checks.
            if (defaultInput.checked) await loadCalendars();
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
    let datefmt = dateFormatKey();
    try {
      const s = await apiGet('/settings');
      tz = s.timezone || 'UTC';
      timefmt = s.time_format || '24h';
      datefmt = s.date_format || 'YYYY-MM-DD';
      document.getElementById('pref-fdow').value = String(s.first_day_of_week ?? 1);
      document.getElementById('pref-default-view').value = s.default_view || 'dayGridMonth';
      const enabled = s.auto_logout_enabled ?? true;
      const mins = Math.max(1, Math.round((s.auto_logout_timeout_seconds ?? 3600) / 60));
      const enEl = document.getElementById('pref-auto-logout-enabled');
      const minEl = document.getElementById('pref-auto-logout-min');
      enEl.checked = enabled;
      minEl.value = String(mins);
      minEl.disabled = !enabled;
      const notifEl = document.getElementById('pref-notifications-enabled');
      const notifOn = !!s.notifications_enabled;
      notifEl.checked = notifOn;
      if (!('Notification' in window)) {
        notifEl.checked = false;
        notifEl.disabled = true;
      }
      // Notifications and auto-logout are mutually exclusive (server-enforced);
      // when notifications are on, lock the auto-logout controls off.
      enEl.disabled = notifOn;
      if (notifOn) minEl.disabled = true;
    } catch (_) {}
    populateTimezones(tz);
    document.getElementById('pref-timefmt').value = timefmt;
    document.getElementById('pref-datefmt').value = datefmt;
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

    // Grey out the minutes field while auto-logout is disabled.
    const autoLogoutEnabledEl = document.getElementById('pref-auto-logout-enabled');
    autoLogoutEnabledEl.addEventListener('change', () => {
      document.getElementById('pref-auto-logout-min').disabled = !autoLogoutEnabledEl.checked;
    });

    // Turning notifications on must happen in this click handler so the browser
    // permission prompt is tied to a user gesture (required by Safari/iOS).
    const notifEnabledEl = document.getElementById('pref-notifications-enabled');
    notifEnabledEl.addEventListener('change', async () => {
      if (notifEnabledEl.checked) {
        if (!('Notification' in window)) {
          notifEnabledEl.checked = false;
          alert('This browser does not support notifications.');
          return;
        }
        let perm = Notification.permission;
        if (perm !== 'granted') {
          try { perm = await Notification.requestPermission(); } catch (_) { perm = 'denied'; }
        }
        if (perm !== 'granted') {
          notifEnabledEl.checked = false;
          alert('Notifications are blocked. Allow them for this site in your browser settings, then try again.');
          return;
        }
        // Enabling notifications forces auto-logout off (the tab must stay
        // logged in to keep resyncing events); mirror the server rule in the UI.
        autoLogoutEnabledEl.checked = false;
        autoLogoutEnabledEl.disabled = true;
        document.getElementById('pref-auto-logout-min').disabled = true;
      } else {
        autoLogoutEnabledEl.disabled = false;
        document.getElementById('pref-auto-logout-min').disabled = !autoLogoutEnabledEl.checked;
      }
    });

    // Always-available per-browser permission grant. Permission is per-browser
    // and not synced with the server setting, so logging in elsewhere needs a
    // gesture-driven prompt (required by Safari) without re-toggling the box.
    const grantBtn = document.getElementById('pref-notifications-grant');
    grantBtn.addEventListener('click', async () => {
      if (!('Notification' in window)) {
        alert('This browser does not support notifications.');
        return;
      }
      let perm = Notification.permission;
      if (perm !== 'granted') {
        try { perm = await Notification.requestPermission(); } catch (_) { perm = 'denied'; }
      }
      if (perm === 'granted') {
        if ((window.__SETTINGS__ || {}).notifications_enabled) startNotifications();
        alert('Notifications are enabled on this browser.');
      } else {
        alert('Notifications are blocked. Allow them for this site in your browser settings.');
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
        const datefmt = document.getElementById('pref-datefmt').value;
        const defaultView = document.getElementById('pref-default-view').value;
        const notifEnabled = document.getElementById('pref-notifications-enabled').checked;
        // Notifications force auto-logout off (server enforces the same).
        const autoEnabled = notifEnabled ? false : document.getElementById('pref-auto-logout-enabled').checked;
        const autoMin = parseInt(document.getElementById('pref-auto-logout-min').value, 10);
        if (autoEnabled && (!Number.isFinite(autoMin) || autoMin < 1)) {
          throw new Error('Logout time must be at least 1 minute');
        }
        const autoSecs = autoEnabled ? autoMin * 60 : (window.__SETTINGS__?.auto_logout_timeout_seconds ?? 3600);
        await apiPut('/settings', {
          timezone: tz,
          first_day_of_week: fdow,
          time_format: timefmt,
          date_format: datefmt,
          default_view: defaultView,
          auto_logout_enabled: autoEnabled,
          auto_logout_timeout_seconds: autoSecs,
          notifications_enabled: notifEnabled,
        });
        window.__SETTINGS__ = window.__SETTINGS__ || {};
        window.__SETTINGS__.timezone = tz;
        window.__SETTINGS__.first_day_of_week = fdow;
        window.__SETTINGS__.time_format = timefmt;
        window.__SETTINGS__.date_format = datefmt;
        window.__SETTINGS__.default_view = defaultView;
        window.__SETTINGS__.auto_logout_enabled = autoEnabled;
        window.__SETTINGS__.auto_logout_timeout_seconds = autoSecs;
        window.__SETTINGS__.notifications_enabled = notifEnabled;
        if (notifEnabled) startNotifications(); else stopNotifications();
        applyCalendarPrefs(tz, fdow, timefmt, datefmt);
        // Live session timeout changed server-side; resync the countdown.
        refreshLogoutCountdown();
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
    if (repeats) { updateRecurUI(); scheduleRecurPreview(); }
  }

  // ── Reminders editor ─────────────────────────────────────────────────────────
  //
  // Editable reminders live in _reminders as {value, unit, time?, isNew}. Timed
  // events use value+unit ("15 minutes before"); all-day events use days/weeks
  // plus a time of day ("2 weeks before at 09:00"). Alarms the server can't
  // express in that model (email, absolute-time, after-event) arrive as
  // {text, readonly} and are shown dimmed without a delete button. Committed
  // rows can only be deleted, not edited — delete and re-add to change one.
  let _reminders = [];
  let _remindersReadonly = [];
  let _remindersEditable = false;

  const REMINDER_UNIT_MIN = { minutes: 1, hours: 60, days: 1440, weeks: 10080 };

  function reminderIsAllDay() {
    return document.getElementById('ev-allday').checked;
  }

  // Minutes before the event start, for soonest-first sorting.
  function reminderMinutes(r) {
    if (r.time != null) {
      const [h, m] = String(r.time).split(':').map(Number);
      return r.value * (r.unit === 'weeks' ? 10080 : 1440) - ((h || 0) * 60 + (m || 0));
    }
    return r.value * (REMINDER_UNIT_MIN[r.unit] || 1);
  }

  // Render a canonical "HH:MM" per the 12h/24h time_format setting.
  function reminderTimeText(hhmm) {
    const [h, m] = String(hhmm).split(':').map(Number);
    if (!timeIs12h()) return hhmm;
    let h12 = h % 12;
    if (h12 === 0) h12 = 12;
    return `${h12}:${pad2(m || 0)} ${h >= 12 ? 'PM' : 'AM'}`;
  }

  function reminderText(r) {
    if (r.time != null) {
      const at = reminderTimeText(r.time);
      if (r.value === 0) return `On the day at ${at}`;
      const unit = r.value === 1 ? r.unit.slice(0, -1) : r.unit;
      return `${r.value} ${unit} before at ${at}`;
    }
    if (r.value === 0) return 'At time of event';
    const unit = r.value === 1 ? r.unit.slice(0, -1) : r.unit;
    return `${r.value} ${unit} before`;
  }

  // hh:mm (+ AM/PM) inputs for an all-day reminder row, honoring time_format —
  // a native <input type="time"> would follow the browser locale instead.
  // The canonical value kept in r.time is always 24h "HH:MM".
  function reminderTimeHtml(idx, hhmm) {
    const [h24, m] = String(hhmm || '09:00').split(':').map(Number);
    const h12mode = timeIs12h();
    let hVal = h24;
    if (h12mode) {
      hVal = h24 % 12;
      if (hVal === 0) hVal = 12;
    }
    return (
      `<span class="ev-reminder-word">at</span>` +
      `<input type="text" class="ev-hh ev-rem-hh" data-idx="${idx}" inputmode="numeric" maxlength="2" value="${pad2(hVal)}">` +
      `<span class="ev-colon">:</span>` +
      `<input type="text" class="ev-mm ev-rem-mm" data-idx="${idx}" inputmode="numeric" maxlength="2" value="${pad2(m || 0)}">` +
      (h12mode
        ? `<button type="button" class="ev-ampm ev-rem-ampm" data-idx="${idx}" tabindex="-1">${h24 >= 12 ? 'PM' : 'AM'}</button>`
        : '')
    );
  }

  // Absolute-trigger alarms arrive with an ISO instant; render it per the
  // user's date/time-format settings instead of the server's raw ISO text.
  function readonlyReminderAtText(iso) {
    const dt = luxon.DateTime.fromISO(iso, { setZone: true }).setZone(effectiveTz());
    if (!dt.isValid) return `At ${iso}`;
    const timeFmt = timeFormatKey() === '12h' ? 'h:mm a' : 'HH:mm';
    return `At ${dt.toFormat(`${luxonDateFmt(dateFormatKey())} ${timeFmt}`)}`;
  }

  // Split the server's extendedProps.reminders into editable and read-only rows.
  function resetReminders(list) {
    _reminders = [];
    _remindersReadonly = [];
    (list || []).forEach((r) => {
      if (!r || typeof r !== 'object') return;
      if (r.readonly) {
        _remindersReadonly.push(r.at ? readonlyReminderAtText(r.at) : (r.text || 'Reminder'));
      } else if (r.unit) {
        _reminders.push({ value: r.value, unit: r.unit, time: r.time });
      }
    });
  }

  function renderReminders() {
    const box = document.getElementById('ev-reminders');
    const addBtn = document.getElementById('ev-reminder-add');
    addBtn.style.display = _remindersEditable ? '' : 'none';
    const allDay = reminderIsAllDay();

    // Committed rows sort soonest-first; rows still being typed stay last so
    // they don't jump around under the cursor.
    const committed = _reminders.filter((r) => !r.isNew)
      .sort((a, b) => reminderMinutes(a) - reminderMinutes(b));
    const fresh = _reminders.filter((r) => r.isNew);
    _reminders = committed.concat(fresh);

    const rows = [];
    committed.forEach((r, i) => {
      const del = _remindersEditable
        ? `<button type="button" class="btn-icon ev-reminder-del" data-idx="${i}" aria-label="Delete reminder">×</button>`
        : '';
      rows.push(
        `<div class="ev-reminder-row"><span class="ev-reminder">${escHtml(reminderText(r))}</span>${del}</div>`
      );
    });
    fresh.forEach((r, i) => {
      const idx = committed.length + i;
      const units = allDay ? ['days', 'weeks'] : ['minutes', 'hours', 'days', 'weeks'];
      const opts = units
        .map((u) => `<option value="${u}"${u === r.unit ? ' selected' : ''}>${u}</option>`)
        .join('');
      const time = allDay ? reminderTimeHtml(idx, r.time) : '';
      rows.push(
        `<div class="ev-reminder-row">` +
          `<input type="number" class="ev-reminder-value" data-idx="${idx}" min="0" max="10000" value="${escHtml(r.value)}">` +
          `<select class="ev-reminder-unit" data-idx="${idx}">${opts}</select>` +
          `<span class="ev-reminder-word">before</span>${time}` +
          `<button type="button" class="btn-icon ev-reminder-del" data-idx="${idx}" aria-label="Delete reminder">×</button>` +
        `</div>`
      );
    });
    _remindersReadonly.forEach((text) => {
      rows.push(
        `<div class="ev-reminder-row"><span class="ev-reminder ev-reminder-locked">${escHtml(text)}</span></div>`
      );
    });
    box.innerHTML = rows.length
      ? rows.join('')
      : '<div class="ev-reminder empty-note">None</div>';

    box.querySelectorAll('.ev-reminder-del').forEach((btn) => {
      btn.addEventListener('click', () => {
        _reminders.splice(parseInt(btn.dataset.idx, 10), 1);
        renderReminders();
      });
    });
    box.querySelectorAll('.ev-reminder-value').forEach((inp) => {
      inp.addEventListener('input', () => {
        const r = _reminders[parseInt(inp.dataset.idx, 10)];
        if (r) r.value = parseInt(inp.value, 10);
      });
    });
    box.querySelectorAll('.ev-reminder-unit').forEach((sel) => {
      sel.addEventListener('change', () => {
        const r = _reminders[parseInt(sel.dataset.idx, 10)];
        if (r) r.unit = sel.value;
      });
    });
    // Read a row's hh/mm (+ AM/PM) back into canonical 24h r.time, re-padding
    // the inputs as the start/end time fields do.
    const syncRowTime = (idx) => {
      const r = _reminders[idx];
      const hEl = box.querySelector(`.ev-rem-hh[data-idx="${idx}"]`);
      const mEl = box.querySelector(`.ev-rem-mm[data-idx="${idx}"]`);
      const aEl = box.querySelector(`.ev-rem-ampm[data-idx="${idx}"]`);
      if (!r || !hEl || !mEl) return;
      const m = clampInt(mEl.value, 0, 59);
      let h24;
      if (aEl) {
        const h12 = clampInt(hEl.value, 1, 12);
        h24 = (h12 % 12) + (aEl.textContent === 'PM' ? 12 : 0);
        hEl.value = pad2(h12);
      } else {
        h24 = clampInt(hEl.value, 0, 23);
        hEl.value = pad2(h24);
      }
      mEl.value = pad2(m);
      r.time = `${pad2(h24)}:${pad2(m)}`;
    };
    box.querySelectorAll('.ev-rem-hh, .ev-rem-mm').forEach((inp) => {
      inp.addEventListener('change', () => syncRowTime(parseInt(inp.dataset.idx, 10)));
    });
    box.querySelectorAll('.ev-rem-ampm').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        btn.textContent = btn.textContent === 'AM' ? 'PM' : 'AM';
        syncRowTime(parseInt(btn.dataset.idx, 10));
      });
    });
  }

  // The reminder rows the save request should carry (invalid rows dropped).
  function collectReminders() {
    const allDay = reminderIsAllDay();
    const out = [];
    _reminders.forEach((r) => {
      const value = parseInt(r.value, 10);
      if (!Number.isFinite(value) || value < 0 || value > 10000) return;
      if (allDay) {
        if (r.unit !== 'days' && r.unit !== 'weeks') return;
        if (!r.time) return;
        out.push({ value, unit: r.unit, time: r.time });
      } else {
        out.push({ value, unit: r.unit });
      }
    });
    return out;
  }

  // Switching all-day changes the reminder model; rows that can't be expressed
  // in the new mode are dropped (re-add them in the new format).
  function remindersOnAllDayToggle() {
    if (reminderIsAllDay()) {
      _reminders = _reminders.filter((r) => r.unit === 'days' || r.unit === 'weeks');
      _reminders.forEach((r) => { if (!r.time) r.time = '09:00'; });
    } else {
      _reminders = _reminders.filter((r) => r.time == null);
    }
    renderReminders();
  }

  function addReminderRow() {
    if (!_remindersEditable) return;
    if (reminderIsAllDay()) {
      _reminders.push({ value: 1, unit: 'days', time: '09:00', isNew: true });
    } else {
      _reminders.push({ value: 15, unit: 'minutes', isNew: true });
    }
    renderReminders();
  }

  // ── Recurrence editor ────────────────────────────────────────────────────────
  const ORDINALS = ['1st', '2nd', '3rd', '4th', '5th'];

  // Build the ISO start the rule is anchored to, from the modal's From inputs.
  function currentStartISO() {
    const d = getDateFieldValue('start');
    if (!d) return null;
    if (document.getElementById('ev-allday').checked) return d;
    const { h24, m } = getTimeParts('start');
    const pad = (n) => String(n).padStart(2, '0');
    return `${d}T${pad(h24)}:${pad(m)}:00`;
  }

  // Refresh the "day N" / "Nth weekday" labels from the current start date.
  function recurDescriptions() {
    const d = getDateFieldValue('start');
    if (!d) return;
    const dt = luxon.DateTime.fromISO(d);
    if (!dt.isValid) return;
    const ord = Math.floor((dt.day - 1) / 7) + 1;
    document.getElementById('ev-recur-monthday-desc').textContent = String(dt.day);
    document.getElementById('ev-recur-weekday-desc').textContent =
      `${ORDINALS[ord - 1] || ord + 'th'} ${dt.toFormat('cccc')}`;
  }

  function updateRecurUI() {
    const freq = document.getElementById('ev-recur-freq').value;
    document.getElementById('ev-recur-monthly').style.display = freq === 'monthly' ? '' : 'none';
    recurDescriptions();
    const endCount = document.getElementById('ev-recur-end-count').checked;
    const endDate = document.getElementById('ev-recur-end-date').checked;
    document.getElementById('ev-recur-count').disabled = !endCount;
    document.querySelectorAll(
      '#ev-recur-until-date-fields input, #ev-recur-until-date-fields button',
    ).forEach((el) => { el.disabled = !endDate; });
  }

  // Collect the editor state into the API's recurrence model, or null if off.
  function getRecurrence() {
    if (!document.getElementById('ev-repeats').checked) return null;
    const rule = {
      freq: document.getElementById('ev-recur-freq').value,
      interval: Math.max(1, parseInt(document.getElementById('ev-recur-interval').value, 10) || 1),
    };
    if (rule.freq === 'monthly') {
      const mode = document.querySelector('input[name="ev-monthly-mode"]:checked');
      rule.monthly_mode = mode ? mode.value : 'monthday';
    }
    if (document.getElementById('ev-recur-end-count').checked) {
      rule.count = Math.max(1, parseInt(document.getElementById('ev-recur-count').value, 10) || 1);
    } else if (document.getElementById('ev-recur-end-date').checked) {
      const until = getDateFieldValue('recur-until');
      if (until) rule.until = `${until}T23:59:59`;
    }
    return rule;
  }

  // Populate the editor from a structured rule returned by the server.
  function setRecurrence(struct) {
    if (!struct) return;
    document.getElementById('ev-recur-freq').value = struct.freq || 'weekly';
    document.getElementById('ev-recur-interval').value = struct.interval || 1;
    if (struct.monthly_mode) {
      const r = document.querySelector(
        `input[name="ev-monthly-mode"][value="${struct.monthly_mode}"]`,
      );
      if (r) r.checked = true;
    }
    document.getElementById('ev-recur-end-count').checked = struct.count != null;
    document.getElementById('ev-recur-end-date').checked = struct.until != null;
    if (struct.count != null) document.getElementById('ev-recur-count').value = struct.count;
    if (struct.until) setDateFieldValue('recur-until', String(struct.until).slice(0, 10));
  }

  function resetRecurEditorDefaults() {
    document.getElementById('ev-recur-freq').value = 'weekly';
    document.getElementById('ev-recur-interval').value = 1;
    const md = document.querySelector('input[name="ev-monthly-mode"][value="monthday"]');
    if (md) md.checked = true;
    document.getElementById('ev-recur-end-count').checked = false;
    document.getElementById('ev-recur-end-date').checked = false;
    document.getElementById('ev-recur-count').value = 10;
    setDateFieldValue('recur-until', '');
    document.getElementById('ev-recur-preview').textContent = '';
  }

  // Called when the From date/time changes, to keep labels + preview in sync.
  function recurOnStartChange() {
    if (document.getElementById('ev-repeats').checked) { recurDescriptions(); scheduleRecurPreview(); }
  }

  let _recurPreviewTimer = null;
  function scheduleRecurPreview() {
    clearTimeout(_recurPreviewTimer);
    _recurPreviewTimer = setTimeout(previewRecur, 250);
  }

  async function previewRecur() {
    const box = document.getElementById('ev-recur-preview');
    const rule = getRecurrence();
    const start = currentStartISO();
    if (!rule || !start) { box.textContent = ''; return; }
    if (rule.count == null && rule.until == null) { box.textContent = 'Repeats forever.'; return; }
    try {
      const res = await apiPost('/events/recurrence-preview', {
        start,
        all_day: document.getElementById('ev-allday').checked,
        timezone: effectiveTz(),
        recurrence: rule,
      });
      box.textContent = res.last
        ? `${res.count} occurrence(s); last on ${String(res.last).slice(0, 10)}.`
        : 'No occurrences in range.';
    } catch (_) {
      box.textContent = '';
    }
  }

  function initRecurEditor() {
    renderDateFields('recur-until', scheduleRecurPreview);
    document.getElementById('ev-recur-freq').addEventListener('change', () => {
      updateRecurUI(); scheduleRecurPreview();
    });
    ['ev-recur-interval', 'ev-recur-count'].forEach((id) => {
      document.getElementById(id).addEventListener('input', scheduleRecurPreview);
    });
    document.querySelectorAll('input[name="ev-monthly-mode"]').forEach((r) => {
      r.addEventListener('change', scheduleRecurPreview);
    });
    const ec = document.getElementById('ev-recur-end-count');
    const ed = document.getElementById('ev-recur-end-date');
    // The two end modes are mutually exclusive.
    ec.addEventListener('change', () => {
      if (ec.checked) ed.checked = false;
      updateRecurUI(); scheduleRecurPreview();
    });
    ed.addEventListener('change', () => {
      if (ed.checked) ec.checked = false;
      updateRecurUI(); scheduleRecurPreview();
    });
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

  // ── Custom date fields (forced format) ──────────────────────────────────────
  // Native <input type="date"> renders per OS locale and can't be forced, so —
  // like the hh/mm time fields — dates use three numeric inputs (year/month/day)
  // ordered per the date_format setting, plus a 📅 button that pops the browser's
  // native mini-calendar via a hidden date input. Canonical value stays yyyy-MM-dd.

  function dateFieldParts(key) {
    if (key === 'MM/DD/YYYY') return { order: ['month', 'day', 'year'], sep: '/' };
    if (key === 'DD/MM/YYYY') return { order: ['day', 'month', 'year'], sep: '/' };
    return { order: ['year', 'month', 'day'], sep: '-' }; // YYYY-MM-DD
  }

  const DATE_PART_RANGE = { year: [1, 9999], month: [1, 12], day: [1, 31] };

  // Read the three numeric inputs into a canonical 'yyyy-MM-dd', or '' if empty/invalid.
  function getDateFieldValue(prefix) {
    const yEl = document.getElementById(`ev-${prefix}-year`);
    const mEl = document.getElementById(`ev-${prefix}-month`);
    const dEl = document.getElementById(`ev-${prefix}-day`);
    if (!yEl || !mEl || !dEl) return '';
    if (yEl.value === '' || mEl.value === '' || dEl.value === '') return '';
    const dt = luxon.DateTime.fromObject({
      year: clampInt(yEl.value, 1, 9999),
      month: clampInt(mEl.value, 1, 12),
      day: clampInt(dEl.value, 1, 31),
    });
    return dt.isValid ? dt.toFormat('yyyy-MM-dd') : '';
  }

  // Write a canonical 'yyyy-MM-dd' into the three inputs + sync the hidden picker.
  function setDateFieldValue(prefix, canon) {
    const yEl = document.getElementById(`ev-${prefix}-year`);
    const mEl = document.getElementById(`ev-${prefix}-month`);
    const dEl = document.getElementById(`ev-${prefix}-day`);
    const picker = document.getElementById(`ev-${prefix}-picker`);
    const c = String(canon || '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(c)) {
      if (yEl) yEl.value = '';
      if (mEl) mEl.value = '';
      if (dEl) dEl.value = '';
      if (picker) picker.value = '';
      return;
    }
    if (yEl) yEl.value = c.slice(0, 4);
    if (mEl) mEl.value = c.slice(5, 7);
    if (dEl) dEl.value = c.slice(8, 10);
    if (picker) picker.value = c;
  }

  // (Re)build the date inputs for one boundary in the configured order. Called on
  // each modal open so a date_format change (no reload) takes effect; replacing
  // innerHTML drops any stale listeners.
  function renderDateFields(prefix, onChange) {
    const container = document.getElementById(`ev-${prefix}-date-fields`);
    if (!container) return;
    const { order, sep } = dateFieldParts(dateFormatKey());
    const pieces = order.map((part) => {
      const max = part === 'year' ? 4 : 2;
      return `<input type="text" inputmode="numeric" maxlength="${max}"` +
        ` id="ev-${prefix}-${part}" class="ev-dnum ev-${part}">`;
    });
    container.innerHTML =
      pieces.join(`<span class="ev-dsep">${sep}</span>`) +
      `<button type="button" class="ev-cal-btn" tabindex="-1" aria-label="Pick date">📅</button>`;

    order.forEach((part) => {
      const [lo, hi] = DATE_PART_RANGE[part];
      const pad = part === 'year' ? 4 : 2;
      const input = document.getElementById(`ev-${prefix}-${part}`);
      input.addEventListener('blur', () => {
        if (input.value === '') return;
        input.value = String(clampInt(input.value, lo, hi)).padStart(pad, '0');
      });
      input.addEventListener('change', onChange);
    });

    const btn = container.querySelector('.ev-cal-btn');
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      openDatePicker(prefix, btn, onChange);
    });
  }

  // ── Custom mini date picker ──────────────────────────────────────────────────
  // Native <input type="date"> renders its month grid per OS locale and ignores
  // the user's first-day-of-week setting, so the 📅 button pops this custom
  // calendar instead. first_day_of_week: 0=Sun … 6=Sat (matches FullCalendar).
  const WEEKDAY_LABELS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
  let _calPop = null;
  let _calState = null; // { prefix, onChange, view: luxon DateTime (month) }

  function firstDayOfWeek() {
    const v = (window.__SETTINGS__ || {}).first_day_of_week;
    return v == null ? 1 : ((v % 7) + 7) % 7;
  }

  function ensureCalPop() {
    if (_calPop) return _calPop;
    const pop = document.createElement('div');
    pop.className = 'ev-cal-pop';
    pop.hidden = true;
    pop.innerHTML =
      `<div class="ev-cal-pop-head">` +
      `<button type="button" class="ev-cal-nav" data-d="-1" aria-label="Previous">‹</button>` +
      `<button type="button" class="ev-cal-title"></button>` +
      `<button type="button" class="ev-cal-nav" data-d="1" aria-label="Next">›</button>` +
      `</div><div class="ev-cal-grid"></div>`;
    document.body.appendChild(pop);
    pop.querySelectorAll('.ev-cal-nav').forEach((b) => {
      b.addEventListener('click', () => {
        if (!_calState) return;
        // Day grid steps by month; month grid steps by year.
        const unit = _calState.mode === 'months' ? 'years' : 'months';
        _calState.view = _calState.view.plus({ [unit]: +b.dataset.d });
        renderCalGrid();
      });
    });
    // Clicking the title drills out from days to the month picker.
    pop.querySelector('.ev-cal-title').addEventListener('click', () => {
      if (!_calState || _calState.mode === 'months') return;
      _calState.mode = 'months';
      renderCalGrid();
    });
    // Click outside or Escape closes; mousedown so a re-click on the button toggles.
    document.addEventListener('mousedown', (e) => {
      if (pop.hidden) return;
      if (pop.contains(e.target) || e.target.closest('.ev-cal-btn, .fc-toolbar-title')) return;
      closeDatePicker();
    });
    _calPop = pop;
    return pop;
  }

  function renderCalGrid() {
    if (_calState.mode === 'months') { renderCalMonths(); return; }
    const pop = _calPop;
    const view = _calState.view;
    pop.querySelector('.ev-cal-grid').classList.remove('months');
    pop.querySelector('.ev-cal-title').textContent = view.toFormat('LLLL yyyy');
    const fdow = firstDayOfWeek();
    const header = Array.from({ length: 7 }, (_, i) =>
      `<span class="ev-cal-dow">${WEEKDAY_LABELS[(fdow + i) % 7]}</span>`).join('');
    const monthStart = view.startOf('month');
    // luxon weekday: 1=Mon … 7=Sun → 0=Sun … 6=Sat.
    const startDow = monthStart.weekday % 7;
    const lead = ((startDow - fdow) % 7 + 7) % 7;
    const gridStart = monthStart.minus({ days: lead });
    const selected = _calState.getSelected();
    const today = luxon.DateTime.local().toFormat('yyyy-MM-dd');
    let cells = '';
    for (let i = 0; i < 42; i++) {
      const d = gridStart.plus({ days: i });
      const iso = d.toFormat('yyyy-MM-dd');
      const cls = ['ev-cal-day'];
      if (d.month !== view.month) cls.push('other-month');
      if (iso === selected) cls.push('selected');
      if (iso === today) cls.push('today');
      cells += `<button type="button" class="${cls.join(' ')}" data-iso="${iso}">${d.day}</button>`;
    }
    pop.querySelector('.ev-cal-grid').innerHTML = header + cells;
    pop.querySelectorAll('.ev-cal-day').forEach((b) => {
      b.addEventListener('click', () => {
        _calState.commit(b.dataset.iso);
        closeDatePicker();
      });
    });
  }

  function renderCalMonths() {
    const pop = _calPop;
    const view = _calState.view;
    const grid = pop.querySelector('.ev-cal-grid');
    grid.classList.add('months');
    pop.querySelector('.ev-cal-title').textContent = view.toFormat('yyyy');
    const labels = luxon.Info.months('short');
    const selISO = _calState.getSelected();
    const sel = selISO ? luxon.DateTime.fromISO(selISO) : null;
    const now = luxon.DateTime.local();
    let cells = '';
    for (let m = 1; m <= 12; m++) {
      const cls = ['ev-cal-month'];
      if (sel && sel.year === view.year && sel.month === m) cls.push('selected');
      else if (now.year === view.year && now.month === m) cls.push('today');
      cells += `<button type="button" class="${cls.join(' ')}" data-month="${m}">${labels[m - 1]}</button>`;
    }
    grid.innerHTML = cells;
    grid.querySelectorAll('.ev-cal-month').forEach((b) => {
      b.addEventListener('click', () => {
        const m = +b.dataset.month;
        if (_calState.selectMonth) {
          _calState.commit(view.set({ month: m }).startOf('month').toFormat('yyyy-MM-dd'));
          closeDatePicker();
        } else {
          _calState.view = view.set({ month: m });
          _calState.mode = 'days';
          renderCalGrid();
        }
      });
    });
  }

  // Generic mini-picker open. `commit(iso)` applies the chosen date; `getSelected`
  // returns the value to highlight; `selectMonth` makes the month grid commit
  // directly instead of drilling into days.
  function openCalPicker({ anchor, base, mode, selectMonth, getSelected, commit }) {
    const pop = ensureCalPop();
    const view = (base ? luxon.DateTime.fromISO(base) : luxon.DateTime.local()).startOf('month');
    _calState = { view, mode: mode || 'days', selectMonth: !!selectMonth, getSelected, commit };
    renderCalGrid();
    pop.hidden = false;
    const r = anchor.getBoundingClientRect();
    pop.style.top = `${r.bottom + 4}px`;
    pop.style.left = `${Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)}px`;
  }

  function openDatePicker(prefix, btn, onChange) {
    const cur = getDateFieldValue(prefix);
    // Empty end-date field: open on the event's start month (not today) so a
    // future event doesn't force the user to scroll forward.
    const fallback = (prefix === 'recur-until' && getDateFieldValue('start')) || null;
    openCalPicker({
      anchor: btn, base: cur || fallback, mode: 'days', selectMonth: false,
      getSelected: () => getDateFieldValue(prefix),
      commit: (iso) => { setDateFieldValue(prefix, iso); onChange(); },
    });
  }

  // Click on the FullCalendar header title → jump-to-date picker. Month view
  // picks a month (arrows step years); week/day views pick a day.
  function openCalTitlePicker(titleEl) {
    const isMonth = _fcCalendar.view.type === 'dayGridMonth';
    const cs = _fcCalendar.view.currentStart; // UTC-based date marker
    const cur = luxon.DateTime.fromJSDate(cs, { zone: 'utc' }).toFormat('yyyy-MM-dd');
    openCalPicker({
      anchor: titleEl, base: cur,
      mode: isMonth ? 'months' : 'days', selectMonth: isMonth,
      getSelected: () => cur,
      commit: (iso) => { _fcCalendar.gotoDate(iso); },
    });
  }

  function closeDatePicker() {
    if (_calPop) _calPop.hidden = true;
    _calState = null;
  }

  // Turn a text input into a zero-padded numeric stepper with ▲▼ buttons.
  // Arrow keys and buttons step by `step`, clamped to [min, max]; blur re-pads.
  function attachStepper(id, step, max, onChange, min = 0) {
    const input = document.getElementById(id);
    const bump = (delta) => {
      if (input.disabled) return;
      input.value = pad2(clampInt(clampInt(input.value, min, max) + delta, min, max));
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
      input.value = pad2(clampInt(input.value, min, max));
    });
  }

  // ── Time fields (24h or 12h per time_format setting) ─────────────────────────
  // Like the date fields, the hh/mm inputs are rebuilt on each modal open so a
  // time_format change (no reload) takes effect. In 12h mode the hour input is
  // 1–12 and an AM/PM toggle button is appended. The canonical value handed to
  // luxon / the API is always 24h.

  function timeIs12h() {
    return timeFormatKey() === '12h';
  }

  // Read the hh/mm (+ AM/PM) inputs as canonical 24h { h24, m }.
  function getTimeParts(prefix) {
    const m = clampInt(document.getElementById(`ev-${prefix}-mm`).value, 0, 59);
    if (timeIs12h()) {
      let h = clampInt(document.getElementById(`ev-${prefix}-hh`).value, 1, 12) % 12;
      const ampm = document.getElementById(`ev-${prefix}-ampm`);
      if (ampm && ampm.textContent === 'PM') h += 12;
      return { h24: h, m };
    }
    return { h24: clampInt(document.getElementById(`ev-${prefix}-hh`).value, 0, 23), m };
  }

  // Write a canonical 24h time into the inputs, formatted per the setting.
  function setTimeParts(prefix, h24, m) {
    const hEl = document.getElementById(`ev-${prefix}-hh`);
    if (timeIs12h()) {
      let h12 = h24 % 12;
      if (h12 === 0) h12 = 12;
      hEl.value = pad2(h12);
      const ampm = document.getElementById(`ev-${prefix}-ampm`);
      if (ampm) ampm.textContent = h24 >= 12 ? 'PM' : 'AM';
    } else {
      hEl.value = pad2(h24);
    }
    document.getElementById(`ev-${prefix}-mm`).value = pad2(m);
  }

  // (Re)build one time row's inputs + steppers (+ AM/PM toggle in 12h mode).
  function renderTimeFields(prefix, onChange) {
    const container = document.getElementById(`ev-${prefix}-time-fields`);
    if (!container) return;
    const h12 = timeIs12h();
    container.innerHTML =
      `<input type="text" id="ev-${prefix}-hh" class="ev-hh" inputmode="numeric" maxlength="2">` +
      `<span class="ev-colon">:</span>` +
      `<input type="text" id="ev-${prefix}-mm" class="ev-mm" inputmode="numeric" maxlength="2">` +
      (h12 ? `<button type="button" class="ev-ampm" id="ev-${prefix}-ampm" tabindex="-1">AM</button>` : '');

    document.getElementById(`ev-${prefix}-hh`).addEventListener('change', onChange);
    document.getElementById(`ev-${prefix}-mm`).addEventListener('change', onChange);
    attachStepper(`ev-${prefix}-hh`, 1, h12 ? 12 : 23, onChange, h12 ? 1 : 0);
    attachStepper(`ev-${prefix}-mm`, 5, 59, onChange);

    if (h12) {
      const ampm = document.getElementById(`ev-${prefix}-ampm`);
      ampm.addEventListener('click', () => {
        if (ampm.disabled) return;
        ampm.textContent = ampm.textContent === 'AM' ? 'PM' : 'AM';
        onChange();
      });
    }
  }

  // Read a From/To row (date + hh/mm) into a luxon DateTime in the given zone.
  function readBoundary(prefix, allDay, tz) {
    const d = getDateFieldValue(prefix);
    if (!d) return null;
    if (allDay) return luxon.DateTime.fromISO(d, { zone: tz });
    const { h24, m } = getTimeParts(prefix);
    return luxon.DateTime.fromObject(
      { year: +d.slice(0, 4), month: +d.slice(5, 7), day: +d.slice(8, 10), hour: h24, minute: m },
      { zone: tz },
    );
  }

  function writeBoundary(prefix, dt, allDay) {
    setDateFieldValue(prefix, dt.toFormat('yyyy-MM-dd'));
    if (!allDay) setTimeParts(prefix, dt.hour, dt.minute);
  }

  function refreshPrevBoundaries() {
    const allDay = document.getElementById('ev-allday').checked;
    const tz = effectiveTz();
    _prevStart = readBoundary('start', allDay, tz);
    _prevEnd = readBoundary('end', allDay, tz);
  }

  // Blank-create flow: hh/mm inputs start empty and only get a visible value
  // once the user commits a date for that boundary.
  function timeFieldsBlank(prefix) {
    const hEl = document.getElementById(`ev-${prefix}-hh`);
    const mEl = document.getElementById(`ev-${prefix}-mm`);
    return !!hEl && !!mEl && hEl.value === '' && mEl.value === '';
  }

  // Blank-create flow: once one boundary is set, copy it into the other side's
  // still-empty fields. Returns true if the date was filled.
  function fillBlankBoundary(prefix, dt, allDay) {
    if (getDateFieldValue(prefix)) return false;
    setDateFieldValue(prefix, dt.toFormat('yyyy-MM-dd'));
    if (!allDay && timeFieldsBlank(prefix)) setTimeParts(prefix, dt.hour, dt.minute);
    return true;
  }

  // From changed: keep the same duration by shifting To along with it.
  function onFromChange() {
    if (!_currentEvent || !_currentEvent.editable) return;
    const allDay = document.getElementById('ev-allday').checked;
    const tz = effectiveTz();
    // A date typed into a blank row gets a visible midnight time.
    if (!allDay && getDateFieldValue('start') && timeFieldsBlank('start')) {
      setTimeParts('start', 0, 0);
    }
    const newStart = readBoundary('start', allDay, tz);
    if (!newStart || !newStart.isValid) return;
    if (fillBlankBoundary('end', newStart, allDay)) {
      _prevEnd = readBoundary('end', allDay, tz);
    } else if (_prevStart && _prevStart.isValid && _prevEnd && _prevEnd.isValid) {
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
    recurOnStartChange();
  }

  // To changed: leave From alone, but never let To fall before From.
  function onToChange() {
    if (!_currentEvent || !_currentEvent.editable) return;
    const allDay = document.getElementById('ev-allday').checked;
    const tz = effectiveTz();
    // A date typed into a blank row gets a visible midnight time.
    if (!allDay && getDateFieldValue('end') && timeFieldsBlank('end')) {
      setTimeParts('end', 0, 0);
    }
    let newEnd = readBoundary('end', allDay, tz);
    if (!newEnd || !newEnd.isValid) return;
    fillBlankBoundary('start', newEnd, allDay);
    const start = readBoundary('start', allDay, tz);
    if (start && start.isValid && newEnd < start) {
      newEnd = start;
      writeBoundary('end', newEnd, allDay);
    }
    _prevStart = start;
    _prevEnd = newEnd;
  }

  function setEditable(on) {
    ['ev-name', 'ev-calendar', 'ev-allday', 'ev-start-hh', 'ev-start-mm',
     'ev-end-hh', 'ev-end-mm', 'ev-location', 'ev-notes'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !on;
    });
    document.querySelectorAll(
      '.ev-date-fields input, .ev-date-fields button, .ev-time-fields input, .ev-ampm',
    ).forEach((el) => {
      el.disabled = !on;
    });
    document.getElementById('btn-event-save').style.display = on ? '' : 'none';
    _remindersEditable = on;
    renderReminders();
  }

  async function openEventModal(event) {
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

    // Rebuild date + time inputs per current date_format / time_format before
    // populating values.
    renderDateFields('start', onFromChange);
    renderDateFields('end', onToChange);
    renderTimeFields('start', onFromChange);
    renderTimeFields('end', onToChange);

    if (event.allDay) {
      setDateFieldValue('start', String(rawStart || '').slice(0, 10));
      setDateFieldValue('end', String(rawEnd || rawStart || '').slice(0, 10));
    } else {
      const from = isoToInputs(rawStart, tz);
      const to = isoToInputs(rawEnd, tz);
      setDateFieldValue('start', from.date);
      setTimeParts('start', from.hour, from.minute);
      setDateFieldValue('end', to.date);
      setTimeParts('end', to.hour, to.minute);
    }

    const recurrence = props.recurrence || '';
    document.getElementById('ev-repeats').checked = !!recurrence;
    // A recurring series can't be un-recurred from here, so lock the toggle.
    document.getElementById('ev-repeats').disabled = !!recurrence;
    const sumEl = document.getElementById('ev-recur-summary');
    if (recurrence) {
      sumEl.textContent = `Current: ${recurrence}`;
      sumEl.style.display = '';
    } else {
      sumEl.style.display = 'none';
    }
    resetRecurEditorDefaults();
    if (props.recurrenceRule) setRecurrence(props.recurrenceRule);

    document.getElementById('ev-location').value = props.location || '';
    document.getElementById('ev-notes').value = props.description || '';

    resetReminders(props.reminders);

    // Demo events have no calendar and stay read-only. Recurring events are
    // editable, but saving asks which occurrences to change.
    const noteEl = document.getElementById('ev-edit-note');
    let editable = true;
    let note = '';
    if (props.calendarId == null) {
      editable = false;
      note = 'Demo event — connect a CalDAV account to add real events.';
    } else if (recurrence) {
      note = 'Recurring event — you’ll choose which occurrences to change when you save.';
    }
    noteEl.textContent = note;
    noteEl.style.display = note ? '' : 'none';

    // Edit mode: show the calendar picker so the event can be moved between
    // calendars. Demo events (no calendar) hide it. Offer Delete if editable.
    const calField = document.getElementById('ev-calendar-field');
    if (props.calendarId != null) {
      const cals = await getEnabledCalendars();
      let opts = cals;
      if (!cals.some((c) => c.id === props.calendarId)) {
        opts = cals.concat([{ id: props.calendarId, display_name: 'Current calendar' }]);
      }
      const calSel = document.getElementById('ev-calendar');
      calSel.innerHTML = opts
        .map((c) => `<option value="${c.id}">${escHtml(c.display_name)}</option>`)
        .join('');
      calSel.value = String(props.calendarId);
      // Moving recreates a single event, so recurring series can't be moved.
      calSel.disabled = !!recurrence;
      calField.style.display = '';
    } else {
      calField.style.display = 'none';
    }
    // Recurring events are editable and deletable by scope, so offer Delete
    // whenever the event is calendar-backed.
    const deletable = props.calendarId != null;
    document.getElementById('btn-event-delete').style.display = deletable ? '' : 'none';
    setEditable(editable);

    _currentEvent = {
      id: event.id,
      calendarId: props.calendarId,
      originalCalendarId: props.calendarId,
      editable,
      recurring: !!recurrence,
      rawStart: props.rawStart || (event.start ? event.start.toISOString() : null),
      // Stable pivot for scoped edits: an already-detached override keeps its
      // RECURRENCE-ID even after being moved, so prefer it over the (mutable)
      // current start to avoid creating a duplicate override on re-edit.
      recurrenceId: props.recurrenceId || null,
      isNew: false,
    };

    refreshPrevBoundaries();
    applyAllDayToggle();
    applyRepeatsToggle();

    show('event-overlay');
    show('event-modal');
  }

  // ── Event creation ───────────────────────────────────────────────────────────

  // Enabled calendars, cached after first load; used to populate the create
  // modal's calendar picker. Refreshed lazily when the cache is empty.
  let _calendarsCache = null;

  async function getEnabledCalendars(force) {
    if (_calendarsCache && !force) return _calendarsCache;
    try {
      const cals = await apiGet('/calendars');
      _calendarsCache = cals.filter((c) => c.enabled);
    } catch (_) {
      _calendarsCache = [];
    }
    return _calendarsCache;
  }

  // Round a luxon DateTime to the nearest `step` minutes (within its own day).
  function roundToMinutes(dt, step) {
    const mins = dt.hour * 60 + dt.minute;
    const rounded = Math.round(mins / step) * step;
    return dt.startOf('day').plus({ minutes: rounded });
  }

  async function openCreateModal(start, end, allDay) {
    hideError('ev-error');
    const cals = await getEnabledCalendars();

    document.getElementById('ev-title-text').textContent = 'New event';
    document.getElementById('ev-name').value = '';
    document.getElementById('ev-allday').checked = !!allDay;
    document.getElementById('ev-location').value = '';
    document.getElementById('ev-notes').value = '';
    document.getElementById('ev-repeats').checked = false;
    document.getElementById('ev-repeats').disabled = false;
    document.getElementById('ev-recur-summary').style.display = 'none';
    resetRecurEditorDefaults();
    resetReminders([]);

    // Populate the calendar picker (create-only).
    const calField = document.getElementById('ev-calendar-field');
    const calSel = document.getElementById('ev-calendar');
    calSel.innerHTML = cals
      .map((c) => `<option value="${c.id}">${escHtml(c.display_name)}</option>`)
      .join('');
    // Pre-select the user's default calendar (else the first enabled one).
    const dflt = cals.find((c) => c.is_default);
    if (dflt) calSel.value = String(dflt.id);
    calField.style.display = '';
    document.getElementById('btn-event-delete').style.display = 'none';

    renderDateFields('start', onFromChange);
    renderDateFields('end', onToChange);
    renderTimeFields('start', onFromChange);
    renderTimeFields('end', onToChange);

    setDateFieldValue('start', start.toFormat('yyyy-MM-dd'));
    setDateFieldValue('end', end.toFormat('yyyy-MM-dd'));
    if (!allDay) {
      setTimeParts('start', start.hour, start.minute);
      setTimeParts('end', end.hour, end.minute);
    }

    const noteEl = document.getElementById('ev-edit-note');
    const hasCal = cals.length > 0;
    if (!hasCal) {
      noteEl.textContent = 'Connect a CalDAV account to create events.';
      noteEl.style.display = '';
    } else {
      noteEl.style.display = 'none';
    }
    setEditable(hasCal);

    _currentEvent = {
      id: null,
      calendarId: hasCal ? parseInt(calSel.value, 10) : null,
      editable: hasCal,
      isNew: true,
    };

    refreshPrevBoundaries();
    applyAllDayToggle();
    applyRepeatsToggle();

    show('event-overlay');
    show('event-modal');
  }

  function closeEventModal() {
    closeDatePicker();
    hide('event-overlay');
    hide('event-modal');
    _currentEvent = null;
    // Discard any drag-selection highlight left by a create-from-select.
    if (_fcCalendar) _fcCalendar.unselect();
  }

  async function saveEvent() {
    if (!_currentEvent || !_currentEvent.editable) return;
    hideError('ev-error');
    const allDay = document.getElementById('ev-allday').checked;
    const startDate = getDateFieldValue('start');
    const endDate = getDateFieldValue('end');
    const name = document.getElementById('ev-name').value.trim();

    if (!name) { showError('ev-error', 'Name is required.'); return; }
    if (!startDate) { showError('ev-error', 'Start date is required.'); return; }

    const pad = (n) => String(n).padStart(2, '0');
    const timeStr = (prefix) => {
      const { h24, m } = getTimeParts(prefix);
      return `${pad(h24)}:${pad(m)}`;
    };

    const body = {
      calendar_id: _currentEvent.calendarId,
      title: name,
      all_day: allDay,
      location: document.getElementById('ev-location').value,
      description: document.getElementById('ev-notes').value,
      timezone: effectiveTz(),
      // Always the full replacement set; [] clears all editable alarms.
      reminders: collectReminders(),
    };
    const recurrence = getRecurrence();
    if (recurrence) body.recurrence = recurrence;
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

    // Editing a recurring event: pick which occurrences the change applies to.
    if (!_currentEvent.isNew && _currentEvent.recurring) {
      const scope = await chooseScope('What to change?');
      if (!scope) return;
      body.scope = scope;
      const pivot = _currentEvent.recurrenceId || _currentEvent.rawStart;
      if (pivot) body.recurrence_id = pivot;
    }

    const btn = document.getElementById('btn-event-save');
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      if (_currentEvent.isNew) {
        await apiPost('/events', body);
      } else {
        // Tell the server the original calendar so it can move the event when
        // the picker was changed.
        body.original_calendar_id = _currentEvent.originalCalendarId;
        await apiPut(`/events/${encodeURIComponent(_currentEvent.id)}`, body);
      }
      closeEventModal();
      refreshViews();
    } catch (err) {
      showError('ev-error', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Save';
    }
  }

  // Delete the event currently open in the modal (Delete button). No confirm
  // here — the spec reserves the "are you sure" prompt for the right-click menu.
  async function deleteCurrentEvent() {
    if (!_currentEvent || _currentEvent.isNew || _currentEvent.calendarId == null) return;
    // Recurring events delete by scope; pick one before hitting the server.
    let qs = `calendar_id=${_currentEvent.calendarId}`;
    if (_currentEvent.recurring) {
      const scope = await chooseScope('What to delete?');
      if (!scope) return;
      qs += `&scope=${scope}`;
      const pivot = _currentEvent.recurrenceId || _currentEvent.rawStart;
      if (pivot) {
        qs += `&recurrence_id=${encodeURIComponent(pivot)}`;
      }
    }
    const btn = document.getElementById('btn-event-delete');
    btn.disabled = true;
    try {
      await apiDelete(`/events/${encodeURIComponent(_currentEvent.id)}?${qs}`);
      closeEventModal();
      refreshViews();
    } catch (err) {
      showError('ev-error', err.message);
    } finally {
      btn.disabled = false;
    }
  }

  function initEventModal() {
    document.getElementById('btn-event-close').addEventListener('click', closeEventModal);
    document.getElementById('btn-event-cancel').addEventListener('click', closeEventModal);
    document.getElementById('btn-event-save').addEventListener('click', saveEvent);
    document.getElementById('btn-event-delete').addEventListener('click', deleteCurrentEvent);
    document.getElementById('event-overlay').addEventListener('click', closeEventModal);
    document.getElementById('ev-calendar').addEventListener('change', (e) => {
      if (_currentEvent) _currentEvent.calendarId = parseInt(e.target.value, 10);
    });
    document.getElementById('ev-allday').addEventListener('change', () => {
      applyAllDayToggle();
      refreshPrevBoundaries();
      recurOnStartChange();
      remindersOnAllDayToggle();
    });
    document.getElementById('ev-repeats').addEventListener('change', applyRepeatsToggle);
    document.getElementById('ev-reminder-add').addEventListener('click', addReminderRow);
    initRecurEditor();
    // Date-field and time-field listeners/steppers are bound per-open inside
    // renderDateFields / renderTimeFields.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { closeEventModal(); hideContextMenu(); closeConfirm(); closeScope(); }
    });
    initContextMenu();
    initConfirm();
    initScopeChooser();
  }

  // ── Right-click context menu ─────────────────────────────────────────────────

  let _ctxEvent = null;

  function showContextMenu(x, y, event) {
    _ctxEvent = event;
    const menu = document.getElementById('ev-context-menu');
    menu.style.display = '';
    // Keep the menu on-screen.
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    menu.style.left = `${Math.min(x, window.innerWidth - mw - 8)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - mh - 8)}px`;
  }

  function hideContextMenu() {
    document.getElementById('ev-context-menu').style.display = 'none';
    _ctxEvent = null;
  }

  function initContextMenu() {
    const menu = document.getElementById('ev-context-menu');
    document.getElementById('ctx-edit').addEventListener('click', () => {
      const ev = _ctxEvent;
      hideContextMenu();
      if (ev) openEventModal(ev);
    });
    document.getElementById('ctx-delete').addEventListener('click', async () => {
      const ev = _ctxEvent;
      hideContextMenu();
      if (!ev) return;
      const props = ev.extendedProps || {};
      if (props.calendarId == null) return;
      let qs = `calendar_id=${props.calendarId}`;
      if (props.recurrence) {
        // Recurring: a scope choice replaces the plain yes/no confirm.
        const scope = await chooseScope('What to delete?');
        if (!scope) return;
        qs += `&scope=${scope}`;
        const pivot =
          props.recurrenceId || props.rawStart || (ev.start ? ev.start.toISOString() : null);
        if (pivot) qs += `&recurrence_id=${encodeURIComponent(pivot)}`;
      } else {
        const ok = await confirmDialog(`Delete "${ev.title || 'this event'}"?`);
        if (!ok) return;
      }
      try {
        await apiDelete(`/events/${encodeURIComponent(ev.id)}?${qs}`);
        refreshViews();
      } catch (err) {
        alert(err.message);
      }
    });
    // Any outside click / scroll dismisses the menu.
    document.addEventListener('click', (e) => {
      if (!menu.contains(e.target)) hideContextMenu();
    });
    document.addEventListener('contextmenu', (e) => {
      if (!e.target.closest('.fc-event') && !menu.contains(e.target)) hideContextMenu();
    });
  }

  // ── Confirm dialog (yes/no) ──────────────────────────────────────────────────

  let _confirmResolve = null;

  function confirmDialog(text) {
    document.getElementById('confirm-text').textContent = text;
    show('confirm-overlay');
    show('confirm-modal');
    return new Promise((resolve) => { _confirmResolve = resolve; });
  }

  function closeConfirm(result) {
    hide('confirm-overlay');
    hide('confirm-modal');
    if (_confirmResolve) {
      _confirmResolve(!!result);
      _confirmResolve = null;
    }
  }

  function initConfirm() {
    document.getElementById('confirm-yes').addEventListener('click', () => closeConfirm(true));
    document.getElementById('confirm-no').addEventListener('click', () => closeConfirm(false));
    document.getElementById('confirm-overlay').addEventListener('click', () => closeConfirm(false));
  }

  // ── Recurring scope chooser ──────────────────────────────────────────────────
  // Resolves to one of this|thisfuture|all, or null if cancelled.

  let _scopeResolve = null;

  function chooseScope(text) {
    document.getElementById('scope-title').textContent = text;
    show('scope-overlay');
    show('scope-modal');
    return new Promise((resolve) => { _scopeResolve = resolve; });
  }

  function closeScope(result) {
    hide('scope-overlay');
    hide('scope-modal');
    if (_scopeResolve) {
      _scopeResolve(result || null);
      _scopeResolve = null;
    }
  }

  function initScopeChooser() {
    document.querySelectorAll('#scope-modal [data-scope]').forEach((btn) => {
      btn.addEventListener('click', () => closeScope(btn.getAttribute('data-scope')));
    });
    document.getElementById('scope-cancel').addEventListener('click', () => closeScope(null));
    document.getElementById('scope-overlay').addEventListener('click', () => closeScope(null));
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
    if (props.calendarId == null) {
      info.revert();
      return;
    }
    const body = eventToBody(info.event);
    if (props.recurrence) {
      const scope = await chooseScope('What to change?');
      if (!scope) { info.revert(); return; }
      body.scope = scope;
      // recurrence_id is the pivot: a detached override's stable RECURRENCE-ID
      // when present, else the ORIGINAL (pre-drag) occurrence start.
      const pivot =
        props.recurrenceId ||
        props.rawStart ||
        (info.oldEvent && info.oldEvent.start ? info.oldEvent.start.toISOString() : null);
      if (pivot) body.recurrence_id = pivot;
    }
    try {
      await apiPut(`/events/${encodeURIComponent(info.event.id)}`, body);
      // Reload so scope splits / overrides (new resources) render correctly.
      refreshViews();
    } catch (err) {
      alert(err.message);
      info.revert();
    }
  }

  // ── Idle-logout countdown ───────────────────────────────────────────────────
  // The server uses a sliding idle window reset by any data request. We poll the
  // non-refreshing GET /auth/session to read the true remaining time, then tick
  // locally between polls. Hitting zero logs the user out.

  let _logoutEnabled = true;
  let _logoutRemaining = null; // seconds, locally interpolated
  let _logoutTick = null;
  let _logoutPoll = null;
  let _loggingOut = false;

  function fmtDuration(secs) {
    secs = Math.max(0, Math.floor(secs));
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  function renderLogoutCountdown() {
    const el = document.getElementById('logout-countdown');
    if (!el) return;
    if (!_logoutEnabled) {
      el.textContent = 'Auto-logout off';
      el.classList.remove('logout-countdown--warn');
      return;
    }
    if (_logoutRemaining == null) {
      el.textContent = '';
      return;
    }
    el.textContent = 'Logout in ' + fmtDuration(_logoutRemaining);
    el.classList.toggle('logout-countdown--warn', _logoutRemaining <= 60);
  }

  async function doAutoLogout() {
    if (_loggingOut) return;
    _loggingOut = true;
    if (_logoutTick) clearInterval(_logoutTick);
    if (_logoutPoll) clearInterval(_logoutPoll);
    try { await fetch('/auth/logout', { method: 'POST', headers: { 'X-Requested-With': 'fetch' } }); } catch (_) {}
    window.location.href = '/';
  }

  async function refreshLogoutCountdown() {
    try {
      const r = await fetch('/auth/session');
      if (r.status === 401) { doAutoLogout(); return; }
      if (!r.ok) return;
      const d = await r.json();
      _logoutEnabled = !!d.enabled;
      _logoutRemaining = d.enabled ? d.remaining_seconds : null;
      renderLogoutCountdown();
    } catch (_) {}
  }

  function startLogoutCountdown() {
    const s = window.__SETTINGS__ || {};
    _logoutEnabled = s.auto_logout_enabled ?? true;
    _logoutRemaining = _logoutEnabled ? (s.auto_logout_timeout_seconds ?? null) : null;
    renderLogoutCountdown();
    refreshLogoutCountdown();
    _logoutTick = setInterval(() => {
      if (!_logoutEnabled || _logoutRemaining == null) return;
      _logoutRemaining -= 1;
      if (_logoutRemaining <= 0) { _logoutRemaining = 0; renderLogoutCountdown(); doAutoLogout(); return; }
      renderLogoutCountdown();
    }, 1000);
    // Resync with server truth (also catches activity from other tabs/requests).
    _logoutPoll = setInterval(refreshLogoutCountdown, 10000);
  }

  // ── Agenda view ─────────────────────────────────────────────────────────────

  // The agenda is a custom DOM panel (not a FullCalendar view) so it can grow
  // forever: it fetches /events in tiled forward windows and appends rows on
  // scroll. Open-ended recurrence keeps yielding rows so scroll never ends; a
  // finite calendar stops after AGENDA_MAX_EMPTY consecutive empty windows.
  const AGENDA_CHUNK_DAYS = 30;
  const AGENDA_MAX_EMPTY = 6; // ~6 months of nothing → assume no more events
  let _agendaActive = false;
  let _agendaCursor = null; // luxon DateTime, start of the next window (user tz)
  let _agendaEmptyRuns = 0;
  let _agendaLoading = false;
  let _agendaDone = false;
  let _agendaSeen = null; // Set of `${id}|${rawStart}` for boundary dedup
  let _agendaLastDayKey = null; // last rendered day header (yyyy-MM-dd)
  let _agendaObserver = null;

  function agendaBtnEl() {
    return document.querySelector('.fc-agenda-button');
  }

  function showAgenda() {
    if (_agendaActive) return;
    _agendaActive = true;
    // Keep #calendar (and its header toolbar with the view buttons) visible;
    // .agenda-mode collapses just the FC view area below the toolbar.
    document.querySelector('.calendar-body').classList.add('agenda-mode');
    show('agenda');
    const titleEl = document.querySelector('.fc-toolbar-title');
    if (titleEl) titleEl.textContent = 'Agenda';
    const btn = agendaBtnEl();
    if (btn) btn.classList.add('fc-button-active');
    document
      .querySelectorAll(
        '.fc-dayGridMonth-button,.fc-timeGridWeek-button,.fc-timeGridDay-button',
      )
      .forEach((b) => b.classList.remove('fc-button-active'));
    agendaReset();
    agendaLoadMore();
  }

  function hideAgenda() {
    if (!_agendaActive) return;
    _agendaActive = false;
    hide('agenda');
    document.querySelector('.calendar-body').classList.remove('agenda-mode');
    // Restore the date title we replaced with "Agenda". FC only rewrites it on
    // navigation/view change, which may not happen on the way out.
    const titleEl = document.querySelector('.fc-toolbar-title');
    if (titleEl && _fcCalendar) titleEl.textContent = _fcCalendar.view.title;
    const btn = agendaBtnEl();
    if (btn) btn.classList.remove('fc-button-active');
    // FC didn't change views while the agenda was up, so it won't re-mark the
    // current view's button as active — restore it ourselves.
    if (_fcCalendar) {
      const cur = document.querySelector('.fc-' + _fcCalendar.view.type + '-button');
      if (cur) cur.classList.add('fc-button-active');
    }
    if (_agendaObserver) _agendaObserver.disconnect();
    // Correct layout drift from the view harness having been display:none.
    if (_fcCalendar) _fcCalendar.updateSize();
  }

  function agendaReset() {
    const tz = effectiveTz();
    _agendaCursor = luxon.DateTime.now().setZone(tz).startOf('day');
    _agendaEmptyRuns = 0;
    _agendaLoading = false;
    _agendaDone = false;
    _agendaSeen = new Set();
    _agendaLastDayKey = null;
    document.getElementById('agenda-list').innerHTML = '';
    agendaSetStatus('');
    agendaObserve();
  }

  function agendaObserve() {
    if (_agendaObserver) _agendaObserver.disconnect();
    const root = document.getElementById('agenda-scroll');
    const sentinel = document.getElementById('agenda-sentinel');
    _agendaObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) agendaLoadMore();
      },
      { root, rootMargin: '300px' },
    );
    _agendaObserver.observe(sentinel);
  }

  function agendaCompare(a, b) {
    if (a.__sortKey !== b.__sortKey) return a.__sortKey - b.__sortKey;
    // Same instant: all-day first, then alphabetical.
    if (!!a.allDay !== !!b.allDay) return a.allDay ? -1 : 1;
    return String(a.title || '').localeCompare(String(b.title || ''));
  }

  async function agendaLoadMore() {
    if (_agendaLoading || _agendaDone || !_agendaActive) return;
    _agendaLoading = true;
    agendaSetStatus('loading');
    const from = _agendaCursor;
    const to = from.plus({ days: AGENDA_CHUNK_DAYS });
    try {
      const params = new URLSearchParams({ from: from.toISO(), to: to.toISO() });
      const r = await fetch('/events?' + params.toString());
      if (!r.ok) throw new Error('Failed to fetch events');
      const data = await r.json();

      const fresh = [];
      for (const e of data) {
        const p = e.extendedProps || {};
        const sISO = p.rawStart || e.start;
        const s = luxon.DateTime.fromISO(sISO, { setZone: true });
        if (s < from || s >= to) continue; // half-open window guard
        const key = (e.id || '') + '|' + sISO;
        if (_agendaSeen.has(key)) continue;
        _agendaSeen.add(key);
        e.__sortKey = s.toMillis();
        fresh.push(e);
      }

      if (fresh.length === 0) {
        _agendaEmptyRuns += 1;
        if (_agendaEmptyRuns >= AGENDA_MAX_EMPTY) {
          _agendaDone = true;
          agendaSetStatus('end');
        } else {
          agendaSetStatus('');
        }
      } else {
        _agendaEmptyRuns = 0;
        fresh.sort(agendaCompare);
        agendaAppendRows(fresh);
        agendaSetStatus('');
      }
      _agendaCursor = to; // windows tile forward regardless
    } catch (err) {
      agendaSetStatus('error', err.message);
      _agendaDone = true;
    } finally {
      _agendaLoading = false;
      if (!_agendaDone && _agendaActive) maybeContinue();
    }
  }

  // The observer only fires when the sentinel *crosses* the margin boundary; a
  // load that appends rows but leaves the sentinel inside the margin produces no
  // new callback and the scroll stalls. Keep loading until the sentinel sits
  // clearly below the fold (same 300px margin the observer uses).
  function maybeContinue() {
    const root = document.getElementById('agenda-scroll');
    const sentinel = document.getElementById('agenda-sentinel');
    const near =
      sentinel.getBoundingClientRect().top <=
      root.getBoundingClientRect().bottom + 300;
    if (near) agendaLoadMore();
  }

  function agendaAppendRows(events) {
    const tz = effectiveTz();
    const list = document.getElementById('agenda-list');
    const todayKey = luxon.DateTime.now().setZone(tz).toFormat('yyyy-MM-dd');
    const timeFmt = timeFormatKey() === '12h' ? 'h:mm a' : 'HH:mm';
    const headerFmt = 'cccc, ' + luxonDateFmt(dateFormatKey());
    const frag = document.createDocumentFragment();

    for (const e of events) {
      const p = e.extendedProps || {};
      const sISO = p.rawStart || e.start;
      const start = luxon.DateTime.fromISO(sISO, { setZone: true }).setZone(tz);
      const dayKey = start.toFormat('yyyy-MM-dd');

      if (dayKey !== _agendaLastDayKey) {
        _agendaLastDayKey = dayKey;
        const h = document.createElement('div');
        h.className = 'agenda-day-header' + (dayKey === todayKey ? ' is-today' : '');
        h.textContent = start.toFormat(headerFmt);
        frag.appendChild(h);
      }

      const row = document.createElement('div');
      row.className = 'agenda-row';
      const timeTxt = e.allDay ? 'All day' : start.toFormat(timeFmt);
      const loc = p.location
        ? `<div class="agenda-loc">${escHtml(p.location)}</div>`
        : '';
      row.innerHTML =
        `<span class="agenda-time">${escHtml(timeTxt)}</span>` +
        `<span class="agenda-dot" style="background:${escHtml(e.color || '#3788d8')}"></span>` +
        `<span class="agenda-main"><div class="agenda-title">${escHtml(e.title || '(no title)')}</div>${loc}</span>`;
      row.addEventListener('click', () => openEventModal(agendaToFcShim(e)));
      frag.appendChild(row);
    }
    list.appendChild(frag);
  }

  // Build the minimal FullCalendar-event shape openEventModal() consumes from a
  // plain /events JSON object, so editing/deleting works unchanged.
  function agendaToFcShim(e) {
    const toDate = (v) => (v ? new Date(v) : null);
    return {
      id: e.id,
      title: e.title || '',
      allDay: !!e.allDay,
      start: toDate(e.start),
      end: toDate(e.end),
      extendedProps: e.extendedProps || {},
    };
  }

  function agendaSetStatus(kind, msg) {
    const el = document.getElementById('agenda-status');
    if (kind === 'loading') {
      el.style.display = '';
      el.innerHTML = '<span class="agenda-spinner"></span>';
    } else if (kind === 'end') {
      el.style.display = '';
      el.textContent = document.getElementById('agenda-list').children.length
        ? 'No more events.'
        : 'No upcoming events.';
    } else if (kind === 'error') {
      el.style.display = '';
      el.innerHTML =
        `Couldn’t load events. <button type="button" id="agenda-retry" class="btn-outline">Retry</button>`;
      el.querySelector('#agenda-retry').addEventListener('click', () => {
        _agendaDone = false;
        agendaSetStatus('');
        agendaLoadMore();
      });
    } else {
      el.style.display = 'none';
      el.textContent = '';
    }
  }

  // Reload whichever view(s) are live after a create/edit/delete.
  function refreshViews() {
    if (_fcCalendar) _fcCalendar.refetchEvents();
    if (_agendaActive) agendaReset();
    if (_agendaActive) agendaLoadMore();
    // A local create/edit/delete won't wait for the 10-min poll: reschedule
    // notifications now (force a refetch — the change is already committed).
    if ((window.__SETTINGS__ || {}).notifications_enabled) resyncNotifications(true);
  }

  // Create modal with no start/end preselected (the "+" FAB). A blank start
  // date is fine: saveEvent() already reports "Start date is required."
  async function openCreateModalBlank() {
    hideError('ev-error');
    const cals = await getEnabledCalendars();

    document.getElementById('ev-title-text').textContent = 'New event';
    document.getElementById('ev-name').value = '';
    document.getElementById('ev-allday').checked = false;
    document.getElementById('ev-location').value = '';
    document.getElementById('ev-notes').value = '';
    document.getElementById('ev-repeats').checked = false;
    document.getElementById('ev-repeats').disabled = false;
    document.getElementById('ev-recur-summary').style.display = 'none';
    resetRecurEditorDefaults();
    resetReminders([]);

    const calField = document.getElementById('ev-calendar-field');
    const calSel = document.getElementById('ev-calendar');
    calSel.innerHTML = cals
      .map((c) => `<option value="${c.id}">${escHtml(c.display_name)}</option>`)
      .join('');
    const dflt = cals.find((c) => c.is_default);
    if (dflt) calSel.value = String(dflt.id);
    calField.style.display = '';
    document.getElementById('btn-event-delete').style.display = 'none';

    // Render the field widgets but leave them blank (no setDateFieldValue /
    // setTimeParts) — that is the whole point of the blank-create flow.
    renderDateFields('start', onFromChange);
    renderDateFields('end', onToChange);
    renderTimeFields('start', onFromChange);
    renderTimeFields('end', onToChange);

    const noteEl = document.getElementById('ev-edit-note');
    const hasCal = cals.length > 0;
    if (!hasCal) {
      noteEl.textContent = 'Connect a CalDAV account to create events.';
      noteEl.style.display = '';
    } else {
      noteEl.style.display = 'none';
    }
    setEditable(hasCal);

    _currentEvent = {
      id: null,
      calendarId: hasCal ? parseInt(calSel.value, 10) : null,
      editable: hasCal,
      isNew: true,
    };

    refreshPrevBoundaries();
    applyAllDayToggle();
    applyRepeatsToggle();

    show('event-overlay');
    show('event-modal');
  }

  // ── Calendar page ───────────────────────────────────────────────────────────

  function initCalendar() {
    show('page-calendar');

    const emailEl = document.getElementById('header-email');
    if (window.__USER_EMAIL__) emailEl.textContent = window.__USER_EMAIL__;

    document.getElementById('btn-logout').addEventListener('click', async () => {
      if (_logoutTick) clearInterval(_logoutTick);
      if (_logoutPoll) clearInterval(_logoutPoll);
      await fetch('/auth/logout', { method: 'POST', headers: { 'X-Requested-With': 'fetch' } });
      window.location.href = '/';
    });

    startLogoutCountdown();
    initSettingsPanel();
    initEventModal();
    if ((window.__SETTINGS__ || {}).notifications_enabled) startNotifications();

    const calendarEl = document.getElementById('calendar');
    const s = window.__SETTINGS__ || {};
    const tf = fcTimeFormats(timeFormatKey());
    _fcCalendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      customButtons: {
        agenda: { text: 'agenda', click: showAgenda },
      },
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'agenda dayGridMonth,timeGridWeek,timeGridDay',
      },
      // Clicking any built-in view button (or navigating) leaves the agenda.
      datesSet: function () {
        if (_agendaActive) hideAgenda();
      },
      firstDay: s.first_day_of_week != null ? s.first_day_of_week : 1,
      timeZone: s.timezone || 'local',
      eventTimeFormat: tf.eventTimeFormat,
      slotLabelFormat: tf.slotLabelFormat,
      views: fcViewFormats(dateFormatKey()),
      height: '100%',
      // Enable drag-to-move and edge-resize; both start and end edges.
      editable: true,
      eventResizableFromStart: true,
      // Click vs drag for event creation: a pixel threshold keeps a plain click
      // out of `select` (→ dateClick) while a real drag fires `select`.
      selectable: true,
      selectMinDistance: 5,
      events: async function (fetchInfo, successCallback, failureCallback) {
        try {
          const params = new URLSearchParams({ from: fetchInfo.startStr, to: fetchInfo.endStr });
          const r = await fetch('/events?' + params.toString());
          if (!r.ok) throw new Error('Failed to fetch events');
          const data = await r.json();
          // Only real (calendar-backed) events are editable; recurring ones
          // prompt for occurrence scope on drop (see onEventChange).
          data.forEach((e) => {
            const p = e.extendedProps || {};
            e.editable = p.calendarId != null;
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
      // Plain click on empty space → create modal with view-specific defaults.
      dateClick: function (info) {
        hideContextMenu();
        const tz = effectiveTz();
        if (info.view.type === 'dayGridMonth') {
          // Month: clicked day as From/To date, now (rounded to 5 min) as the
          // From time, default 1-hour duration.
          const day = info.dateStr.slice(0, 10);
          const t = roundToMinutes(luxon.DateTime.now().setZone(tz), 5);
          const start = luxon.DateTime.fromObject(
            { year: +day.slice(0, 4), month: +day.slice(5, 7), day: +day.slice(8, 10),
              hour: t.hour, minute: t.minute },
            { zone: tz },
          );
          openCreateModal(start, start.plus({ hours: 1 }), false);
        } else if (info.allDay) {
          // Week/Day all-day lane → one-day all-day event.
          const start = luxon.DateTime.fromISO(info.dateStr.slice(0, 10), { zone: tz });
          openCreateModal(start, start, true);
        } else {
          // Week/Day timed: snap to the nearest half-hour, 30-minute slot.
          const start = roundToMinutes(
            luxon.DateTime.fromISO(info.dateStr, { setZone: true }).setZone(tz), 30);
          openCreateModal(start, start.plus({ minutes: 30 }), false);
        }
      },
      // Drag over empty space → create modal spanning the dragged range.
      select: function (info) {
        hideContextMenu();
        const tz = effectiveTz();
        if (info.allDay) {
          const startDay = info.startStr.slice(0, 10);
          let endDay = shiftDateStr(info.endStr, -1); // DTEND exclusive → inclusive
          if (endDay < startDay) endDay = startDay;
          openCreateModal(
            luxon.DateTime.fromISO(startDay, { zone: tz }),
            luxon.DateTime.fromISO(endDay, { zone: tz }),
            true,
          );
        } else {
          openCreateModal(
            luxon.DateTime.fromISO(info.startStr, { setZone: true }).setZone(tz),
            luxon.DateTime.fromISO(info.endStr, { setZone: true }).setZone(tz),
            false,
          );
        }
      },
      eventDidMount: function (info) {
        const props = info.event.extendedProps || {};
        // Demo events have no calendar; skip the right-click menu for them.
        if (props.calendarId == null) return;
        info.el.addEventListener('contextmenu', function (e) {
          e.preventDefault();
          showContextMenu(e.pageX, e.pageY, info.event);
        });
      },
      eventDrop: onEventChange,
      eventResize: onEventChange,
    });
    _fcCalendar.render();

    document.getElementById('btn-create-fab').addEventListener('click', openCreateModalBlank);

    // datesSet only fires when the view/range actually changes, so clicking the
    // button of the view FC is already on (e.g. "month" while month sits under
    // the agenda) wouldn't leave the agenda. Catch every toolbar button click.
    const toolbarEl = calendarEl.querySelector('.fc-header-toolbar');
    if (toolbarEl) {
      toolbarEl.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b || b.classList.contains('fc-agenda-button')) return;
        hideAgenda();
      });
    }

    // Apply the user's default view (month is already the FC initialView).
    const dv = (window.__SETTINGS__ || {}).default_view;
    if (dv === 'agenda') {
      showAgenda();
    } else if (dv === 'timeGridWeek' || dv === 'timeGridDay') {
      _fcCalendar.changeView(dv);
    }

    // The title node is re-rendered on navigation, so delegate from the calendar.
    calendarEl.addEventListener('click', (e) => {
      const t = e.target.closest('.fc-toolbar-title');
      if (!t) return;
      if (_agendaActive) return; // title reads "Agenda" — no date to drill
      if (_calPop && !_calPop.hidden) { closeDatePicker(); return; } // toggle
      openCalTitlePicker(t);
    });
  }

  // ── Browser reminder notifications ──────────────────────────────────────────
  // Foreground-only by design: while a WebCalDav tab is open and logged in, load
  // a future window of events, schedule timers, and fire a notification at each
  // event start and each reminder via the Service Worker (so the OS routes it to
  // the notification center). No Web Push / server push — that would require
  // plaintext reminder data on the server, breaking zero-knowledge at rest.

  const NOTIF_RESYNC_MS = 10 * 60 * 1000;     // re-poll cadence
  const NOTIF_MAX_TIMEOUT_MS = 2147483647;    // setTimeout ceiling (~24.8 days)
  let _notifSwReg = null;
  let _notifTimers = [];
  let _notifResync = null;
  let _notifEvents = null;                     // last-fetched future window
  let _notifCtags = null;                      // last-seen per-calendar tokens
  const _notifFired = loadFiredSet();          // tags already shown (dedupe)

  function loadFiredSet() {
    try {
      const raw = localStorage.getItem('webcaldav_notif_fired');
      return new Set(raw ? JSON.parse(raw) : []);
    } catch (_) { return new Set(); }
  }

  function persistFiredSet() {
    try {
      // Drop entries older than the horizon margin so the set can't grow forever.
      const cutoff = Date.now() - 2 * 24 * 60 * 60 * 1000;
      const kept = Array.from(_notifFired).filter((t) => {
        const ep = parseInt(t.slice(t.lastIndexOf(':') + 1), 10);
        return Number.isFinite(ep) && ep >= cutoff;
      });
      _notifFired.clear();
      kept.forEach((t) => _notifFired.add(t));
      localStorage.setItem('webcaldav_notif_fired', JSON.stringify(kept));
    } catch (_) {}
  }

  // Body datetime, in the user's date (+ time, for timed events) format.
  function notifDateTime(dt, allDay) {
    const dfmt = luxonDateFmt(dateFormatKey());
    if (allDay) return dt.toFormat(dfmt);
    const tfmt = timeFormatKey() === '12h' ? 'h:mm a' : 'HH:mm';
    return dt.toFormat(dfmt + ' ' + tfmt);
  }

  // Expand events into absolute notification triggers (event start + each
  // reminder). All triggers display the event's start datetime in the body.
  function buildTriggers(events) {
    const tz = effectiveTz();
    const now = Date.now();
    const out = [];
    (events || []).forEach((e) => {
      const p = e.extendedProps || {};
      if (p.calendarId == null) return;          // skip demo/non-calendar events
      const allDay = !!e.allDay;
      const startStr = p.rawStart || e.start;
      if (!startStr) return;
      const start = allDay
        ? luxon.DateTime.fromISO(String(startStr).slice(0, 10), { zone: tz })
        : luxon.DateTime.fromISO(startStr, { setZone: true }).setZone(tz);
      if (!start.isValid) return;
      const title = e.title || '(No title)';
      out.push({ uid: e.id, when: start, title, allDay, displayAt: start });
      (p.reminders || []).forEach((r) => {
        let when = null;
        if (r.readonly) {
          if (r.at) when = luxon.DateTime.fromISO(r.at, { setZone: true }).setZone(tz);
        } else if (allDay && r.time) {
          const [hh, mm] = r.time.split(':').map(Number);
          const days = r.value * (r.unit === 'weeks' ? 7 : 1);
          when = start.startOf('day').minus({ days }).plus({ hours: hh, minutes: mm });
        } else if (!allDay) {
          when = start.minus({ [r.unit]: r.value });
        }
        if (when && when.isValid) out.push({ uid: e.id, when, title, allDay, displayAt: start });
      });
    });
    return out.filter((t) => t.when.toMillis() > now);
  }

  function scheduleTriggers(events) {
    _notifTimers.forEach((id) => clearTimeout(id));
    _notifTimers = [];
    const now = Date.now();
    buildTriggers(events).forEach((t) => {
      const epoch = t.when.toMillis();
      const tag = t.uid + ':' + epoch;
      if (_notifFired.has(tag)) return;
      const delay = epoch - now;
      // Skip triggers beyond the setTimeout ceiling; a later resync schedules
      // them once they fall inside the window.
      if (delay <= 0 || delay > NOTIF_MAX_TIMEOUT_MS) return;
      _notifTimers.push(setTimeout(() => fireNotification(t, tag), delay));
    });
  }

  function fireNotification(t, tag) {
    if (_notifFired.has(tag)) return;
    _notifFired.add(tag);
    persistFiredSet();
    const opts = {
      body: t.title + '\n' + notifDateTime(t.displayAt, t.allDay),
      tag,
      icon: '/static/icon.png',
      badge: '/static/favicon-32x32.png',
    };
    try {
      if (_notifSwReg && _notifSwReg.showNotification) _notifSwReg.showNotification('WebCalDav', opts);
      else if ('Notification' in window) new Notification('WebCalDav', opts);
    } catch (_) {}
  }

  async function fetchNotifWindow() {
    const tz = effectiveTz();
    const now = luxon.DateTime.now().setZone(tz);
    const horizon = (window.__CONFIG__ || {}).notification_horizon_days || 60;
    const params = new URLSearchParams({ from: now.toISO(), to: now.plus({ days: horizon }).toISO() });
    const r = await fetch('/events?' + params.toString());
    if (!r.ok) throw new Error('events fetch failed');
    return await r.json();
  }

  // True if events should be refetched. Compares per-calendar change tokens;
  // any error (or first run) → refetch.
  async function notifCtagsChanged() {
    try {
      const r = await fetch('/calendars/ctags');
      if (!r.ok) return true;
      const tags = await r.json();
      const prev = _notifCtags;
      _notifCtags = tags;
      if (prev == null) return true;
      const keys = new Set([...Object.keys(prev), ...Object.keys(tags)]);
      for (const k of keys) { if (prev[k] !== tags[k]) return true; }
      return false;
    } catch (_) { return true; }
  }

  async function resyncNotifications(force) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try {
      // `force` (a local create/edit/delete) refetches without waiting on the
      // change-token check, which may lag a just-committed write. Still refresh
      // the stored token so the next polled resync compares against current.
      const changed = await notifCtagsChanged();
      if (force || changed || !_notifEvents) {
        _notifEvents = await fetchNotifWindow();
      }
      // Always reschedule so far-future triggers get a timer once in range.
      scheduleTriggers(_notifEvents || []);
    } catch (_) {}
  }

  async function startNotifications() {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
      try { await Notification.requestPermission(); } catch (_) {}
    }
    if (Notification.permission !== 'granted') return;
    try {
      if ('serviceWorker' in navigator) {
        const v = (window.__CONFIG__ || {}).static_v || '';
        _notifSwReg = await navigator.serviceWorker.register('/static/sw.js' + (v ? '?v=' + v : ''));
      }
    } catch (_) {}
    await resyncNotifications();
    if (_notifResync) clearInterval(_notifResync);
    _notifResync = setInterval(resyncNotifications, NOTIF_RESYNC_MS);
  }

  function stopNotifications() {
    if (_notifResync) { clearInterval(_notifResync); _notifResync = null; }
    _notifTimers.forEach((id) => clearTimeout(id));
    _notifTimers = [];
    _notifEvents = null;
    _notifCtags = null;
  }

  document.addEventListener('DOMContentLoaded', function () {
    const state = window.__STATE__;
    if (state === 'anonymous') initLogin();
    else if (state === 'restricted') initChangePassword();
    else if (state === 'authenticated') initCalendar();
  });
})();
