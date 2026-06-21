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

  // ── Share mode ──────────────────────────────────────────────────────────────
  // On the /s/<id> page app.js runs in "share mode": the same modals/renderers,
  // but data/CRUD calls are rerouted to /shares/* and carry the URL-fragment
  // secret in the X-Share-Secret header (never the request line). The sealed
  // share window/scope is authoritative server-side. SHARE_CFG is filled by
  // resolveShare() before the calendar is built.
  const SHARE_MODE = !!window.__SHARE_MODE__;
  const SHARE_ID = window.__SHARE_ID__;
  let SHARE_SECRET = '';
  let SHARE_CFG = null;
  if (SHARE_MODE) {
    SHARE_SECRET = (window.location.hash || '').replace(/^#/, '');
    try { history.replaceState(null, '', window.location.pathname); } catch (e) {}
  }

  // Reroute the data/CRUD endpoints to their /shares/* equivalents in share mode.
  function apiPath(path) {
    if (!SHARE_MODE) return path;
    return path.replace(/^\/(events|tasks|journals)\b/, '/shares/$1');
  }

  async function resolveShare() {
    const r = await fetch('/shares/resolve', {
      method: 'POST', headers: apiHeaders({ 'Content-Type': 'application/json' }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    SHARE_CFG = await r.json();
    return SHARE_CFG;
  }

  async function fetchShareItems() {
    const r = await fetch('/shares/items', { headers: apiHeaders() });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json(); // { events, tasks, journals }
  }

  async function downloadShareIcs() {
    try {
      const r = await fetch(`/shares/${SHARE_ID}/export.ics`, { headers: apiHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `share-${SHARE_ID}.ics`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { alert(e.message); }
  }

  function apiHeaders(base) {
    const h = Object.assign({ 'X-Requested-With': 'fetch' }, base || {});
    if (SHARE_MODE && SHARE_SECRET) h['X-Share-Secret'] = SHARE_SECRET;
    return h;
  }

  async function apiPost(path, body) {
    const r = await fetch(apiPath(path), {
      method: 'POST',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errMsg(data.detail) || `HTTP ${r.status}`);
    return data;
  }

  async function apiPatch(path, body) {
    const r = await fetch(apiPath(path), {
      method: 'PATCH',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errMsg(data.detail) || `HTTP ${r.status}`);
    return data;
  }

  async function apiDelete(path) {
    const r = await fetch(apiPath(path), { method: 'DELETE', headers: apiHeaders() });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new Error(errMsg(data.detail) || `HTTP ${r.status}`);
    }
  }

  async function apiGet(path) {
    const r = await fetch(apiPath(path), { headers: apiHeaders() });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errMsg(data.detail) || `HTTP ${r.status}`);
    return data;
  }

  async function apiPut(path, body) {
    const r = await fetch(apiPath(path), {
      method: 'PUT',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errMsg(data.detail) || `HTTP ${r.status}`);
    return data;
  }

  // ── i18n ──────────────────────────────────────────────────────────────────
  // Catalog + effective language code are injected by the server (see index.html).
  // Note: the translate helper is named `tr` because `t` is used elsewhere for
  // task objects.
  const I18N = window.__I18N__ || {};
  const LANG = window.__LANG__ || 'en';

  // Dot-path lookup ("ui.modal_save") with {placeholder} interpolation. Returns
  // the key itself when missing, so untranslated strings are visible, not blank.
  function tr(key, params) {
    let node = I18N;
    for (const part of String(key).split('.')) {
      node = node && typeof node === 'object' ? node[part] : undefined;
    }
    let str = typeof node === 'string' ? node : key;
    if (params) {
      str = str.replace(/\{(\w+)\}/g, (m, name) =>
        params[name] != null ? String(params[name]) : m);
    }
    return str;
  }

  // Plural form select. English: 1 vs other. Czech: 1 / 2–4 / 5+.
  function pluralIndex(n) {
    if (LANG === 'cs') {
      if (n === 1) return 0;
      if (n >= 2 && n <= 4) return 1;
      return 2;
    }
    return n === 1 ? 0 : 1;
  }

  // Localized unit noun ("minutes" → "minut") agreeing with count n.
  function unitWord(unit, n) {
    const forms = (I18N.units && I18N.units[unit]) || [unit];
    return forms[Math.min(pluralIndex(n), forms.length - 1)] || forms[0];
  }

  // Map a server-returned error detail to its translation, leaving unknown
  // (e.g. validation array or interpolated) details untouched.
  function errMsg(detail) {
    if (typeof detail !== 'string') return detail;
    return (I18N.errors && I18N.errors[detail]) || detail;
  }

  // Fill DOM text/attributes tagged with data-i18n* from the catalog. Run once
  // on load; the in-markup English text stays as a fallback for missing keys.
  function applyTranslations(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach((el) => {
      el.textContent = tr(el.getAttribute('data-i18n'));
    });
    scope.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      el.setAttribute('placeholder', tr(el.getAttribute('data-i18n-placeholder')));
    });
    scope.querySelectorAll('[data-i18n-title]').forEach((el) => {
      el.setAttribute('title', tr(el.getAttribute('data-i18n-title')));
    });
    scope.querySelectorAll('[data-i18n-aria-label]').forEach((el) => {
      el.setAttribute('aria-label', tr(el.getAttribute('data-i18n-aria-label')));
    });
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
  // Double-click-to-create state: last date-cell click (for manual dblclick
  // detection) and a guard so the highlight-only single click doesn't trip the
  // `select` handler into opening the create modal.
  let _lastDateClick = null;
  let _suppressSelectModal = false;
  const DBLCLICK_MS = 350;

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
    closeTokenModal();
    hide('settings-overlay');
    hide('settings-panel');
    // Calendars may have changed; drop the create-modal picker cache.
    _calendarsCache = null;
    refreshViews();
  }

  async function loadSettings() {
    await Promise.all([loadAccounts(), loadCalendars(), loadPrefs(), loadTokens(), loadShares()]);
  }

  const MCP_ENABLED = !!window.__MCP_ENABLED__;
  const SHARING_ENABLED = window.__SHARING_ENABLED__ !== false;

  // ── Sharing ─────────────────────────────────────────────────────────────────
  // A share's secret rides in the URL fragment only. Creating one seals the
  // session DEK + scope server-side (see routers/shares.py); the link is shown
  // once. _shareDraft holds the pending spec while the modal is open.
  let _shareDraft = null;

  function shareExpiryISO() {
    const v = document.getElementById('share-expiry').value;
    if (v === 'never') return null;
    return luxon.DateTime.now().plus({ days: parseInt(v, 10) }).toISO();
  }

  async function renderShareCalPicker(selectedIds) {
    const picker = document.getElementById('share-cal-picker');
    picker.innerHTML = '';
    const rw = document.getElementById('share-mode').value === 'rw';
    let cals = [];
    try { cals = await apiGet('/calendars'); } catch (_) {}
    cals.forEach((c, i) => {
      const checked = !selectedIds || selectedIds.includes(c.id);
      const row = document.createElement('div');
      row.className = 'share-cal-row';
      row.innerHTML =
        `<label class="ev-check"><input type="checkbox" class="share-cal" value="${c.id}"${checked ? ' checked' : ''}> ` +
        `<span>${escHtml(c.display_name)}</span></label>` +
        `<label class="ev-check share-cal-w"><input type="checkbox" class="share-cal-writable" value="${c.id}"> ` +
        `<span data-i18n="ui.share_writable">writable</span></label>` +
        `<label class="ev-check share-cal-d"><input type="radio" name="share-default" class="share-cal-default" value="${c.id}"> ` +
        `<span data-i18n="ui.share_default">default</span></label>`;
      picker.appendChild(row);
    });
    applyTranslations(picker);
    picker.classList.toggle('share-ro', !rw);
  }

  function collectShareCalendars() {
    const rw = document.getElementById('share-mode').value === 'rw';
    const writableIds = new Set(
      Array.from(document.querySelectorAll('.share-cal-writable'))
        .filter((c) => c.checked).map((c) => parseInt(c.value, 10)),
    );
    const def = document.querySelector('.share-cal-default:checked');
    const calendars = Array.from(document.querySelectorAll('.share-cal'))
      .filter((c) => c.checked)
      .map((c) => {
        const id = parseInt(c.value, 10);
        return { id, writable: rw && writableIds.has(id) };
      });
    const defaultId = rw && def ? parseInt(def.value, 10) : null;
    return { calendars, defaultId };
  }

  function openItemShare() {
    if (!SHARING_ENABLED || !_currentEvent || _currentEvent.calendarId == null
        || _currentEvent.isNew) return;
    const kind = _currentEvent.isJournal ? 'journal' : (_currentEvent.isTask ? 'task' : 'event');
    _shareDraft = {
      kind: 'item',
      item: { uid: _currentEvent.id, item_kind: kind, calendar_id: _currentEvent.calendarId },
    };
    document.getElementById('share-scope-desc').textContent = tr('dyn.share_item_desc');
    document.getElementById('share-agenda-range').style.display = 'none';
    document.getElementById('share-cal-scope').style.display = 'none';
    openShareModal();
  }

  async function openGridShare() {
    if (!SHARING_ENABLED || !_fcCalendar) return;
    const view = _fcCalendar.view.type;
    const anchor = luxon.DateTime.fromJSDate(_fcCalendar.getDate())
      .setZone(effectiveTz()).toISODate();
    _shareDraft = { kind: 'grid', grid: { grid_view: view, grid_anchor: anchor } };
    document.getElementById('share-scope-desc').textContent =
      tr('dyn.share_grid_desc', { view: tr('ui.view_' + ({
        dayGridMonth: 'month', timeGridWeek: 'week', timeGridDay: 'day',
      }[view] || 'month')) });
    document.getElementById('share-agenda-range').style.display = 'none';
    document.getElementById('share-cal-scope').style.display = '';
    await renderShareCalPicker(null);
    openShareModal();
  }

  async function openAgendaShare() {
    if (!SHARING_ENABLED) return;
    const tz = effectiveTz();
    // Default range from the currently rendered agenda rows.
    const span = agendaVisibleSpan();
    _shareDraft = { kind: 'agenda' };
    document.getElementById('share-scope-desc').textContent = tr('dyn.share_agenda_desc');
    document.getElementById('share-agenda-range').style.display = '';
    document.getElementById('share-cal-scope').style.display = '';
    renderDateFields('share-from', () => {});
    renderDateFields('share-to', () => {});
    renderTimeFields('share-from', () => {});
    renderTimeFields('share-to', () => {});
    const from = span.from || luxon.DateTime.now().setZone(tz).startOf('day');
    const to = span.to || from.plus({ days: 7 });
    setDateFieldValue('share-from', from.toISODate());
    setTimeParts('share-from', from.hour, from.minute);
    setDateFieldValue('share-to', to.toISODate());
    setTimeParts('share-to', to.hour, to.minute);
    document.getElementById('share-cal-scope').style.display = '';
    await renderShareCalPicker(null);
    openShareModal();
  }

  function agendaVisibleSpan() {
    const tz = effectiveTz();
    const rows = document.querySelectorAll('#agenda-list [data-start]');
    let from = null, to = null;
    rows.forEach((r) => {
      const s = luxon.DateTime.fromISO(r.getAttribute('data-start'), { setZone: true }).setZone(tz);
      if (!from || s < from) from = s;
      if (!to || s > to) to = s;
    });
    return { from, to: to ? to.plus({ days: 1 }) : null };
  }

  function openShareModal() {
    hideError('share-error');
    document.getElementById('share-mode').value = 'ro';
    document.getElementById('share-expiry').value = '30';
    show('share-overlay');
    show('share-modal');
  }

  function closeShareModal() {
    hide('share-modal');
    hide('share-overlay');
    _shareDraft = null;
  }

  async function submitShare() {
    if (!_shareDraft) return;
    hideError('share-error');
    const btn = document.getElementById('btn-share-create');
    btn.disabled = true;
    try {
      const body = {
        kind: _shareDraft.kind,
        mode: document.getElementById('share-mode').value,
        expires_at: shareExpiryISO(),
      };
      if (_shareDraft.kind === 'item') {
        body.item = _shareDraft.item;
      } else if (_shareDraft.kind === 'grid') {
        body.grid = _shareDraft.grid;
        const sc = collectShareCalendars();
        body.calendars = sc.calendars;
        body.default_calendar_id = sc.defaultId;
      } else {
        const tz = effectiveTz();
        const f = getDateFieldValue('share-from');
        const t = getDateFieldValue('share-to');
        const ft = getTimeParts('share-from');
        const tt = getTimeParts('share-to');
        body.agenda = {
          agenda_from: luxon.DateTime.fromObject(
            { year: +f.slice(0, 4), month: +f.slice(5, 7), day: +f.slice(8, 10),
              hour: ft.h24, minute: ft.m }, { zone: tz }).toISO(),
          agenda_to: luxon.DateTime.fromObject(
            { year: +t.slice(0, 4), month: +t.slice(5, 7), day: +t.slice(8, 10),
              hour: tt.h24, minute: tt.m }, { zone: tz }).toISO(),
        };
        const sc = collectShareCalendars();
        body.calendars = sc.calendars;
        body.default_calendar_id = sc.defaultId;
      }
      if ((_shareDraft.kind === 'grid' || _shareDraft.kind === 'agenda')
          && (!body.calendars || body.calendars.length === 0)) {
        throw new Error(tr('dyn.share_need_calendar'));
      }
      const res = await apiPost('/shares', body);
      closeShareModal();
      showShareResult(res.url, res.info.id);
    } catch (err) {
      showError('share-error', err.message);
    } finally {
      btn.disabled = false;
    }
  }

  function showShareResult(url, shareId) {
    document.getElementById('shareres-url').value = url;
    const dl = document.getElementById('shareres-download');
    dl.style.display = '';
    // The export endpoint is share-secret authed; the secret is in the URL
    // fragment. Fetch with the X-Share-Secret header and download the blob so the
    // secret never enters the request line.
    dl.onclick = async (e) => {
      e.preventDefault();
      const secret = url.split('#', 2)[1] || '';
      try {
        const r = await fetch(`/shares/${shareId}/export.ics`, {
          headers: { 'X-Share-Secret': secret },
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `share-${shareId}.ics`;
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (err) {
        alert(err.message);
      }
    };
    show('shareres-overlay');
    show('shareres-modal');
  }

  function closeShareResult() {
    document.getElementById('shareres-url').value = '';
    hide('shareres-modal');
    hide('shareres-overlay');
  }

  async function loadShares() {
    const list = document.getElementById('shares-list');
    const note = document.getElementById('shares-disabled-note');
    if (note) note.style.display = SHARING_ENABLED ? 'none' : '';
    if (!list) return;
    list.innerHTML = `<p class="loading">${escHtml(tr('dyn.loading'))}</p>`;
    try {
      const shares = await apiGet('/shares');
      if (shares.length === 0) {
        list.innerHTML = `<p class="empty-note">${escHtml(tr('dyn.no_shares'))}</p>`;
        return;
      }
      list.innerHTML = '';
      shares.forEach((s) => {
        const modeLabel = s.mode === 'rw' ? tr('ui.share_rw') : tr('ui.share_ro');
        const kindLabel = tr('dyn.share_kind_' + s.kind);
        const expires = s.expires_at
          ? tr('dyn.token_expires', {
              date: luxon.DateTime.fromISO(s.expires_at).toFormat(luxonDateFmt(dateFormatKey())),
            })
          : tr('dyn.token_no_expiry');
        const row = document.createElement('div');
        row.className = 'token-row';
        row.innerHTML =
          `<div class="token-meta">` +
            `<span class="token-name">${escHtml(s.name)}</span>` +
            `<span class="token-badge token-${s.mode}">${escHtml(modeLabel)}</span>` +
            `<span class="token-sub">${escHtml(kindLabel)} · ${escHtml(expires)}</span>` +
          `</div>` +
          `<button class="btn-danger-sm" data-id="${s.id}">${escHtml(tr('dyn.revoke'))}</button>`;
        row.querySelector('button').addEventListener('click', async () => {
          if (!confirm(tr('dyn.revoke_share', { name: s.name }))) return;
          try { await apiDelete(`/shares/${s.id}`); await loadShares(); }
          catch (err) { alert(err.message); }
        });
        list.appendChild(row);
      });
    } catch (err) {
      list.innerHTML = `<p class="error-note">${escHtml(err.message)}</p>`;
    }
  }

  function initShareUI() {
    const btnItem = document.getElementById('btn-event-share');
    if (btnItem) btnItem.addEventListener('click', openItemShare);
    document.getElementById('btn-share-close').addEventListener('click', closeShareModal);
    document.getElementById('btn-share-cancel').addEventListener('click', closeShareModal);
    document.getElementById('share-overlay').addEventListener('click', closeShareModal);
    document.getElementById('btn-share-create').addEventListener('click', submitShare);
    document.getElementById('share-mode').addEventListener('change', () => {
      if (document.getElementById('share-cal-scope').style.display !== 'none') {
        const sel = Array.from(document.querySelectorAll('.share-cal'))
          .filter((c) => c.checked).map((c) => parseInt(c.value, 10));
        renderShareCalPicker(sel);
      }
    });
    document.getElementById('shareres-copy').addEventListener('click', async () => {
      const u = document.getElementById('shareres-url');
      try { await navigator.clipboard.writeText(u.value); }
      catch (_) { u.select(); document.execCommand('copy'); }
    });
    document.getElementById('shareres-close').addEventListener('click', closeShareResult);
    document.getElementById('shareres-overlay').addEventListener('click', closeShareResult);
  }

  async function loadTokens() {
    const list = document.getElementById('tokens-list');
    // Reflect the server toggle: disable creation, keep revoke working.
    const disabledNote = document.getElementById('tokens-disabled-note');
    const addDetails = document.getElementById('add-token-details');
    if (disabledNote) disabledNote.style.display = MCP_ENABLED ? 'none' : '';
    if (addDetails) addDetails.style.display = MCP_ENABLED ? '' : 'none';
    // (Re)build the expiry date field each open so a date_format change (no
    // reload) and the localized mini picker take effect. Reuses the event/task
    // custom date field + mini calendar.
    renderDateFields('token-expires', () => {});
    list.innerHTML = `<p class="loading">${escHtml(tr('dyn.loading'))}</p>`;
    try {
      const tokens = await apiGet('/api-tokens');
      if (tokens.length === 0) {
        list.innerHTML = `<p class="empty-note">${escHtml(tr('dyn.no_tokens'))}</p>`;
        return;
      }
      list.innerHTML = '';
      tokens.forEach((t) => {
        const modeLabel = t.mode === 'rw' ? tr('ui.tokens_rw') : tr('ui.tokens_ro');
        const scope = t.all_calendars
          ? tr('dyn.token_all_calendars')
          : tr('dyn.token_scoped', { n: t.calendar_ids.length });
        const expires = t.expires_at
          ? tr('dyn.token_expires', {
              date: luxon.DateTime.fromISO(t.expires_at).toFormat(
                luxonDateFmt(dateFormatKey())),
            })
          : tr('dyn.token_no_expiry');
        const row = document.createElement('div');
        row.className = 'token-row';
        row.innerHTML =
          `<div class="token-meta">` +
            `<span class="token-name">${escHtml(t.name)}</span>` +
            `<span class="token-badge token-${t.mode}">${escHtml(modeLabel)}</span>` +
            `<span class="token-sub">${escHtml(scope)} · ${escHtml(expires)}</span>` +
          `</div>` +
          `<button class="btn-danger-sm" data-id="${t.id}">${escHtml(tr('dyn.revoke'))}</button>`;
        row.querySelector('button').addEventListener('click', async () => {
          if (!confirm(tr('dyn.revoke_token', { name: t.name }))) return;
          try {
            await apiDelete(`/api-tokens/${t.id}`);
            await loadTokens();
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

  async function renderTokenCalendarPicker() {
    const picker = document.getElementById('token-cal-picker');
    picker.innerHTML = '';
    try {
      const cals = await apiGet('/calendars');
      cals.forEach((c) => {
        const label = document.createElement('label');
        label.className = 'ev-check';
        label.innerHTML =
          `<input type="checkbox" class="token-cal" value="${c.id}">` +
          ` <span>${escHtml(c.display_name)}</span>`;
        picker.appendChild(label);
      });
    } catch (_) {}
  }

  // Show the freshly minted token once, in a modal. The plaintext lives only in
  // the input's value while the modal is open; closing it wipes the value so the
  // secret is not recoverable from the DOM afterwards.
  function openTokenModal(secret) {
    document.getElementById('token-secret').value = secret;
    show('token-overlay');
    show('token-modal');
  }

  function closeTokenModal() {
    const input = document.getElementById('token-secret');
    if (input) input.value = '';
    hide('token-modal');
    hide('token-overlay');
  }

  function initTokenForm() {
    const form = document.getElementById('add-token-form');
    if (!form) return;
    const allCals = document.getElementById('token-all-cals');
    const picker = document.getElementById('token-cal-picker');
    allCals.addEventListener('change', async () => {
      if (allCals.checked) {
        picker.style.display = 'none';
      } else {
        await renderTokenCalendarPicker();
        picker.style.display = '';
      }
    });

    document.getElementById('token-copy').addEventListener('click', async () => {
      const secret = document.getElementById('token-secret');
      try {
        await navigator.clipboard.writeText(secret.value);
      } catch (_) {
        secret.select();
        document.execCommand('copy');
      }
    });
    document.getElementById('token-modal-close').addEventListener('click', closeTokenModal);
    document.getElementById('token-overlay').addEventListener('click', closeTokenModal);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError('add-token-error');
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      try {
        const all = allCals.checked;
        const calendar_ids = all
          ? null
          : Array.from(document.querySelectorAll('.token-cal:checked')).map((el) =>
              parseInt(el.value, 10));
        const expRaw = getDateFieldValue('token-expires'); // canonical yyyy-MM-dd or ''
        const body = {
          name: document.getElementById('token-name').value.trim(),
          mode: document.getElementById('token-mode').value,
          all_calendars: all,
          calendar_ids,
          expires_at: expRaw ? `${expRaw}T23:59:59` : null,
        };
        const res = await apiPost('/api-tokens', body);
        form.reset();
        setDateFieldValue('token-expires', '');
        allCals.checked = true;
        picker.style.display = 'none';
        document.getElementById('add-token-details').open = false;
        await loadTokens();
        openTokenModal(res.token);
      } catch (err) {
        showError('add-token-error', err.message);
      } finally {
        btn.disabled = false;
      }
    });
  }

  async function loadAccounts() {
    const list = document.getElementById('accounts-list');
    list.innerHTML = `<p class="loading">${escHtml(tr('dyn.loading'))}</p>`;
    try {
      const accounts = await apiGet('/caldav-accounts');
      if (accounts.length === 0) {
        list.innerHTML = `<p class="empty-note">${escHtml(tr('dyn.no_accounts'))}</p>`;
        return;
      }
      list.innerHTML = '';
      accounts.forEach((a) => {
        const row = document.createElement('div');
        row.className = 'account-row';
        row.innerHTML =
          `<span class="account-url" title="${escHtml(a.url)}">${escHtml(a.username)} — ${escHtml(a.url)}</span>` +
          `<button class="btn-danger-sm" data-id="${a.id}">${escHtml(tr('dyn.remove'))}</button>`;
        row.querySelector('button').addEventListener('click', async () => {
          if (!confirm(tr('dyn.remove_account', { url: a.url }))) return;
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
    list.innerHTML = `<p class="loading">${escHtml(tr('dyn.loading'))}</p>`;
    try {
      const cals = await apiGet('/calendars');
      if (cals.length === 0) {
        list.innerHTML = `<p class="empty-note">${escHtml(tr('dyn.no_calendars'))}</p>`;
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
          `<label class="cal-default-label" title="${escHtml(tr('dyn.default_calendar_title'))}">` +
            `<input type="checkbox" class="cal-default" data-id="${c.id}"${c.is_default ? ' checked' : ''}>` +
            ` ${escHtml(tr('dyn.default'))}` +
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
      document.getElementById('pref-completed-task').value = s.completed_task_display || 'hidden';
      document.getElementById('pref-undated-task').value = s.undated_task_display || 'agenda';
      document.getElementById('pref-theme').value = s.theme || 'system';
      document.getElementById('pref-language').value = s.language || 'autodetect';
      document.getElementById('pref-dblclick-create').checked = !!s.double_click_to_create_events;
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
    initTokenForm();

    // Add account form
    const addForm = document.getElementById('add-account-form');
    addForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError('add-account-error');
      const btn = addForm.querySelector('button');
      btn.disabled = true;
      btn.textContent = tr('dyn.connecting');
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
        btn.textContent = tr('dyn.connect');
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
          alert(tr('dyn.notif_unsupported'));
          return;
        }
        let perm = Notification.permission;
        if (perm !== 'granted') {
          try { perm = await Notification.requestPermission(); } catch (_) { perm = 'denied'; }
        }
        if (perm !== 'granted') {
          notifEnabledEl.checked = false;
          alert(tr('dyn.notif_blocked_try'));
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
        alert(tr('dyn.notif_unsupported'));
        return;
      }
      let perm = Notification.permission;
      if (perm !== 'granted') {
        try { perm = await Notification.requestPermission(); } catch (_) { perm = 'denied'; }
      }
      if (perm === 'granted') {
        if ((window.__SETTINGS__ || {}).notifications_enabled) startNotifications();
        alert(tr('dyn.notif_enabled'));
      } else {
        alert(tr('dyn.notif_blocked'));
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
        const completedTask = document.getElementById('pref-completed-task').value;
        const undatedTask = document.getElementById('pref-undated-task').value;
        const theme = document.getElementById('pref-theme').value;
        const language = document.getElementById('pref-language').value;
        const dblClickCreate = document.getElementById('pref-dblclick-create').checked;
        const languageChanged = language !== (window.__SETTINGS__?.language ?? 'autodetect');
        const notifEnabled = document.getElementById('pref-notifications-enabled').checked;
        // Notifications force auto-logout off (server enforces the same).
        const autoEnabled = notifEnabled ? false : document.getElementById('pref-auto-logout-enabled').checked;
        const autoMin = parseInt(document.getElementById('pref-auto-logout-min').value, 10);
        if (autoEnabled && (!Number.isFinite(autoMin) || autoMin < 1)) {
          throw new Error(tr('dyn.logout_min'));
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
          completed_task_display: completedTask,
          undated_task_display: undatedTask,
          theme: theme,
          language: language,
          double_click_to_create_events: dblClickCreate,
        });
        // The active translation catalog is injected at page render, so a
        // language change only takes full effect after a reload.
        if (languageChanged) { window.location.reload(); return; }
        window.__SETTINGS__ = window.__SETTINGS__ || {};
        window.__SETTINGS__.timezone = tz;
        window.__SETTINGS__.first_day_of_week = fdow;
        window.__SETTINGS__.time_format = timefmt;
        window.__SETTINGS__.date_format = datefmt;
        window.__SETTINGS__.default_view = defaultView;
        window.__SETTINGS__.auto_logout_enabled = autoEnabled;
        window.__SETTINGS__.auto_logout_timeout_seconds = autoSecs;
        window.__SETTINGS__.notifications_enabled = notifEnabled;
        window.__SETTINGS__.completed_task_display = completedTask;
        window.__SETTINGS__.undated_task_display = undatedTask;
        window.__SETTINGS__.theme = theme;
        window.__SETTINGS__.language = language;
        window.__SETTINGS__.double_click_to_create_events = dblClickCreate;
        // Apply theme live; "system" tracked by CSS media query (no JS needed).
        document.documentElement.dataset.theme = theme;
        if (notifEnabled) startNotifications(); else stopNotifications();
        applyCalendarPrefs(tz, fdow, timefmt, datefmt);
        // Live session timeout changed server-side; resync the countdown.
        refreshLogoutCountdown();
        msg.textContent = tr('dyn.saved');
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

  // ── Event / Task type toggle ─────────────────────────────────────────────────

  // The modal serves three kinds: 'event', 'task', 'journal' (the #ev-type value).
  function modalKind() {
    return document.getElementById('ev-type').value;
  }
  function modalIsTask() {
    return modalKind() === 'task';
  }
  function modalIsJournal() {
    return modalKind() === 'journal';
  }

  // The journal body uses a two-tab editor: an "Edit" tab (a plain textarea of raw
  // Markdown) and a read-only "Display" tab that renders the Markdown. The body is
  // stored in the textarea; the display pane is re-rendered on each switch to it.
  // Images are disabled and raw HTML escaped, so rendering via innerHTML is safe
  // (CalDAV can't store images anyway).
  let _journalMd = null;
  function journalRenderer() {
    if (_journalMd) return _journalMd;
    if (!window.markdownit) return null;
    const hl = window.hljs;
    const md = window.markdownit({
      html: false,
      linkify: true,
      breaks: true,
      // Syntax-highlight fenced code via highlight.js (the language hint when
      // valid, else auto-detect); fall back to escaped plain text.
      highlight: function (str, lang) {
        const esc = (s) => _journalMd.utils.escapeHtml(s);
        if (hl) {
          try {
            const out = lang && hl.getLanguage(lang)
              ? hl.highlight(str, { language: lang, ignoreIllegals: true })
              : hl.highlightAuto(str);
            return '<pre class="hljs"><code>' + out.value + '</code></pre>';
          } catch (_) { /* fall through */ }
        }
        return '<pre class="hljs"><code>' + esc(str) + '</code></pre>';
      },
    });
    md.disable('image');

    // Generic custom containers: `::: name` … `:::` → <div class="md-container
    // md-<name>">. validate→true accepts any name (defaults to "note").
    if (window.markdownitContainer) {
      md.use(window.markdownitContainer, 'generic', {
        validate: function () { return true; },
        render: function (tokens, idx) {
          if (tokens[idx].nesting !== 1) return '</div>\n';
          const name = (tokens[idx].info.trim().split(/\s+/)[0] || 'note');
          return '<div class="md-container md-' + md.utils.escapeHtml(name) + '">\n';
        },
      });
    }
    // Remaining plugins (each guarded — a missing vendor file just disables it).
    [
      window.markdownitFootnote,
      window.markdownitDeflist,
      window.markdownitSub,
      window.markdownitSup,
      window.markdownitMark,
      window.markdownitTaskLists,
    ].forEach((p) => { if (p) md.use(p); });

    _journalMd = md;
    return _journalMd;
  }
  function renderJournalDisplay() {
    const el = document.getElementById('ev-journal-display');
    const src = document.getElementById('ev-journal-edit').value || '';
    const md = journalRenderer();
    el.innerHTML = md ? md.render(src) : escHtml(src);
  }
  function setJournalTab(tab) {
    const edit = tab !== 'display';
    document.getElementById('ev-journal-edit').style.display = edit ? '' : 'none';
    document.getElementById('ev-journal-display').style.display = edit ? 'none' : '';
    document.getElementById('ev-journal-tab-edit').classList.toggle('active', edit);
    document.getElementById('ev-journal-tab-display').classList.toggle('active', !edit);
    if (!edit) renderJournalDisplay();
  }
  function setJournalBody(md) {
    document.getElementById('ev-journal-edit').value = md || '';
  }
  function getJournalBody() {
    return document.getElementById('ev-journal-edit').value;
  }

  // Point the shared modal at one kind ('event' | 'task' | 'journal'). `locked`
  // disables the switch (existing items can't change kind).
  function setModalType(kind, locked) {
    const sel = document.getElementById('ev-type');
    sel.value = kind;
    sel.disabled = !!locked;
    applyTypeToggle();
  }

  function applyTypeToggle() {
    const kind = modalKind();
    const isTask = kind === 'task';
    const isJournal = kind === 'journal';
    document.getElementById('ev-duration-legend').textContent =
      isJournal ? tr('dyn.date') : (isTask ? tr('dyn.schedule') : tr('dyn.duration'));
    document.getElementById('ev-from-label').textContent =
      isJournal ? tr('dyn.date') : (isTask ? tr('dyn.start') : tr('dyn.from'));
    document.getElementById('ev-to-label').textContent = isTask ? tr('dyn.due') : tr('dyn.to');
    // Journals anchor on a single date; hide the "To" row entirely.
    document.getElementById('ev-to-row').style.display = isJournal ? 'none' : '';
    document.getElementById('ev-priority-field').style.display = isTask ? '' : 'none';
    document.getElementById('ev-undated-hint').style.display = isTask ? '' : 'none';
    const isNew = _currentEvent && _currentEvent.isNew;
    document.getElementById('ev-done-field').style.display = isTask && !isNew ? '' : 'none';
    // Journals carry no recurrence, reminders or location; they swap the plain
    // notes textarea for the Markdown body editor.
    document.getElementById('ev-repeat-fieldset').style.display = isJournal ? 'none' : '';
    document.getElementById('ev-location-field').style.display = isJournal ? 'none' : '';
    document.getElementById('ev-reminders-field').style.display = isJournal ? 'none' : '';
    document.getElementById('ev-notes-field').style.display = isJournal ? 'none' : '';
    document.getElementById('ev-journal-field').style.display = isJournal ? '' : 'none';
    // New journals default to all-day (a diary entry is a date, not a time);
    // existing items keep their stored all-day flag.
    if (isJournal && _currentEvent && _currentEvent.isNew) {
      document.getElementById('ev-allday').checked = true;
      applyAllDayToggle();
    }
    if (_currentEvent && _currentEvent.isNew) {
      _currentEvent.isTask = isTask;
      _currentEvent.isJournal = isJournal;
      document.getElementById('ev-title-text').textContent =
        isJournal ? tr('dyn.new_journal') : (isTask ? tr('dyn.new_task') : tr('dyn.new_event'));
    }
    // Relabel reminder anchors (before/after due vs end) for the new type.
    renderReminders();
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
  // True while the event modal is in read-only mode (demo event, or a read-only
  // share). Recurrence UI consults it so it won't re-enable its own fields.
  let _editLocked = false;

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
    const isTask = modalIsTask();
    const dir = r.direction === 'after' ? 'after' : 'before';
    const anchorWord = r.anchor === 'end' ? (isTask ? 'due' : 'end') : 'start';
    const relwhen = tr(`dyn.relwhen_${dir}_${anchorWord}`);
    if (r.time != null) {
      const at = reminderTimeText(r.time);
      if (r.value === 0) {
        return tr('dyn.rem_on_day_at', { anchorDay: tr(`dyn.rem_anchor_day_${anchorWord}`), time: at });
      }
      return tr('dyn.rem_n_at', { n: r.value, unit: unitWord(r.unit, r.value), relwhen, time: at });
    }
    if (r.value === 0) {
      return tr('dyn.rem_at_of', {
        atof: tr(`dyn.rem_atof_${anchorWord}`),
        kind: tr(isTask ? 'dyn.kind_task_gen' : 'dyn.kind_event_gen'),
      });
    }
    return tr('dyn.rem_n', { n: r.value, unit: unitWord(r.unit, r.value), relwhen });
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
      `<span class="ev-reminder-word">${escHtml(tr('dyn.rem_at_word'))}</span>` +
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
    if (!dt.isValid) return tr('dyn.at_iso', { value: iso });
    const timeFmt = timeFormatKey() === '12h' ? 'h:mm a' : 'HH:mm';
    return tr('dyn.at_iso', { value: dt.toFormat(`${luxonDateFmt(dateFormatKey())} ${timeFmt}`) });
  }

  // Split the server's extendedProps.reminders into editable and read-only rows.
  function resetReminders(list) {
    _reminders = [];
    _remindersReadonly = [];
    (list || []).forEach((r) => {
      if (!r || typeof r !== 'object') return;
      if (r.readonly) {
        _remindersReadonly.push(r.at ? readonlyReminderAtText(r.at) : (r.text || tr('dyn.reminder')));
      } else if (r.unit) {
        _reminders.push({
          value: r.value,
          unit: r.unit,
          time: r.time,
          anchor: r.anchor === 'end' ? 'end' : 'start',
          direction: r.direction === 'after' ? 'after' : 'before',
        });
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
        ? `<button type="button" class="btn-icon ev-reminder-del" data-idx="${i}" aria-label="${escHtml(tr('dyn.delete_reminder'))}">×</button>`
        : '';
      rows.push(
        `<div class="ev-reminder-row"><span class="ev-reminder">${escHtml(reminderText(r))}</span>${del}</div>`
      );
    });
    fresh.forEach((r, i) => {
      const idx = committed.length + i;
      const units = allDay ? ['days', 'weeks'] : ['minutes', 'hours', 'days', 'weeks'];
      const opts = units
        .map((u) => `<option value="${u}"${u === r.unit ? ' selected' : ''}>${escHtml(unitWord(u, 5))}</option>`)
        .join('');
      const time = allDay ? reminderTimeHtml(idx, r.time) : '';
      const sel = `${r.direction === 'after' ? 'after' : 'before'}|${r.anchor === 'end' ? 'end' : 'start'}`;
      const endW = modalIsTask() ? 'due' : 'end';
      const anchorOpts = [
        ['before|start', tr('dyn.relwhen_before_start')],
        ['after|start', tr('dyn.relwhen_after_start')],
        ['before|end', tr(`dyn.relwhen_before_${endW}`)],
        ['after|end', tr(`dyn.relwhen_after_${endW}`)],
      ].map(([v, label]) => `<option value="${v}"${v === sel ? ' selected' : ''}>${escHtml(label)}</option>`).join('');
      rows.push(
        `<div class="ev-reminder-row">` +
          `<input type="number" class="ev-reminder-value" data-idx="${idx}" min="0" max="10000" value="${escHtml(r.value)}">` +
          `<select class="ev-reminder-unit" data-idx="${idx}">${opts}</select>` +
          `<select class="ev-reminder-anchor" data-idx="${idx}">${anchorOpts}</select>${time}` +
          `<button type="button" class="btn-icon ev-reminder-del" data-idx="${idx}" aria-label="${escHtml(tr('dyn.delete_reminder'))}">×</button>` +
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
      : `<div class="ev-reminder empty-note">${escHtml(tr('dyn.none'))}</div>`;

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
    box.querySelectorAll('.ev-reminder-anchor').forEach((sel) => {
      sel.addEventListener('change', () => {
        const r = _reminders[parseInt(sel.dataset.idx, 10)];
        if (!r) return;
        const [direction, anchor] = sel.value.split('|');
        r.direction = direction;
        r.anchor = anchor;
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
      const anchor = r.anchor === 'end' ? 'end' : 'start';
      const direction = r.direction === 'after' ? 'after' : 'before';
      if (allDay) {
        if (r.unit !== 'days' && r.unit !== 'weeks') return;
        if (!r.time) return;
        out.push({ value, unit: r.unit, time: r.time, anchor, direction });
      } else {
        out.push({ value, unit: r.unit, anchor, direction });
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
      _reminders.push({ value: 1, unit: 'days', time: '09:00', anchor: 'start', direction: 'before', isNew: true });
    } else {
      _reminders.push({ value: 15, unit: 'minutes', anchor: 'start', direction: 'before', isNew: true });
    }
    renderReminders();
  }

  // ── Recurrence editor ────────────────────────────────────────────────────────

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
    const ords = I18N.ordinals || [];
    document.getElementById('ev-recur-monthday-desc').textContent = String(dt.day);
    document.getElementById('ev-recur-weekday-desc').textContent =
      `${ords[ord - 1] || ord + '.'} ${dt.toFormat('cccc')}`;
  }

  function updateRecurUI() {
    const freq = document.getElementById('ev-recur-freq').value;
    document.getElementById('ev-recur-monthly').style.display = freq === 'monthly' ? '' : 'none';
    recurDescriptions();
    // Read-only (e.g. a read-only share): keep every recurrence control locked
    // so the rule can't be cosmetically edited.
    if (_editLocked) return;
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
    if (rule.count == null && rule.until == null) { box.textContent = tr('dyn.repeats_forever'); return; }
    try {
      const res = await apiPost('/events/recurrence-preview', {
        start,
        all_day: document.getElementById('ev-allday').checked,
        timezone: effectiveTz(),
        recurrence: rule,
      });
      box.textContent = res.last
        ? tr('dyn.recur_preview', {
            count: res.count,
            occ: tr(pluralIndex(res.count) === 0 ? 'dyn.occ_one' : 'dyn.occ_other'),
            date: String(res.last).slice(0, 10),
          })
        : tr('dyn.recur_no_occ');
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
      `<button type="button" class="ev-cal-btn" tabindex="-1" aria-label="${escHtml(tr('dyn.pick_date'))}">📅</button>`;

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

  // Localized Sun-indexed short weekday labels (luxon follows the UI language,
  // see luxon.Settings.defaultLocale). Falls back to the English abbreviations.
  function weekdayLabels() {
    if (window.luxon && luxon.Info) {
      const wd = luxon.Info.weekdays('short'); // [Mon … Sun]
      return [wd[6], wd[0], wd[1], wd[2], wd[3], wd[4], wd[5]];
    }
    return WEEKDAY_LABELS;
  }

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
      `<button type="button" class="ev-cal-nav" data-d="-1" aria-label="${escHtml(tr('dyn.prev'))}">‹</button>` +
      `<button type="button" class="ev-cal-title"></button>` +
      `<button type="button" class="ev-cal-nav" data-d="1" aria-label="${escHtml(tr('dyn.next'))}">›</button>` +
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
    const labels = weekdayLabels();
    const header = Array.from({ length: 7 }, (_, i) =>
      `<span class="ev-cal-dow">${escHtml(labels[(fdow + i) % 7])}</span>`).join('');
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
    _editLocked = !on;
    ['ev-name', 'ev-calendar', 'ev-allday', 'ev-start-hh', 'ev-start-mm',
     'ev-end-hh', 'ev-end-mm', 'ev-location', 'ev-notes',
     'ev-priority', 'ev-done'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !on;
    });
    // The repeats toggle keeps its own lock when editable (a recurring series
    // can't be un-recurred), so only force it off when read-only.
    if (!on) document.getElementById('ev-repeats').disabled = true;
    document.querySelectorAll(
      '.ev-date-fields input, .ev-date-fields button, .ev-time-fields input, .ev-ampm',
    ).forEach((el) => {
      el.disabled = !on;
    });
    // Lock the entire recurrence editor when read-only; updateRecurUI also
    // early-returns so it won't re-enable count/until fields by radio state.
    document.querySelectorAll(
      '#ev-recur-editor input, #ev-recur-editor select, #ev-recur-editor button',
    ).forEach((el) => { el.disabled = !on; });
    // Journal Markdown body: lock the raw editor so it can't be typed into.
    const jbody = document.getElementById('ev-journal-edit');
    if (jbody) jbody.readOnly = !on;
    document.getElementById('btn-event-save').style.display = on ? '' : 'none';
    _remindersEditable = on;
    renderReminders();
  }

  async function openEventModal(event) {
    const props = event.extendedProps || {};
    hideError('ev-error');

    const isTask = !!props.isTask;
    const isJournal = !!props.isJournal;
    const kind = isJournal ? 'journal' : (isTask ? 'task' : 'event');
    document.getElementById('ev-title-text').textContent =
      event.title || (isJournal ? tr('dyn.journal') : (isTask ? tr('dyn.task') : tr('dyn.event')));
    document.getElementById('ev-name').value = event.title || '';
    document.getElementById('ev-allday').checked = !!event.allDay;
    setModalType(kind, true);
    document.getElementById('ev-priority').value = String(props.priority || 0);
    document.getElementById('ev-done').checked = !!props.completed;

    const tz = effectiveTz();
    const rawStart = props.rawStart || (event.start ? event.start.toISOString() : null);
    let rawEnd;
    if (isTask) {
      // Tasks anchor on DUE (stored as-is, no exclusive-end shift); either side
      // may be absent (undated / start-only / due-only).
      rawEnd = props.rawDue || null;
    } else {
      rawEnd = props.rawEnd || (event.end ? event.end.toISOString() : rawStart);
      // iCal all-day DTEND is exclusive — show the inclusive last day.
      if (event.allDay && props.rawEnd) rawEnd = shiftDateStr(props.rawEnd, -1);
    }

    // Rebuild date + time inputs per current date_format / time_format before
    // populating values.
    renderDateFields('start', onFromChange);
    renderDateFields('end', onToChange);
    renderTimeFields('start', onFromChange);
    renderTimeFields('end', onToChange);

    // Events always carry both ends; tasks may leave fields blank.
    const endSrc = isTask ? rawEnd : (rawEnd || rawStart);
    if (event.allDay) {
      setDateFieldValue('start', rawStart ? String(rawStart).slice(0, 10) : '');
      setDateFieldValue('end', endSrc ? String(endSrc).slice(0, 10) : '');
    } else {
      if (rawStart) {
        const from = isoToInputs(rawStart, tz);
        setDateFieldValue('start', from.date);
        setTimeParts('start', from.hour, from.minute);
      }
      if (endSrc) {
        const to = isoToInputs(endSrc, tz);
        setDateFieldValue('end', to.date);
        setTimeParts('end', to.hour, to.minute);
      }
    }

    const recurrence = props.recurrence || '';
    document.getElementById('ev-repeats').checked = !!recurrence;
    // A recurring series can't be un-recurred from here, so lock the toggle.
    document.getElementById('ev-repeats').disabled = !!recurrence;
    const sumEl = document.getElementById('ev-recur-summary');
    if (recurrence) {
      sumEl.textContent = tr('dyn.recur_current', { rule: recurrence });
      sumEl.style.display = '';
    } else {
      sumEl.style.display = 'none';
    }
    resetRecurEditorDefaults();
    if (props.recurrenceRule) setRecurrence(props.recurrenceRule);

    document.getElementById('ev-location').value = props.location || '';
    document.getElementById('ev-notes').value = props.description || '';
    if (isJournal) { setJournalBody(props.description || ''); setJournalTab('display'); }

    resetReminders(props.reminders);

    // Demo events have no calendar and stay read-only. Recurring events are
    // editable, but saving asks which occurrences to change.
    const noteEl = document.getElementById('ev-edit-note');
    let editable = true;
    let note = '';
    if (props.calendarId == null) {
      editable = false;
      note = tr('dyn.demo_event');
    } else if (recurrence) {
      const kind = isTask ? 'task' : 'event';
      note = `Recurring ${kind} — you’ll choose which occurrences to change when you save.`;
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
    // In a share: a read-only share makes everything view-only; a read-write
    // share allows editing only on its writable calendars.
    if (SHARE_MODE) {
      const writable = (SHARE_CFG && SHARE_CFG.mode === 'rw'
        && (SHARE_CFG.calendars || []).some((c) => c.writable && c.id === props.calendarId));
      if (!writable) { editable = false; note = ''; noteEl.style.display = 'none'; }
    }

    // Recurring events are editable and deletable by scope, so offer Delete
    // whenever the event is calendar-backed (and, in a share, writable).
    const deletable = props.calendarId != null && editable;
    document.getElementById('btn-event-delete').style.display = deletable ? '' : 'none';
    setEditable(editable);

    _currentEvent = {
      id: event.id,
      calendarId: props.calendarId,
      originalCalendarId: props.calendarId,
      editable,
      isTask,
      isJournal,
      recurring: !!recurrence,
      rawStart: props.rawStart || (event.start ? event.start.toISOString() : null),
      // Stable pivot for scoped edits: an already-detached override keeps its
      // RECURRENCE-ID even after being moved, so prefer it over the (mutable)
      // current start to avoid creating a duplicate override on re-edit.
      recurrenceId: props.recurrenceId || null,
      completed: !!props.completed,
      isNew: false,
      // Baseline for the changed-property diff used by "reset customized".
      original: snapshotEditFields(),
    };

    // Share button: only for an existing, calendar-backed item, when enabled and
    // not already inside a share view.
    const shareBtn = document.getElementById('btn-event-share');
    if (shareBtn) {
      shareBtn.style.display =
        !SHARE_MODE && SHARING_ENABLED && props.calendarId != null ? '' : 'none';
    }

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
    if (SHARE_MODE) {
      // The sharee can only write to the share's writable calendars; map the
      // resolve metadata into the {id, display_name, enabled} shape the modal
      // calendar picker expects.
      const cals = (SHARE_CFG && SHARE_CFG.calendars) || [];
      _calendarsCache = cals
        .filter((c) => c.writable)
        .map((c) => ({ id: c.id, display_name: c.name, color: c.color, enabled: true }));
      return _calendarsCache;
    }
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

    document.getElementById('ev-title-text').textContent = tr('dyn.new_event');
    document.getElementById('ev-name').value = '';
    document.getElementById('ev-allday').checked = !!allDay;
    document.getElementById('ev-location').value = '';
    document.getElementById('ev-notes').value = '';
    document.getElementById('ev-priority').value = '0';
    document.getElementById('ev-repeats').checked = false;
    document.getElementById('ev-repeats').disabled = false;
    document.getElementById('ev-recur-summary').style.display = 'none';
    resetRecurEditorDefaults();
    resetReminders([]);
    setJournalBody('');
    setJournalTab('edit');
    setModalType('event', false);

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
      noteEl.textContent = tr('dyn.connect_to_create');
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

    // No sharing a not-yet-saved item.
    const shareBtnNew = document.getElementById('btn-event-share');
    if (shareBtnNew) shareBtnNew.style.display = 'none';

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

  // Snapshot the editable modal fields in a comparable shape. Taken once when the
  // modal opens and again at save time; the diff (computeChangedFields) drives the
  // "reset customized occurrences" property list.
  function snapshotEditFields() {
    const pad = (n) => String(n).padStart(2, '0');
    const t = (prefix) => {
      const { h24, m } = getTimeParts(prefix);
      return `${pad(h24)}:${pad(m)}`;
    };
    const allDay = document.getElementById('ev-allday').checked;
    const startDate = getDateFieldValue('start');
    const endDate = getDateFieldValue('end');
    return {
      title: document.getElementById('ev-name').value.trim(),
      location: document.getElementById('ev-location').value,
      description: document.getElementById('ev-notes').value,
      priority: document.getElementById('ev-priority').value,
      allDay,
      start: allDay ? startDate : `${startDate}T${t('start')}`,
      end: allDay ? endDate : `${endDate}T${t('end')}`,
      reminders: JSON.stringify(collectReminders()),
    };
  }

  function computeChangedFields(orig, cur, isTask) {
    const changed = [];
    if (!orig) return changed;
    if (cur.allDay !== orig.allDay || cur.start !== orig.start || cur.end !== orig.end) changed.push('time');
    if (cur.title !== orig.title) changed.push('title');
    if (cur.location !== orig.location) changed.push('location');
    if (cur.description !== orig.description) changed.push('description');
    if (isTask && cur.priority !== orig.priority) changed.push('priority');
    if (cur.reminders !== orig.reminders) changed.push('reminders');
    return changed;
  }

  async function saveEvent() {
    if (!_currentEvent || !_currentEvent.editable) return;
    hideError('ev-error');
    const allDay = document.getElementById('ev-allday').checked;
    const startDate = getDateFieldValue('start');
    const endDate = getDateFieldValue('end');
    const name = document.getElementById('ev-name').value.trim();

    if (!name) { showError('ev-error', tr('dyn.name_required')); return; }

    const pad = (n) => String(n).padStart(2, '0');
    const timeStr = (prefix) => {
      const { h24, m } = getTimeParts(prefix);
      return `${pad(h24)}:${pad(m)}`;
    };

    if (modalIsJournal()) { await saveJournal(name, allDay, startDate, timeStr); return; }
    if (modalIsTask()) { await saveTask(name, allDay, startDate, endDate, timeStr); return; }

    if (!startDate) { showError('ev-error', tr('dyn.start_required')); return; }

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
        showError('ev-error', tr('dyn.from_to_required'));
        return;
      }
      body.start = `${startDate}T${timeStr('start')}:00`;
      body.end = `${endDate}T${timeStr('end')}:00`;
    }

    // Editing a recurring event: pick which occurrences the change applies to.
    if (!_currentEvent.isNew && _currentEvent.recurring) {
      const changed = computeChangedFields(_currentEvent.original, snapshotEditFields(), false);
      const scope = await chooseScope(tr('dyn.what_to_change'), tr('dyn.noun_event'), changed);
      if (!scope) return;
      body.scope = scope;
      const pivot = _currentEvent.recurrenceId || _currentEvent.rawStart;
      if (pivot) body.recurrence_id = pivot;
      if (_scopeReset && changed.length && scope !== 'this') {
        body.reset_overrides = true;
        body.reset_fields = changed;
      }
    }

    const btn = document.getElementById('btn-event-save');
    btn.disabled = true;
    btn.textContent = tr('dyn.saving');
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
      btn.textContent = tr('dyn.save');
    }
  }

  // Save the modal as a VTODO. Mirrors the event path but dates are optional
  // (undated tasks), there is a priority, and writes target /tasks.
  async function saveTask(name, allDay, startDate, endDate, timeStr) {
    const body = {
      calendar_id: _currentEvent.calendarId,
      title: name,
      all_day: allDay,
      location: document.getElementById('ev-location').value,
      description: document.getElementById('ev-notes').value,
      timezone: effectiveTz(),
      priority: parseInt(document.getElementById('ev-priority').value, 10) || 0,
      reminders: collectReminders(),
    };
    const recurrence = getRecurrence();
    if (recurrence) body.recurrence = recurrence;
    if (recurrence && !startDate && !endDate) {
      showError('ev-error', 'A recurring task needs a start or due date.');
      return;
    }
    if (startDate) body.start = allDay ? startDate : `${startDate}T${timeStr('start')}:00`;
    if (endDate) body.due = allDay ? endDate : `${endDate}T${timeStr('end')}:00`;

    if (!_currentEvent.isNew && _currentEvent.recurring) {
      const changed = computeChangedFields(_currentEvent.original, snapshotEditFields(), true);
      const scope = await chooseScope(tr('dyn.what_to_change'), tr('dyn.noun_task'), changed);
      if (!scope) return;
      body.scope = scope;
      const pivot = _currentEvent.recurrenceId || _currentEvent.rawStart;
      if (pivot) body.recurrence_id = pivot;
      if (_scopeReset && changed.length && scope !== 'this') {
        body.reset_overrides = true;
        body.reset_fields = changed;
      }
    }

    const btn = document.getElementById('btn-event-save');
    btn.disabled = true;
    btn.textContent = tr('dyn.saving');
    try {
      if (_currentEvent.isNew) {
        await apiPost('/tasks', body);
      } else {
        body.original_calendar_id = _currentEvent.originalCalendarId;
        await apiPut(`/tasks/${encodeURIComponent(_currentEvent.id)}`, body);
        const wantDone = document.getElementById('ev-done').checked;
        if (wantDone !== _currentEvent.completed) {
          const st = { calendar_id: _currentEvent.calendarId, completed: wantDone };
          if (_currentEvent.recurring) {
            const pivot = _currentEvent.recurrenceId || _currentEvent.rawStart;
            if (pivot) st.recurrence_id = pivot;
          }
          await apiPost(`/tasks/${encodeURIComponent(_currentEvent.id)}/status`, st);
        }
      }
      closeEventModal();
      refreshViews();
    } catch (err) {
      showError('ev-error', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = tr('dyn.save');
    }
  }

  // Save the modal as a VJOURNAL. A single date (or datetime), a Markdown body,
  // and no recurrence / reminders / end. Writes target /journals.
  async function saveJournal(name, allDay, startDate, timeStr) {
    if (!startDate) { showError('ev-error', tr('dyn.start_required')); return; }
    const body = {
      calendar_id: _currentEvent.calendarId,
      title: name,
      all_day: allDay,
      description: getJournalBody(),
      timezone: effectiveTz(),
      start: allDay ? startDate : `${startDate}T${timeStr('start')}:00`,
    };
    const btn = document.getElementById('btn-event-save');
    btn.disabled = true;
    btn.textContent = tr('dyn.saving');
    try {
      if (_currentEvent.isNew) {
        await apiPost('/journals', body);
      } else {
        body.original_calendar_id = _currentEvent.originalCalendarId;
        await apiPut(`/journals/${encodeURIComponent(_currentEvent.id)}`, body);
      }
      closeEventModal();
      refreshViews();
    } catch (err) {
      showError('ev-error', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = tr('dyn.save');
    }
  }

  // Delete the event currently open in the modal (Delete button). No confirm
  // here — the spec reserves the "are you sure" prompt for the right-click menu.
  async function deleteCurrentEvent() {
    if (!_currentEvent || _currentEvent.isNew || _currentEvent.calendarId == null) return;
    // Recurring events delete by scope; pick one before hitting the server.
    let qs = `calendar_id=${_currentEvent.calendarId}`;
    if (_currentEvent.recurring) {
      const scope = await chooseScope(tr('dyn.what_to_delete'), tr(_currentEvent.isTask ? 'dyn.noun_task' : 'dyn.noun_event'));
      if (!scope) return;
      qs += `&scope=${scope}`;
      const pivot = _currentEvent.recurrenceId || _currentEvent.rawStart;
      if (pivot) {
        qs += `&recurrence_id=${encodeURIComponent(pivot)}`;
      }
    }
    const base = _currentEvent.isJournal ? '/journals' : (_currentEvent.isTask ? '/tasks' : '/events');
    const btn = document.getElementById('btn-event-delete');
    btn.disabled = true;
    try {
      await apiDelete(`${base}/${encodeURIComponent(_currentEvent.id)}?${qs}`);
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
    document.getElementById('ev-type').addEventListener('change', applyTypeToggle);
    document.getElementById('ev-journal-tab-edit').addEventListener('click', () => setJournalTab('edit'));
    document.getElementById('ev-journal-tab-display').addEventListener('click', () => setJournalTab('display'));
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
    const toggleBtn = document.getElementById('ctx-toggle-done');
    const p = event.extendedProps || {};
    if (p.isTask) {
      toggleBtn.style.display = '';
      toggleBtn.textContent = p.completed ? tr('dyn.mark_undone') : tr('dyn.mark_done');
    } else {
      toggleBtn.style.display = 'none';
    }
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
    document.getElementById('ctx-toggle-done').addEventListener('click', () => {
      const ev = _ctxEvent;
      hideContextMenu();
      if (!ev) return;
      const p = ev.extendedProps || {};
      toggleTaskDone(ev, !p.completed);
    });
    document.getElementById('ctx-delete').addEventListener('click', async () => {
      const ev = _ctxEvent;
      hideContextMenu();
      if (!ev) return;
      const props = ev.extendedProps || {};
      if (props.calendarId == null) return;
      const isTask = !!props.isTask;
      const isJournal = !!props.isJournal;
      const noun = tr(isJournal ? 'dyn.noun_journal' : (isTask ? 'dyn.noun_task' : 'dyn.noun_event'));
      let qs = `calendar_id=${props.calendarId}`;
      if (props.recurrence) {
        // Recurring: a scope choice replaces the plain yes/no confirm.
        const scope = await chooseScope(tr('dyn.what_to_delete'), noun);
        if (!scope) return;
        qs += `&scope=${scope}`;
        const pivot =
          props.recurrenceId || props.rawStart || (ev.start ? ev.start.toISOString() : null);
        if (pivot) qs += `&recurrence_id=${encodeURIComponent(pivot)}`;
      } else {
        const ok = await confirmDialog(tr('dyn.confirm_delete', { title: ev.title || tr(isJournal ? 'dyn.this_journal' : (isTask ? 'dyn.this_task' : 'dyn.this_event')) }));
        if (!ok) return;
      }
      try {
        const base = isJournal ? 'journals' : (isTask ? 'tasks' : 'events');
        await apiDelete(`/${base}/${encodeURIComponent(ev.id)}?${qs}`);
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

  // Reset-customized choice from the last scope pick (read by the edit flows
  // right after chooseScope resolves). Only the "all"/"thisfuture" buttons carry
  // a checkbox; everything else leaves this false.
  let _scopeReset = false;

  // changedFields (optional): the properties this edit changed. When given, the
  // "reset customized occurrences" checkboxes + info text are shown next to the
  // all/thisfuture buttons; omit it (delete/drag flows) to hide them.
  function chooseScope(text, noun, changedFields) {
    const n = noun || tr('dyn.noun_event');
    document.getElementById('scope-title').textContent = text;
    document.querySelector('#scope-modal [data-scope="this"]').textContent = tr('dyn.scope_this', { noun: n });
    document.querySelector('#scope-modal [data-scope="thisfuture"]').textContent = tr('dyn.scope_thisfuture', { noun: n });
    document.querySelector('#scope-modal [data-scope="all"]').textContent = tr('dyn.scope_all', { noun: n });
    _scopeReset = false;
    const rows = document.querySelectorAll('#scope-modal .scope-reset');
    const info = document.getElementById('scope-reset-info');
    const fields = Array.isArray(changedFields) ? changedFields : [];
    if (fields.length) {
      const props = fields.map((f) => tr('dyn.prop_' + f)).join(', ');
      rows.forEach((row) => {
        row.style.display = '';
        const cb = row.querySelector('input[type=checkbox]');
        if (cb) cb.checked = false;
        const span = row.querySelector('span');
        if (span) span.textContent = tr('dyn.scope_reset_customized', { noun: n });
      });
      info.textContent = tr('dyn.scope_reset_info', { noun: n, props });
      info.style.display = '';
    } else {
      rows.forEach((row) => { row.style.display = 'none'; });
      info.style.display = 'none';
    }
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
      btn.addEventListener('click', () => {
        const scope = btn.getAttribute('data-scope');
        const cb = document.getElementById('scope-reset-' + scope);
        _scopeReset = !!(cb && cb.checked);
        closeScope(scope);
      });
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

  // Build a PUT body for a dragged/resized task. Like eventToBody but emits
  // start/due (not start/end) and only the anchors the task actually has, so a
  // DUE-only or DTSTART-only task keeps its single anchor.
  function taskToBody(event) {
    const props = event.extendedProps || {};
    const body = {
      calendar_id: props.calendarId,
      title: event.title || '',
      all_day: event.allDay,
      location: props.location || '',
      description: props.description || '',
      priority: props.priority || 0,
      timezone: effectiveTz(),
    };
    const hasStart = props.rawStart != null;
    const hasDue = props.rawDue != null;
    if (hasStart && hasDue) {
      if (event.allDay) {
        // FC end is exclusive; a task DUE is stored inclusive (− 1 day).
        body.start = event.startStr.slice(0, 10);
        body.due = event.endStr ? shiftDateStr(event.endStr, -1) : body.start;
      } else {
        body.start = event.startStr;
        body.due = event.endStr || event.startStr;
      }
    } else {
      // Single anchor: the grid event start IS that anchor (DUE if present, else
      // DTSTART — matching the server's _build_task_event).
      const val = event.allDay ? event.startStr.slice(0, 10) : event.startStr;
      if (hasDue) body.due = val;
      else body.start = val;
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
    const isTask = !!props.isTask;
    const body = isTask ? taskToBody(info.event) : eventToBody(info.event);
    if (props.recurrence) {
      // A drag/resize only changes the time, so that is the lone reset target.
      const changed = ['time'];
      const scope = await chooseScope(
        tr('dyn.what_to_change'),
        tr(props.isTask ? 'dyn.noun_task' : 'dyn.noun_event'),
        changed,
      );
      if (!scope) { info.revert(); return; }
      body.scope = scope;
      // recurrence_id is the pivot: a detached override's stable RECURRENCE-ID
      // when present, else the ORIGINAL (pre-drag) occurrence start.
      const pivot =
        props.recurrenceId ||
        props.rawStart ||
        (info.oldEvent && info.oldEvent.start ? info.oldEvent.start.toISOString() : null);
      if (pivot) body.recurrence_id = pivot;
      if (_scopeReset && scope !== 'this') {
        body.reset_overrides = true;
        body.reset_fields = changed;
      }
    }
    try {
      const path = isTask ? '/tasks/' : '/events/';
      await apiPut(`${path}${encodeURIComponent(info.event.id)}`, body);
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
      el.textContent = tr('dyn.auto_logout_off');
      el.classList.remove('logout-countdown--warn');
      return;
    }
    if (_logoutRemaining == null) {
      el.textContent = '';
      return;
    }
    el.textContent = tr('dyn.logout_in', { time: fmtDuration(_logoutRemaining) });
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
    if (titleEl) titleEl.textContent = tr('dyn.agenda');
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
    // In an agenda share the slice is fixed: start at the sealed window and let
    // agendaLoadMore pull the single clamped page (no infinite scroll, no
    // pinned-undated section that would reach outside the slice).
    _agendaCursor = SHARE_MODE && SHARE_CFG && SHARE_CFG.window_from
      ? luxon.DateTime.fromISO(SHARE_CFG.window_from, { setZone: true }).setZone(tz)
      : luxon.DateTime.now().setZone(tz).startOf('day');
    _agendaEmptyRuns = 0;
    _agendaLoading = false;
    _agendaDone = false;
    _agendaSeen = new Set();
    _agendaLastDayKey = null;
    document.getElementById('agenda-list').innerHTML = '';
    agendaSetStatus('');
    if (!SHARE_MODE) renderAgendaPinned();
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
    // The share slice is a single fixed window; everything else tiles forward.
    const to = SHARE_MODE && SHARE_CFG && SHARE_CFG.window_to
      ? luxon.DateTime.fromISO(SHARE_CFG.window_to, { setZone: true }).setZone(effectiveTz())
      : from.plus({ days: AGENDA_CHUNK_DAYS });
    try {
      const data = [];
      const completedMode = (window.__SETTINGS__ || {}).completed_task_display || 'hidden';
      if (SHARE_MODE) {
        const items = await fetchShareItems();
        (items.events || []).forEach((e) => data.push(e));
        (items.tasks || []).forEach((e) => {
          const p = e.extendedProps || {};
          if (p.undated) return; // no date → not part of a bounded slice
          if (p.completed && completedMode === 'hidden') return;
          data.push(e);
        });
        (items.journals || []).forEach((e) => data.push(e));
      } else {
        const params = new URLSearchParams({ from: from.toISO(), to: to.toISO() });
        const [evR, tkR, jrR] = await Promise.all([
          fetch('/events?' + params.toString()),
          fetch('/tasks?' + params.toString()),
          fetch('/journals?' + params.toString()),
        ]);
        if (!evR.ok) throw new Error('Failed to fetch events');
        (await evR.json()).forEach((e) => data.push(e));
        if (tkR.ok) {
          (await tkR.json()).forEach((e) => {
            const p = e.extendedProps || {};
            if (p.undated) return; // shown in the pinned "Tasks" section
            if (p.completed && completedMode === 'hidden') return;
            data.push(e);
          });
        }
        if (jrR.ok) (await jrR.json()).forEach((e) => data.push(e));
      }

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
      // A share slice is one fixed page — stop after it so the sharee can't
      // scroll outside the shared window.
      if (SHARE_MODE) { _agendaDone = true; if (fresh.length) agendaSetStatus(''); else agendaSetStatus('end'); }
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

  // Build one agenda row. Events get a colour dot; tasks get a checkbox square
  // (the dot's task counterpart) that toggles completion without opening the
  // modal. `forcedTimeTxt` is used by the undated "Tasks" section.
  function agendaRowEl(e, forcedTimeTxt) {
    const tz = effectiveTz();
    const timeFmt = timeFormatKey() === '12h' ? 'h:mm a' : 'HH:mm';
    const p = e.extendedProps || {};
    const isTask = !!p.isTask;
    const isJournal = !!p.isJournal;
    const completedMode = (window.__SETTINGS__ || {}).completed_task_display || 'hidden';

    const row = document.createElement('div');
    row.className = 'agenda-row';
    // Expose the occurrence start so the agenda-share modal can infer a default
    // from/to from what's currently on screen.
    row.setAttribute('data-start', p.rawStart || e.start || '');
    if (isTask && p.completed && completedMode === 'grayed') row.classList.add('is-task-done');

    let timeTxt = forcedTimeTxt;
    if (timeTxt == null) {
      const start = luxon.DateTime.fromISO(p.rawStart || e.start, { setZone: true }).setZone(tz);
      timeTxt = e.allDay ? tr('ui.modal_allday') : start.toFormat(timeFmt);
    }
    const loc = p.location ? `<div class="agenda-loc">${escHtml(p.location)}</div>` : '';
    const marker = isJournal
      ? `<span class="agenda-tri" style="color:${escHtml(e.color || '#3788d8')}"></span>`
      : isTask
      ? `<span class="agenda-box${p.completed ? ' done' : ''}" style="color:${escHtml(e.color || '#3788d8')}" role="checkbox"></span>`
      : `<span class="agenda-dot" style="background:${escHtml(e.color || '#3788d8')}"></span>`;
    row.innerHTML =
      `<span class="agenda-time">${escHtml(timeTxt)}</span>` + marker +
      `<span class="agenda-main"><div class="agenda-title">${escHtml(e.title || '(no title)')}</div>${loc}</span>`;
    if (isTask) {
      const box = row.querySelector('.agenda-box');
      if (box) box.addEventListener('click', (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        toggleTaskDone(agendaToFcShim(e), !p.completed);
      });
    }
    row.addEventListener('click', () => openEventModal(agendaToFcShim(e)));
    return row;
  }

  function agendaAppendRows(events) {
    const tz = effectiveTz();
    const list = document.getElementById('agenda-list');
    const todayKey = luxon.DateTime.now().setZone(tz).toFormat('yyyy-MM-dd');
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
      frag.appendChild(agendaRowEl(e));
    }
    list.appendChild(frag);
  }

  // Pinned sections at the top of the agenda, above the day-grouped scroll list:
  //   • "Overdue" — dated tasks still undone whose due/start is before today,
  //     each shown with its own date + time. These sit first.
  //   • "Tasks"   — undated tasks (no date). Shown in both undated modes.
  // One /tasks fetch over a past window (today back AGENDA_OVERDUE_DAYS) feeds
  // both; undated tasks always come back via the server's separate todos pass.
  const AGENDA_OVERDUE_DAYS = 365;

  function agendaPinnedSection(id, label) {
    const sec = document.createElement('div');
    sec.id = id;
    const h = document.createElement('div');
    h.className = 'agenda-day-header';
    h.textContent = label;
    sec.appendChild(h);
    return sec;
  }

  async function renderAgendaPinned() {
    const tz = effectiveTz();
    const list = document.getElementById('agenda-list');
    ['agenda-overdue', 'agenda-undated'].forEach((id) => {
      const old = document.getElementById(id);
      if (old) old.remove();
    });
    const completedMode = (window.__SETTINGS__ || {}).completed_task_display || 'hidden';
    const todayStart = luxon.DateTime.now().setZone(tz).startOf('day');
    const dfmt = luxonDateFmt(dateFormatKey());
    const tfmt = timeFormatKey() === '12h' ? 'h:mm a' : 'HH:mm';
    try {
      const params = new URLSearchParams({
        from: todayStart.minus({ days: AGENDA_OVERDUE_DAYS }).toISO(),
        to: todayStart.toISO(),
      });
      const r = await fetch('/tasks?' + params.toString());
      if (!r.ok) return;
      const data = await r.json();
      // Recurring tasks expand into many past occurrences; collapse each series
      // (keyed by task id) to just its latest overdue occurrence so the list
      // shows one row per recurring task, not one per missed instance.
      const overdueById = new Map();
      const undated = [];
      data.forEach((e) => {
        const p = e.extendedProps || {};
        if (p.undated) {
          if (p.completed && completedMode === 'hidden') return;
          undated.push(e);
          return;
        }
        if (p.completed) return; // overdue lists undone tasks only
        const sISO = p.rawDue || e.start || p.rawStart;
        if (!sISO) return;
        const s = luxon.DateTime.fromISO(sISO, { setZone: true }).setZone(tz);
        if (s >= todayStart) return; // today/future handled by the scroll list
        e.__sortKey = s.toMillis();
        const prev = overdueById.get(e.id);
        if (!prev || e.__sortKey > prev.__sortKey) overdueById.set(e.id, e);
      });
      const overdue = Array.from(overdueById.values());

      // Build undated first, then overdue, so prepending overdue lands it above.
      if (undated.length) {
        const sec = agendaPinnedSection('agenda-undated', tr('dyn.agenda_tasks'));
        undated.forEach((e) => sec.appendChild(agendaRowEl(e, 'Task')));
        list.prepend(sec);
      }
      if (overdue.length) {
        overdue.sort(agendaCompare);
        const sec = agendaPinnedSection('agenda-overdue', tr('dyn.agenda_overdue'));
        overdue.forEach((e) => {
          const p = e.extendedProps || {};
          const s = luxon.DateTime
            .fromISO(p.rawDue || e.start || p.rawStart, { setZone: true }).setZone(tz);
          const when = e.allDay ? s.toFormat(dfmt) : s.toFormat(dfmt + ' ' + tfmt);
          sec.appendChild(agendaRowEl(e, when));
        });
        list.prepend(sec);
      }
    } catch (_) {}
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
        ? tr('dyn.agenda_no_more')
        : tr('dyn.agenda_no_upcoming');
    } else if (kind === 'error') {
      el.style.display = '';
      el.innerHTML =
        `${escHtml(tr('dyn.agenda_load_failed'))} <button type="button" id="agenda-retry" class="btn-outline">${escHtml(tr('dyn.agenda_retry'))}</button>`;
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

    document.getElementById('ev-title-text').textContent = tr('dyn.new_event');
    document.getElementById('ev-name').value = '';
    document.getElementById('ev-allday').checked = false;
    document.getElementById('ev-location').value = '';
    document.getElementById('ev-notes').value = '';
    document.getElementById('ev-priority').value = '0';
    document.getElementById('ev-repeats').checked = false;
    document.getElementById('ev-repeats').disabled = false;
    document.getElementById('ev-recur-summary').style.display = 'none';
    resetRecurEditorDefaults();
    resetReminders([]);
    setJournalBody('');
    setJournalTab('edit');
    setModalType('event', false);

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
      noteEl.textContent = tr('dyn.connect_to_create');
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

    // No sharing a not-yet-saved item.
    const shareBtnNew = document.getElementById('btn-event-share');
    if (shareBtnNew) shareBtnNew.style.display = 'none';

    refreshPrevBoundaries();
    applyAllDayToggle();
    applyRepeatsToggle();

    show('event-overlay');
    show('event-modal');
  }

  // ── Tasks (VTODO) ────────────────────────────────────────────────────────────

  // Shape the /tasks payload into FullCalendar events for the grid views,
  // honouring the completed-task and undated-task display settings.
  function prepTasksForGrid(data) {
    const s = window.__SETTINGS__ || {};
    const completedMode = s.completed_task_display || 'hidden';
    const undatedMode = s.undated_task_display || 'agenda';
    const todayStr = luxon.DateTime.now().setZone(effectiveTz()).toFormat('yyyy-MM-dd');
    const shareRO = SHARE_MODE && SHARE_CFG && SHARE_CFG.mode !== 'rw';
    const out = [];
    data.forEach((e) => {
      const p = e.extendedProps || {};
      // Dated tasks drag (move start/due) and resize like events; undated tasks
      // parked on "today" stay fixed (a drag would assign an arbitrary date).
      const canEdit = !shareRO && p.calendarId != null && !p.undated;
      e.editable = canEdit;
      e.startEditable = canEdit;
      // Only spanning tasks (both DTSTART and DUE) get draggable edges.
      e.durationEditable = canEdit && p.rawStart != null && p.rawDue != null;
      if (p.completed && completedMode === 'hidden') return;
      if (p.undated) {
        if (undatedMode !== 'today') return; // agenda-only → keep off the grid
        e.start = todayStr;
        e.allDay = true;
      }
      if (!e.start) return;
      const classes = ['fc-task'];
      if (p.completed && completedMode === 'grayed') classes.push('fc-task-grayed');
      e.classNames = classes;
      out.push(e);
    });
    return out;
  }

  // Swap FullCalendar's round dot for a checkbox square (empty / ticked). The
  // square toggles completion without opening the modal.
  function decorateTaskEl(info) {
    const props = info.event.extendedProps || {};
    const box = document.createElement('span');
    box.className = 'fc-task-box' + (props.completed ? ' done' : '');
    box.setAttribute('role', 'checkbox');
    box.setAttribute('aria-checked', props.completed ? 'true' : 'false');
    box.title = props.completed ? tr('dyn.mark_undone') : tr('dyn.mark_done');
    box.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      toggleTaskDone(info.event, !props.completed);
    });
    const dot = info.el.querySelector('.fc-daygrid-event-dot');
    if (dot) {
      // The dot carries the per-calendar colour as an inline border-color; the
      // box otherwise inherits the chip's dark text colour (black). Copy it so
      // the square stays calendar-coloured.
      box.style.color = dot.style.borderColor || getComputedStyle(dot).borderColor;
      dot.replaceWith(box);
    } else {
      const titleEl = info.el.querySelector('.fc-event-title, .fc-list-event-title');
      if (titleEl && titleEl.parentNode) titleEl.parentNode.insertBefore(box, titleEl);
      else info.el.prepend(box);
    }
  }

  // Swap FullCalendar's round dot for a downward-pointing triangle (a pencil
  // tip) so journals read distinctly from events (dot) and tasks (checkbox).
  function decorateJournalEl(info) {
    const tri = document.createElement('span');
    tri.className = 'fc-journal-tri';
    const dot = info.el.querySelector('.fc-daygrid-event-dot');
    if (dot) {
      tri.style.color = dot.style.borderColor || getComputedStyle(dot).borderColor;
      dot.replaceWith(tri);
    } else {
      const titleEl = info.el.querySelector('.fc-event-title, .fc-list-event-title');
      if (titleEl && titleEl.parentNode) titleEl.parentNode.insertBefore(tri, titleEl);
      else info.el.prepend(tri);
    }
  }

  async function toggleTaskDone(event, done) {
    const p = event.extendedProps || {};
    if (p.calendarId == null) return;
    // A read-only share (or a calendar not writable in this share) can't toggle.
    if (SHARE_MODE) {
      const writable = SHARE_CFG && SHARE_CFG.mode === 'rw'
        && (SHARE_CFG.calendars || []).some((c) => c.writable && c.id === p.calendarId);
      if (!writable) return;
    }
    const body = { calendar_id: p.calendarId, completed: done };
    if (p.recurrence) {
      const pivot =
        p.recurrenceId || p.rawStart || (event.start ? event.start.toISOString() : null);
      if (pivot) body.recurrence_id = pivot;
    }
    try {
      await apiPost(`/tasks/${encodeURIComponent(event.id)}/status`, body);
      refreshViews();
    } catch (err) {
      alert(err.message);
    }
  }

  // ── Calendar page ───────────────────────────────────────────────────────────

  // Open the create modal from a date-cell click with view-specific defaults.
  function openCreateFromDateClick(info) {
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
  }

  function initCalendar() {
    show('page-calendar');

    const shareRO = SHARE_MODE && SHARE_CFG && SHARE_CFG.mode !== 'rw';

    if (SHARE_MODE) {
      // Strip the authed chrome (settings/logout/email) and add a download
      // button + an access-mode badge to the header.
      ['btn-settings', 'btn-logout', 'logout-countdown', 'header-email'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
      });
      const hdr = document.querySelector('.top-bar');
      if (hdr) {
        const badge = document.createElement('span');
        badge.className = 'token-badge ' + (shareRO ? 'token-ro' : 'token-rw');
        badge.textContent = shareRO ? tr('ui.share_ro') : tr('ui.share_rw');
        const dl = document.createElement('button');
        dl.className = 'btn-outline';
        dl.textContent = tr('ui.share_download');
        dl.addEventListener('click', downloadShareIcs);
        hdr.appendChild(badge);
        hdr.appendChild(dl);
      }
    } else {
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
      initShareUI();
    }
    initEventModal();
    if (!SHARE_MODE && (window.__SETTINGS__ || {}).notifications_enabled) startNotifications();

    // For an item share, the "view" is just the single item's modal.
    if (SHARE_MODE && SHARE_CFG && SHARE_CFG.kind === 'item') {
      openShareItem();
      return;
    }

    const calendarEl = document.getElementById('calendar');
    const s = window.__SETTINGS__ || {};
    const tf = fcTimeFormats(timeFormatKey());
    const fcCat = I18N.fc || {};
    const fcBtn = fcCat.buttonText || {};
    // In a share the toolbar is locked: no prev/next/today, no view switcher,
    // no agenda toggle (the kind is fixed), no share button.
    const shareView = SHARE_MODE && SHARE_CFG
      ? (SHARE_CFG.kind === 'agenda' ? 'dayGridMonth' : (SHARE_CFG.grid_view || 'dayGridMonth'))
      : 'dayGridMonth';
    // Anchor the initial date inside the target month (window_from can be in the
    // previous month for a 6-week grid); week/day windows start on the period.
    const shareInitialDate = SHARE_MODE && SHARE_CFG
      ? (SHARE_CFG.grid_anchor || SHARE_CFG.window_from) : undefined;
    _fcCalendar = new FullCalendar.Calendar(calendarEl, {
      initialView: shareView,
      initialDate: shareInitialDate,
      validRange: SHARE_MODE && SHARE_CFG && SHARE_CFG.window_from
        ? { start: SHARE_CFG.window_from, end: SHARE_CFG.window_to }
        : undefined,
      // `locale` is the bare code so the Luxon plugin formats month/weekday
      // names (and the title range) for that language; passing a full locale
      // object instead would replace FullCalendar's range-formatting internals
      // and break the header title. Translated button/helper text is supplied
      // as top-level overrides. No locale bundle is vendored.
      locale: LANG,
      buttonText: fcBtn,
      allDayText: fcCat.allDayText,
      weekText: fcCat.weekText,
      moreLinkText: fcCat.moreLinkText,
      noEventsText: fcCat.noEventsText,
      customButtons: {
        agenda: { text: fcBtn.agenda || 'agenda', click: showAgenda },
        share: {
          text: '\u{1f517}',
          click: function () { if (_agendaActive) openAgendaShare(); else openGridShare(); },
        },
      },
      headerToolbar: SHARE_MODE
        ? { left: '', center: 'title', right: '' }
        : {
            left: 'prev,next today',
            center: 'title',
            right: SHARING_ENABLED
              ? 'agenda dayGridMonth,timeGridWeek,timeGridDay share'
              : 'agenda dayGridMonth,timeGridWeek,timeGridDay',
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
      // Enable drag-to-move and edge-resize; both start and end edges. A
      // read-only share disables all editing/creation.
      editable: !shareRO,
      eventResizableFromStart: true,
      // Click vs drag for event creation: a pixel threshold keeps a plain click
      // out of `select` (→ dateClick) while a real drag fires `select`.
      selectable: !shareRO,
      selectMinDistance: 5,
      events: async function (fetchInfo, successCallback, failureCallback) {
        try {
          let data, rawTasks, rawJournals;
          if (SHARE_MODE) {
            // One clamped call; the server bounds it to the sealed window/scope.
            const items = await fetchShareItems();
            data = items.events || [];
            rawTasks = items.tasks || [];
            rawJournals = items.journals || [];
          } else {
            const params = new URLSearchParams({ from: fetchInfo.startStr, to: fetchInfo.endStr });
            const [evR, tkR, jrR] = await Promise.all([
              fetch('/events?' + params.toString()),
              fetch('/tasks?' + params.toString()),
              fetch('/journals?' + params.toString()),
            ]);
            if (!evR.ok) throw new Error('Failed to fetch events');
            data = await evR.json();
            rawTasks = tkR.ok ? await tkR.json() : [];
            rawJournals = jrR.ok ? await jrR.json() : [];
          }
          // Only real (calendar-backed) events are editable; recurring ones
          // prompt for occurrence scope on drop (see onEventChange). In a
          // read-only share nothing is drag/resize editable.
          const shareRO = SHARE_MODE && SHARE_CFG && SHARE_CFG.mode !== 'rw';
          data.forEach((e) => {
            const p = e.extendedProps || {};
            e.editable = !shareRO && p.calendarId != null;
          });
          const tasks = prepTasksForGrid(rawTasks);
          // Journals aren't drag/resize editable; left-click opens the modal.
          const journals = rawJournals.map((e) => {
            e.editable = false;
            e.classNames = ['fc-journal'];
            return e;
          });
          successCallback(data.concat(tasks).concat(journals));
        } catch (err) {
          failureCallback(err);
        }
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        openEventModal(info.event);
      },
      // Click on empty space. Default: open the create modal immediately. When
      // the "double-click to create" setting is on, a single click only
      // highlights the day/slot and a double click opens the modal.
      dateClick: function (info) {
        hideContextMenu();
        if (!(window.__SETTINGS__ || {}).double_click_to_create_events) {
          openCreateFromDateClick(info);
          return;
        }
        const now = Date.now();
        if (_lastDateClick && _lastDateClick.dateStr === info.dateStr
            && now - _lastDateClick.time < DBLCLICK_MS) {
          _lastDateClick = null;
          openCreateFromDateClick(info);
          return;
        }
        _lastDateClick = { dateStr: info.dateStr, time: now };
        // Single click → highlight only. Drive FullCalendar's own selection so
        // the day/slot lights up, but suppress the modal the select handler
        // would otherwise open.
        const end = info.allDay
          ? info.date
          : new Date(info.date.getTime() + 30 * 60 * 1000);
        _suppressSelectModal = true;
        try {
          info.view.calendar.select({ start: info.date, end: end, allDay: info.allDay });
        } finally {
          _suppressSelectModal = false;
        }
      },
      // Drag over empty space → create modal spanning the dragged range.
      select: function (info) {
        if (_suppressSelectModal) return; // highlight-only single click
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
        if (props.isJournal) decorateJournalEl(info);
        else if (props.isTask) decorateTaskEl(info);
        info.el.addEventListener('contextmenu', function (e) {
          e.preventDefault();
          showContextMenu(e.pageX, e.pageY, info.event);
        });
      },
      eventDrop: onEventChange,
      eventResize: onEventChange,
    });
    _fcCalendar.render();

    const fab = document.getElementById('btn-create-fab');
    fab.addEventListener('click', openCreateModalBlank);
    // The create FAB only makes sense when the viewer can write somewhere.
    if (shareRO || (SHARE_MODE && getShareWritableCount() === 0)) fab.style.display = 'none';

    // datesSet only fires when the view/range actually changes, so clicking the
    // button of the view FC is already on (e.g. "month" while month sits under
    // the agenda) wouldn't leave the agenda. Catch every toolbar button click.
    const toolbarEl = calendarEl.querySelector('.fc-header-toolbar');
    if (toolbarEl) {
      toolbarEl.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b || b.classList.contains('fc-agenda-button')
            || b.classList.contains('fc-share-button')) return;
        hideAgenda();
      });
    }

    if (SHARE_MODE) {
      // The kind fixes the view. Agenda shares open the bounded agenda slice;
      // grid shares are already on their locked view + window.
      if (SHARE_CFG && SHARE_CFG.kind === 'agenda') showAgenda();
      return;
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

  function getShareWritableCount() {
    return ((SHARE_CFG && SHARE_CFG.calendars) || []).filter((c) => c.writable).length;
  }

  // Open the single shared item directly in the normal event modal (so a journal
  // renders its markdown, a task shows its done state, etc.). A "Reopen" button
  // is shown behind it since there is nothing else on the page.
  async function openShareItem() {
    document.getElementById('calendar').style.display = 'none';
    let item = null;
    try {
      const items = await fetchShareItems();
      const all = (items.events || []).concat(items.tasks || []).concat(items.journals || []);
      item = all[0] || null;
    } catch (e) { /* fall through to the empty state */ }
    const body = document.querySelector('.calendar-body');
    if (body && !document.getElementById('share-item-reopen')) {
      const wrap = document.createElement('div');
      wrap.className = 'share-item-empty';
      wrap.innerHTML = item
        ? `<button id="share-item-reopen" class="btn-primary"></button>`
        : `<p class="empty-note">${escHtml(tr('dyn.share_empty'))}</p>`;
      body.appendChild(wrap);
      const btn = document.getElementById('share-item-reopen');
      if (btn) {
        btn.textContent = tr('ui.ctx_edit');
        btn.addEventListener('click', () => openEventModal(agendaToFcShim(item)));
      }
    }
    if (item) await openEventModal(agendaToFcShim(item));
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
      const title = e.title || tr('dyn.no_title');
      const endStr = p.rawEnd || e.end;
      const end = endStr
        ? (allDay
            ? luxon.DateTime.fromISO(String(endStr).slice(0, 10), { zone: tz })
            : luxon.DateTime.fromISO(endStr, { setZone: true }).setZone(tz))
        : null;
      out.push({ uid: e.id, when: start, title, allDay, displayAt: start });
      (p.reminders || []).forEach((r) => {
        let when = null;
        const base = r.anchor === 'end' ? end : start;
        const sign = r.direction === 'after' ? 1 : -1;
        if (r.readonly) {
          if (r.at) when = luxon.DateTime.fromISO(r.at, { setZone: true }).setZone(tz);
        } else if (base && base.isValid) {
          if (allDay && r.time) {
            const [hh, mm] = r.time.split(':').map(Number);
            const days = r.value * (r.unit === 'weeks' ? 7 : 1);
            when = base.startOf('day').plus({ days: sign * days }).plus({ hours: hh, minutes: mm });
          } else if (!allDay) {
            when = base.plus({ [r.unit]: sign * r.value });
          }
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
    // Look back as well as ahead so a reminder anchored *after* an event that
    // has already ended still loads (buildTriggers drops anything past `now`).
    const lookback = (window.__CONFIG__ || {}).notification_lookback_days || 60;
    const params = new URLSearchParams({
      from: now.minus({ days: lookback }).toISO(),
      to: now.plus({ days: horizon }).toISO(),
    });
    // Notify on events and tasks alike. Tasks anchor on due/start (their
    // `start`) and carry reminders in the same shape, so buildTriggers handles
    // both. Skip completed tasks — a done task shouldn't keep nagging.
    const [evR, tkR] = await Promise.all([
      fetch('/events?' + params.toString()),
      fetch('/tasks?' + params.toString()),
    ]);
    if (!evR.ok) throw new Error('events fetch failed');
    const events = await evR.json();
    let tasks = [];
    if (tkR.ok) {
      tasks = (await tkR.json()).filter((t) => !((t.extendedProps || {}).completed));
    }
    return events.concat(tasks);
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
    // Date/time formatting (Luxon) and static markup follow the active language.
    if (window.luxon && luxon.Settings) luxon.Settings.defaultLocale = LANG;
    applyTranslations(document);
    const state = window.__STATE__;
    if (state === 'anonymous') initLogin();
    else if (state === 'restricted') initChangePassword();
    else if (state === 'authenticated') initCalendar();
    else if (state === 'share') {
      // Resolve the share (secret in the X-Share-Secret header) before building
      // the calendar, then reuse the normal calendar in share mode.
      resolveShare()
        .then(() => initCalendar())
        .catch(() => {
          show('page-calendar');
          const body = document.querySelector('.calendar-body') || document.body;
          const p = document.createElement('p');
          p.className = 'error-msg';
          p.style.margin = '2rem';
          p.textContent = tr(SHARE_SECRET ? 'dyn.share_invalid' : 'dyn.share_no_secret');
          body.appendChild(p);
        });
    }
  });
})();
