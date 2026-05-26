(function () {
  'use strict';

  function show(id) {
    document.getElementById(id).style.display = '';
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

  function initLogin() {
    show('page-login');
    const form = document.getElementById('login-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError('login-error');
      const btn = form.querySelector('button');
      btn.disabled = true;
      try {
        const data = await apiPost('/auth/login', {
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

  function initCalendar() {
    show('page-calendar');

    const emailEl = document.getElementById('header-email');
    if (window.__USER_EMAIL__) emailEl.textContent = window.__USER_EMAIL__;

    document.getElementById('btn-logout').addEventListener('click', async () => {
      await fetch('/auth/logout', { method: 'POST' });
      window.location.href = '/';
    });

    const calendarEl = document.getElementById('calendar');
    const s = window.__SETTINGS__ || {};
    const calendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,timeGridWeek,timeGridDay',
      },
      firstDay: s.first_day_of_week != null ? s.first_day_of_week : 1,
      timeZone: s.timezone || 'local',
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
    });
    calendar.render();
  }

  document.addEventListener('DOMContentLoaded', function () {
    const state = window.__STATE__;
    if (state === 'anonymous') initLogin();
    else if (state === 'restricted') initChangePassword();
    else if (state === 'authenticated') initCalendar();
  });
})();
