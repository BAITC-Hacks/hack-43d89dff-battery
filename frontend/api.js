/* The server owns account identity. Session and CSRF state stay in memory. */
(() => {
  'use strict';
  const apiRoot = String(window.MARKETPLACE_API_BASE || '').replace(/\/+$/, '').replace(/\/api$/, '');
  const apiOrigin = new URL(apiRoot || '/', window.location.href).origin;
  const storagePrefix = `sana.marketplace.v1:${apiOrigin}:`;
  let available = false;
  let session = { user: null, profile: null, csrf_token: null, expires_at: null };
  const domainRole = role => role === 'student' ? 'team' : role;
  const getRole = () => session.user ? domainRole(session.user.role) : null;
  const getProfile = (role = getRole()) => getRole() === domainRole(role) ? session.profile : null;

  function setSession(value, reason) {
    session = value?.user ? value : { user: null, profile: null, csrf_token: null, expires_at: null };
    window.dispatchEvent(new CustomEvent('sessionchange', { detail: { reason } }));
    return session;
  }
  function requireProfile(role) {
    const profile = getProfile(role);
    if (profile && session.user) return profile;
    const error = new Error(session.user ? `This action requires a ${role === 'business' ? 'business' : 'student'} account. Sign out to use another account.` : 'Sign in to continue.');
    error.code = session.user ? 'role_mismatch' : 'authentication_required';
    throw error;
  }
  function legacyProfile(role) {
    try {
      const value = JSON.parse(window.localStorage.getItem(`${storagePrefix}profile:${domainRole(role)}`) || 'null');
      return value && typeof value.id === 'string' && typeof value.owner_token === 'string' && value.owner_token ? value : null;
    } catch (_) { return null; }
  }
  function clearLegacy(role) {
    try {
      window.localStorage.removeItem(`${storagePrefix}profile:${domainRole(role)}`);
      window.localStorage.removeItem(`${storagePrefix}role`);
    } catch (_) { /* Blocked storage does not affect the server session. */ }
  }
  async function request(path, { method = 'GET', body, role, signal } = {}) {
    const headers = { Accept: 'application/json' };
    if (role) requireProfile(role);
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && method !== 'HEAD' && session.csrf_token) headers['X-CSRF-Token'] = session.csrf_token;
    let response;
    try {
      response = await fetch(apiRoot + path, {
        method, headers, signal, credentials: apiOrigin === window.location.origin ? 'same-origin' : 'include', cache: 'no-store',
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (cause) {
      available = false;
      const error = new Error(cause.name === 'AbortError' ? 'The server is taking too long to respond. Try again.' : 'Cannot connect to the marketplace. Start the local server and try again.');
      error.code = 'connection_error';
      throw error;
    }
    let data;
    try { data = await response.json(); }
    catch (_) {
      available = false;
      throw new Error('The marketplace returned an invalid response. Check that the API server is running.');
    }
    available = true;
    if (!response.ok) {
      if (response.status === 401 && session.user) setSession(null, 'expired');
      const error = new Error(data.error?.message || `Request failed (${response.status}). Please try again.`);
      error.code = data.error?.code || 'request_failed';
      error.status = response.status;
      throw error;
    }
    return data;
  }
  const idPath = id => encodeURIComponent(String(id));
  const businessAction = (id, action, body = {}) => request(`/api/tasks/${idPath(id)}/${action}`, { method: 'POST', body, role: 'business' });
  window.Api = Object.freeze({
    async initSession() {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 5000);
      try { return setSession(await request('/api/auth/session', { signal: controller.signal }), 'restore'); }
      finally { window.clearTimeout(timeout); }
    },
    getUser: () => session.user,
    getRole,
    getProfile,
    getLegacyProfile(role) { const profile = legacyProfile(role); return profile ? { id: profile.id, name: profile.name || 'Previous workspace' } : null; },
    async register(payload, { claimLegacy = false } = {}) {
      const role = domainRole(payload.role);
      const legacy = claimLegacy ? legacyProfile(role) : null;
      const body = { ...payload, ...(legacy ? { legacy_profile_id: legacy.id, legacy_owner_token: legacy.owner_token } : {}) };
      const result = await request('/api/auth/register', { method: 'POST', body });
      if (legacy) clearLegacy(role);
      return setSession(result, 'register');
    },
    async login(payload) { return setSession(await request('/api/auth/login', { method: 'POST', body: payload }), 'login'); },
    async logout({ switching = false } = {}) { const result = await request('/api/auth/logout', { method: 'POST', body: {} }); return setSession(result, switching ? 'switch' : 'logout'); },
    async checkHealth() {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 5000);
      try { available = (await request('/health', { signal: controller.signal })).status === 'ok'; }
      catch (_) { available = false; }
      finally { window.clearTimeout(timeout); }
      return available;
    },
    isAvailable: () => available,
    createTask: draft => request('/api/tasks', { method: 'POST', role: 'business', body: { business_id: requireProfile('business').id, initial_draft: draft } }),
    getTask: id => request(`/api/tasks/${idPath(id)}`),
    getCatalog(filters = {}) {
      const query = new URLSearchParams();
      for (const key of ['tags', 'industry', 'readiness', 'min_score', 'q', 'limit', 'offset']) {
        const value = filters[key];
        if (value !== undefined && value !== null && value !== '') query.set(key, Array.isArray(value) ? value.join(',') : String(value));
      }
      return request(`/api/catalog${query.size ? `?${query}` : ''}`);
    },
    getBusinessTasks: () => request(`/api/businesses/${idPath(requireProfile('business').id)}/tasks`, { role: 'business' }),
    submitAnswers: (id, answers) => businessAction(id, 'answers', { answers }),
    updateCard: (id, patch) => request(`/api/tasks/${idPath(id)}/card`, { method: 'PATCH', body: patch, role: 'business' }),
    confirmTask: id => businessAction(id, 'confirm'),
    publishTask: id => businessAction(id, 'publish'),
    getTaskProposals: id => request(`/api/tasks/${idPath(id)}/proposals`, { role: 'business' }),
    decideProposal: (id, decision) => request(`/api/proposals/${idPath(id)}/decision`, { method: 'PATCH', body: { decision }, role: 'business' }),
    submitProposal: (id, payload) => request(`/api/tasks/${idPath(id)}/proposals`, { method: 'POST', role: 'team', body: { ...payload, team_id: requireProfile('team').id } }),
    getTeamProposals: () => request(`/api/teams/${idPath(requireProfile('team').id)}/proposals`, { role: 'team' }),
  });
})();
