/* Account dialogs reuse the page's accessible native dialog and form controls. */
(() => {
  'use strict';
  const e = value => window.UI.escape(value);
  const domainRole = role => role === 'student' ? 'team' : role;
  const roleName = role => domainRole(role) === 'business' ? 'business' : 'student';
  const home = () => window.Api.getRole() === 'business' ? '#workspace' : '#proposals';
  const field = (label, name, value = '', options = {}) => `<label class="field${options.wide ? ' field-wide' : ''}"><span>${e(label)}</span><input name="${name}" type="${options.type || 'text'}" value="${e(value)}" ${options.required === false ? '' : 'required'} maxlength="${options.max || 160}" ${options.min ? `minlength="${options.min}"` : ''} autocomplete="${options.autocomplete || 'off'}">${options.hint ? `<small>${e(options.hint)}</small>` : ''}</label>`;
  async function busy(form, action) {
    if (form.dataset.busy) return;
    const error = form.querySelector('[role="alert"]');
    error.hidden = true;
    form.dataset.busy = 'true';
    form.setAttribute('aria-busy', 'true');
    const controls = Array.from(form.querySelectorAll('input,button')).map(item => [item, item.disabled]);
    controls.forEach(([item]) => { item.disabled = true; });
    const button = form.querySelector('[type="submit"]');
    const label = button?.textContent;
    if (button) button.textContent = 'Please wait…';
    try { await action(); }
    catch (cause) { error.textContent = cause.message || 'Please try again.'; error.hidden = false; }
    finally {
      controls.forEach(([item, disabled]) => { item.disabled = disabled; });
      if (button) button.textContent = label;
      delete form.dataset.busy;
      form.removeAttribute('aria-busy');
    }
  }
  function show({ mode = 'login', role = 'team', afterSuccess } = {}) {
    const desiredRole = domainRole(role);
    if (window.Api.getUser()) { requireAccount(desiredRole, afterSuccess || (() => window.UI.navigate(home()))); return; }
    let selectedRole = desiredRole;
    const values = { name: '', email: '', password: '', organization_name: '', team_name: '' };
    const startedOn = window.location.hash;
    function draw() {
      const signup = mode === 'register';
      const business = selectedRole === 'business';
      const legacy = signup ? window.Api.getLegacyProfile(selectedRole) : null;
      const profileKey = business ? 'organization_name' : 'team_name';
      if (legacy && !values[profileKey]) values[profileKey] = legacy.name;
      const dialog = window.UI.modal(signup ? 'Your next chapter.' : 'Good to see you.', `<form class="stack auth-form"><div class="auth-tabs" role="group" aria-label="Account access"><button type="button" data-mode="login" aria-pressed="${!signup}">Sign in</button><button type="button" data-mode="register" aria-pressed="${signup}">Create account</button></div><div><p class="eyebrow">${signup ? 'A PLACE TO BUILD SOMETHING REAL' : 'WELCOME BACK'}</p><p class="muted">${signup ? 'One personal account. A workspace for the work ahead.' : 'Sign in with your email to pick up where you left off.'}</p></div>${signup ? `<fieldset class="auth-role"><legend>I’m joining as</legend><label><input type="radio" name="account_role" value="team" ${!business ? 'checked' : ''}><span>Student</span></label><label><input type="radio" name="account_role" value="business" ${business ? 'checked' : ''}><span>Business</span></label></fieldset>` : ''}<div class="form-grid">${signup ? field('Your full name', 'name', values.name, { wide: true, autocomplete: 'name' }) : ''}${field('Email address', 'email', values.email, { type: 'email', max: 320, autocomplete: 'email', wide: true })}${field('Password', 'password', values.password, { type: 'password', max: 128, min: signup ? 15 : undefined, autocomplete: signup ? 'new-password' : 'current-password', wide: true, hint: signup ? 'Use 15–128 characters. A memorable passphrase works well.' : '' })}${signup ? field(business ? 'Organization name' : 'Team name', profileKey, values[profileKey], { wide: true, autocomplete: business ? 'organization' : 'off', hint: business ? 'The organization whose challenges you will publish.' : 'Your personal student account will be linked to this team profile.' }) : ''}</div><label class="checkbox-field"><input type="checkbox" data-show-password><span>Show password</span></label>${legacy ? `<label class="checkbox-field auth-legacy"><input type="checkbox" name="claim_legacy" checked><span>Link the previous ${business ? 'business' : 'team'} workspace “${e(legacy.name)}” saved in this browser, including its existing ${business ? 'tasks' : 'proposals'}.</span></label>` : ''}<p class="error-message" role="alert" hidden></p><button type="submit" class="btn btn-primary">${signup ? 'Create account' : 'Sign in'} ${window.UI.icon('arrow')}</button>${signup ? '<p class="muted">Use your email and password to return from another browser or device.</p>' : ''}</form>`);
      const form = dialog.querySelector('form');
      const capture = () => { for (const key of Object.keys(values)) if (form.elements[key]) values[key] = form.elements[key].value; };
      form.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => { capture(); mode = button.dataset.mode; draw(); }));
      form.querySelectorAll('[name="account_role"]').forEach(input => input.addEventListener('change', () => { capture(); selectedRole = input.value; draw(); }));
      form.querySelector('[data-show-password]').addEventListener('change', event => { form.elements.password.type = event.target.checked ? 'text' : 'password'; });
      form.addEventListener('submit', event => {
        event.preventDefault();
        capture();
        const claimLegacy = !!form.elements.claim_legacy?.checked;
        const payload = signup ? { role: selectedRole === 'team' ? 'student' : 'business', name: values.name.trim(), email: values.email.trim(), password: values.password, [profileKey]: values[profileKey].trim() } : { email: values.email.trim(), password: values.password };
        busy(form, async () => {
          if (signup) await window.Api.register(payload, { claimLegacy });
          else await window.Api.login(payload);
          values.password = '';
          form.elements.password.value = '';
          form.elements.password.removeAttribute('value');
          if (!dialog.open || !form.isConnected || window.location.hash !== startedOn) return;
          window.UI.closeModal();
          window.UI.toast(signup ? 'Your account is ready.' : 'You’re signed in.');
          if (afterSuccess) requireAccount(desiredRole, afterSuccess);
          else window.UI.navigate(home());
        });
      });
    }
    draw();
  }
  function requireAccount(role, callback) {
    const required = domainRole(role);
    if (!window.Api.getUser()) { show({ role: required, afterSuccess: callback }); return; }
    if (window.Api.getRole() === required) { callback?.(window.Api.getProfile(required)); return; }
    const user = window.Api.getUser();
    const dialog = window.UI.modal('A different workspace.', `<form class="stack"><p class="eyebrow">ACCOUNT ROLE</p><h3 class="panel-title">This action is for ${roleName(required)} accounts.</h3><p class="muted">You are signed in as ${e(user.name)} with a ${roleName(window.Api.getRole())} account. Sign out to use a different account.</p><p class="error-message" role="alert" hidden></p><button type="submit" class="btn btn-primary">Sign out & switch account ${window.UI.icon('arrow')}</button><button type="button" class="btn" data-home>Go to my workspace</button></form>`);
    const form = dialog.querySelector('form');
    form.querySelector('[data-home]').addEventListener('click', () => { window.UI.closeModal(); window.UI.navigate(home()); });
    form.addEventListener('submit', event => {
      event.preventDefault();
      busy(form, async () => { await window.Api.logout({ switching: true }); window.UI.closeModal(); show({ role: required, afterSuccess: callback }); });
    });
  }
  function showAccount() {
    if (!window.Api.getUser()) { show(); return; }
    const user = window.Api.getUser(), profile = window.Api.getProfile();
    const business = window.Api.getRole() === 'business';
    const dialog = window.UI.modal('Your account.', `<form class="stack"><div><p class="eyebrow">${business ? 'BUSINESS ACCOUNT' : 'PERSONAL STUDENT ACCOUNT'}</p><h3 class="panel-title">${e(user.name)}</h3></div><div class="data-row"><span>Email</span><span>${e(user.email)}</span></div><div class="data-row"><span>${business ? 'Organization' : 'Linked team'}</span><span>${e(profile?.name || '')}</span></div><p class="muted">${business ? 'Publish challenges and choose the teams you work with.' : 'Your proposals are submitted through your linked team profile.'}</p><button class="btn btn-primary" type="button" data-home>Open my ${business ? 'workspace' : 'proposals'} ${window.UI.icon('arrow')}</button><p class="error-message" role="alert" hidden></p><button class="btn" type="submit">Sign out</button></form>`);
    const form = dialog.querySelector('form');
    form.querySelector('[data-home]').addEventListener('click', () => { window.UI.closeModal(); window.UI.navigate(home()); });
    form.addEventListener('submit', event => {
      event.preventDefault();
      busy(form, async () => { await window.Api.logout(); window.UI.closeModal(); window.UI.toast('You’re signed out.'); });
    });
  }
  function renderGate(root, role, resume) {
    const business = domainRole(role) === 'business';
    const signedIn = !!window.Api.getUser();
    root.innerHTML = `<header class="page-header"><p class="eyebrow">${business ? 'BUSINESS' : 'STUDENT'} WORKSPACE</p><h1 class="page-title">${signedIn ? 'The right space<br>for your work.' : 'Your work.<br>Your next step.'}</h1><p class="page-description">${signedIn ? `This page requires a ${business ? 'business' : 'student'} account. Your current account is for ${roleName(window.Api.getRole())} work.` : business ? 'Sign in to turn a business challenge into a clear task and choose your team.' : 'Sign in to follow your team’s proposals and find a meaningful challenge.'}</p></header><section class="panel auth-gate stack"><div class="inline-actions"><button type="button" class="btn btn-primary" data-login>${signedIn ? 'Switch account' : 'Sign in'} ${window.UI.icon('arrow')}</button>${!signedIn ? '<button type="button" class="btn" data-register>Create account</button>' : '<button type="button" class="btn" data-own>My workspace</button>'}<a class="text-link" href="#catalog">Explore tasks</a></div></section>`;
    const startedOn = window.location.hash;
    const continuation = () => { if (window.location.hash === startedOn) resume?.(); else window.UI.navigate(startedOn); };
    root.querySelector('[data-login]').addEventListener('click', () => requireAccount(role, continuation));
    root.querySelector('[data-register]')?.addEventListener('click', () => show({ mode: 'register', role, afterSuccess: continuation }));
    root.querySelector('[data-own]')?.addEventListener('click', () => window.UI.navigate(home()));
  }
  window.Auth = { show, require: requireAccount, showAccount, renderGate };
})();
