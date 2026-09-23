/* The browser owns two separate MVP identities; the server owns all task data. */
(() => {
  'use strict';

  const apiRoot = String(window.MARKETPLACE_API_BASE || '').replace(/\/+$/, '').replace(/\/api$/, '');
  const apiOrigin = new URL(apiRoot || '/', window.location.href).origin;
  const storagePrefix = `sana.marketplace.v1:${apiOrigin}:`;
  const memory = new Map();
  let available = false;

  function readStored(key) {
    if (memory.has(key)) return memory.get(key);
    try { return window.localStorage.getItem(storagePrefix + key); }
    catch (_) { return null; }
  }

  function writeStored(key, value) {
    memory.set(key, value);
    try { window.localStorage.setItem(storagePrefix + key, value); }
    catch (_) { /* The identity remains usable for this page when storage is blocked. */ }
  }

  function validRole(role) {
    if (role !== 'business' && role !== 'team') throw new Error('Choose Business or Student team.');
    return role;
  }

  function getRole() {
    return readStored('role') === 'business' ? 'business' : 'team';
  }

  function getProfile(role = getRole()) {
    validRole(role);
    try {
      const profile = JSON.parse(readStored(`profile:${role}`) || 'null');
      if (!profile || typeof profile.id !== 'string' || typeof profile.name !== 'string' ||
          typeof profile.owner_token !== 'string' || !profile.owner_token) return null;
      return profile;
    } catch (_) { return null; }
  }

  function requireProfile(role) {
    const profile = getProfile(role);
    if (profile) return profile;
    const error = new Error(role === 'business'
      ? 'Create your business profile to manage challenges.'
      : 'Create your team profile to submit a proposal.');
    error.code = 'profile_required';
    throw error;
  }

  async function request(path, { method = 'GET', body, role, signal } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (role) headers['X-Owner-Token'] = requireProfile(role).owner_token;

    let response;
    try {
      response = await fetch(apiRoot + path, {
        method, headers, signal, credentials: 'omit', cache: 'no-store',
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (cause) {
      available = false;
      const error = new Error(cause.name === 'AbortError'
        ? 'The server is taking too long to respond. Try again.'
        : 'Cannot connect to the marketplace. Start the local server and try again.');
      error.code = 'connection_error';
      throw error;
    }

    let data;
    try { data = await response.json(); }
    catch (_) {
      available = false;
      const error = new Error('The marketplace returned an invalid response. Check that the API server is running.');
      error.code = 'invalid_response';
      error.status = response.status;
      throw error;
    }

    available = true;
    if (!response.ok) {
      const error = new Error(data.error?.message || `Request failed (${response.status}). Please try again.`);
      error.code = data.error?.code || 'request_failed';
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function createProfile(role, payload) {
    const profile = await request(role === 'business' ? '/api/businesses' : '/api/teams', {
      method: 'POST', body: payload,
    });
    if (!profile.id || !profile.owner_token) throw new Error('The server did not return a usable owner identity.');
    writeStored(`profile:${role}`, JSON.stringify(profile));
    return profile;
  }

  const idPath = id => encodeURIComponent(String(id));
  const businessAction = (id, action, body = {}) => request(`/api/tasks/${idPath(id)}/${action}`, {
    method: 'POST', body, role: 'business',
  });

  window.Api = Object.freeze({
    async checkHealth() {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 5000);
      try {
        const health = await request('/health', { signal: controller.signal });
        available = health.status === 'ok';
      } catch (_) { available = false; }
      finally { window.clearTimeout(timeout); }
      return available;
    },
    isAvailable: () => available,
    getRole,
    setRole: role => writeStored('role', validRole(role)),
    getProfile,
    createBusiness: payload => createProfile('business', payload),
    createTeam: payload => createProfile('team', payload),
    createTask: draft => request('/api/tasks', {
      method: 'POST', role: 'business',
      body: { business_id: requireProfile('business').id, initial_draft: draft },
    }),
    getTask: id => request(`/api/tasks/${idPath(id)}`, {
      role: getRole() === 'business' && getProfile('business') ? 'business' : undefined,
    }),
    getCatalog(filters = {}) {
      const query = new URLSearchParams();
      for (const key of ['tags', 'industry', 'readiness', 'min_score', 'q', 'limit', 'offset']) {
        const value = filters[key];
        if (value !== undefined && value !== null && value !== '') {
          query.set(key, Array.isArray(value) ? value.join(',') : String(value));
        }
      }
      return request(`/api/catalog${query.size ? `?${query}` : ''}`);
    },
    getBusinessTasks: () => request(`/api/businesses/${idPath(requireProfile('business').id)}/tasks`, { role: 'business' }),
    submitAnswers: (id, answers) => businessAction(id, 'answers', { answers }),
    updateCard: (id, patch) => request(`/api/tasks/${idPath(id)}/card`, { method: 'PATCH', body: patch, role: 'business' }),
    confirmTask: id => businessAction(id, 'confirm'),
    publishTask: id => businessAction(id, 'publish'),
    getTaskProposals: id => request(`/api/tasks/${idPath(id)}/proposals`, { role: 'business' }),
    decideProposal: (id, decision) => request(`/api/proposals/${idPath(id)}/decision`, {
      method: 'PATCH', body: { decision }, role: 'business',
    }),
    submitProposal: (id, payload) => request(`/api/tasks/${idPath(id)}/proposals`, {
      method: 'POST', role: 'team', body: { ...payload, team_id: requireProfile('team').id },
    }),
    getTeamProposals: () => request(`/api/teams/${idPath(requireProfile('team').id)}/proposals`, { role: 'team' }),
  });
})();
