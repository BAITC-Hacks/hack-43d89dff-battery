/* Shared view primitives and the public marketplace. No framework or build step. */
(() => {
  'use strict';
  const root = document.getElementById('app-root');
  const dialog = document.getElementById('app-dialog');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const paths = {
    arrow: '<path d="M5 19 19 5M5 5h14v14"/>',
    arrowLeft: '<path d="m12 5-7 7 7 7M5 12h14"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    close: '<path d="m6 6 12 12M6 18 12 6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    building: '<path d="M4 21V5h10v16M14 11h6v10M2 21h20M8 9h2M8 13h2M8 17h2M17 15h1M17 18h1"/>',
    person: '<circle cx="12" cy="8" r="3"/><path d="M5 21v-3a7 7 0 0 1 14 0v3"/>'
  };
  const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true">${paths[name] || paths.arrow}</svg>`;
  const safeScore = evaluation => Math.max(0, Math.min(100, Number(evaluation?.score) || 0));
  const level = evaluation => { const score = safeScore(evaluation); return score >= 90 ? 'priority' : score >= 70 ? 'ready' : score >= 40 ? 'working' : 'draft'; };
  const levelNames = { priority: 'Priority brief', ready: 'Ready to build', working: 'Taking shape', draft: 'Early draft' };
  const readiness = evaluation => `<span class="status-badge ${level(evaluation)}">${levelNames[level(evaluation)]}</span>`;
  const state = { tasks: [], examples: false, hiddenExamples: false, error: '', filters: { q: '', industry: '', readiness: '', skill: '', sort: 'readiness' }, page: 0 };
  let routeVersion = 0;
  let toastTimer;
  let modalReturnFocus;
  let lastAuthenticatedId = null;

  function toast(message) {
    const target = document.getElementById('toast');
    clearTimeout(toastTimer);
    target.textContent = message;
    target.hidden = false;
    toastTimer = setTimeout(() => { target.hidden = true; }, 5000);
  }
  function modal(title, html) {
    if (!dialog.open) modalReturnFocus = document.activeElement;
    dialog.querySelector('#dialog-title').textContent = title;
    dialog.querySelector('.modal-body').innerHTML = html;
    if (!dialog.open) dialog.showModal();
    requestAnimationFrame(() => (dialog.querySelector('.modal-body input, .modal-body textarea, .modal-body button') || document.getElementById('close-dialog')).focus());
    return dialog;
  }
  function closeModal() { dialog.close(); }
  function navigate(hash) { if (window.location.hash === hash) route(); else window.location.hash = hash; }
  function refreshNavigation() {
    const business = window.Api.getRole() === 'business';
    const link = document.getElementById('workspace-link');
    const user = window.Api.getUser();
    document.getElementById('account-button').textContent = user ? 'My account' : 'Sign in';
    document.getElementById('account-role').textContent = user ? business ? 'Business' : 'Student' : '';
    document.getElementById('account-role').hidden = !user;
    link.href = business ? '#workspace' : '#proposals';
    link.innerHTML = `${business ? 'My workspace' : 'My proposals'}<span class="nav-index">03</span>`;
    const hash = window.location.hash.replace(/^#\/?/, '').split('/')[0] || 'catalog';
    document.querySelectorAll('[data-nav]').forEach(item => {
      const active = item.dataset.nav === hash || item.dataset.nav === 'workspace' && ['workspace', 'edit', 'create', 'proposals'].includes(hash);
      if (active) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
    });
  }
  function taskCard(task, index = 0) {
    const card = task.card || {}, evaluation = task.evaluation || {};
    const score = safeScore(evaluation);
    return `<a class="task-card ${level(evaluation) === 'priority' ? 'is-priority' : ''}" href="#task/${encodeURIComponent(task.id)}" aria-label="${escape(card.title || 'Untitled task')}, readiness ${score} out of 100">
      <div class="card-top"><span class="card-category">${escape(card.industry || 'Business challenge')}</span><span class="card-index">${String(index + 1).padStart(2, '0')} /</span></div>
      <h3>${escape(card.title || 'Untitled task')}</h3>
      <p class="card-company">${icon('building')}${escape(task.business_name || 'Business task')}</p>
      <p class="card-description">${escape(card.business_need || card.context || 'Open the brief to explore this business challenge.')}</p>
      <div class="tags">${(card.tags || []).slice(0, 3).map(tag => `<span class="tag">${escape(tag)}</span>`).join('')}</div>
      <div class="card-score"><span>Task readiness</span><b>${score}<small> / 100</small></b></div>
      <div class="score-track" aria-hidden="true"><div class="score-fill" style="--score:${score}%"></div></div>
      <div class="card-footer">${readiness(evaluation)}${icon('arrow')}</div>
    </a>`;
  }
  window.UI = { escape, icon, toast, modal, closeModal, navigate, taskCard, readiness, refreshNavigation };

  function hero() {
    return `<section class="hero" aria-labelledby="hero-title">
      <div class="hero-copy"><p class="eyebrow hero-kicker"><span class="signal-dot" aria-hidden="true"></span>A meeting point for business & bright minds</p>
        <h1 id="hero-title"><span>Real tasks.</span><span>Real <span class="outline-word" style="display:inline">impact.</span></span></h1>
        <div class="hero-bottom"><p class="hero-description">Put your skills to work on challenges that matter. Connect with businesses. Build something real.</p><a class="text-link" href="#challenge-index" data-explore>Find your challenge ${icon('arrow')}</a></div>
      </div>
      <div class="hero-art swiss-grid-pattern" aria-hidden="true"><div class="art-topline"><span>POTENTIAL → POSSIBILITY</span><span>FIG. 01</span></div><div class="art-geometry"><div class="art-ring"></div><div class="art-axis"></div><div class="art-arrow"></div></div><div class="art-caption"><span>GOOD IDEAS DESERVE A DIRECTION.</span><span class="art-caption-mark">↗</span></div></div>
    </section>
    <div class="principle-strip" aria-label="The Sana approach"><div class="principle"><strong>01</strong><span><b>Real business challenges</b>Meaningful problems. Practical experience.</span></div><div class="principle"><strong>100</strong><span><b>Points of clarity</b>Better briefs rise to the top.</span></div><div class="principle"><strong>↗</strong><span><b>Human connections</b>You propose. The business chooses.</span></div></div>`;
  }
  const callout = () => `<section class="business-callout swiss-dots"><div><p class="eyebrow"><span class="section-number">↗</span>FOR BUSINESSES</p><h2>A fresh perspective<br>starts with your challenge.</h2><p>Turn a rough idea into a clear brief. Connect with student teams ready to make a difference.</p></div><a class="btn btn-accent" href="#create">Post your first task ${icon('arrow')}</a></section>`;

  async function renderCatalog(version) {
    root.innerHTML = `${hero()}<section class="catalog-section" id="challenge-index" aria-labelledby="catalog-title"><div class="catalog-heading"><div><p class="eyebrow"><span class="section-number">01</span>THE OPPORTUNITY INDEX</p><h2 id="catalog-title">Find your next challenge.</h2></div><label class="catalog-search"><span class="sr-only">Search tasks</span><input type="search" id="catalog-search" placeholder="Search ideas, skills, possibilities…" value="${escape(state.filters.q)}">${icon('search')}</label></div><div id="industry-tabs" class="industry-tabs" aria-label="Filter by industry"></div><div class="catalog-layout"><aside class="catalog-sidebar" aria-label="Filter challenges"><div class="filter-group"><p class="eyebrow">Task readiness</p><div class="readiness-filters">${[['','All readiness','0—100'],['priority','Priority','90—100'],['ready','Ready','70—89'],['working','Working','40—69'],['draft','Draft','0—39']].map(([value, label, range]) => `<label class="filter-option"><input type="radio" name="readiness" value="${value}" ${state.filters.readiness === value ? 'checked' : ''}><span>${label}</span><small>${range}</small></label>`).join('')}</div></div><div class="filter-group"><label class="eyebrow" for="skill-filter">Your area of interest</label><select id="skill-filter" class="filter-skill"><option value="">All skills</option></select></div><div class="readiness-note swiss-diagonal"><div class="big-plus" aria-hidden="true">+</div><h3>Clarity creates<br>possibility.</h3><p>A task’s score reflects how clearly it’s defined. More detail. Less guesswork. A better starting point.</p><a class="text-link" href="#readiness">About the score ${icon('arrow')}</a></div></aside><div><div class="catalog-meta"><span id="results-count" role="status" aria-live="polite">Loading opportunities…</span><label class="sort-control">Sort by <select id="sort-select"><option value="readiness">Highest readiness</option><option value="newest">Newest first</option><option value="title">Title A–Z</option></select></label></div><div id="catalog-notice"></div><div class="task-grid" id="task-grid" aria-busy="true"><div class="loading-state" role="status">Finding your next challenge…</div></div><div id="catalog-pagination" class="catalog-pagination"></div></div></div></section>${callout()}`;
    root.querySelector('[data-explore]').addEventListener('click', event => { event.preventDefault(); root.querySelector('#challenge-index').scrollIntoView({ behavior: 'smooth' }); root.querySelector('#catalog-search').focus({ preventScroll: true }); });
    root.querySelector('#catalog-search').addEventListener('input', event => { state.filters.q = event.target.value; state.page = 0; updateResults(); });
    root.querySelectorAll('[name="readiness"]').forEach(input => input.addEventListener('change', event => { state.filters.readiness = event.target.value; state.page = 0; updateResults(); }));
    root.querySelector('#skill-filter').addEventListener('change', event => { state.filters.skill = event.target.value; state.page = 0; updateResults(); });
    const sort = root.querySelector('#sort-select');
    sort.value = state.filters.sort;
    sort.addEventListener('change', event => { state.filters.sort = event.target.value; state.page = 0; updateResults(); });
    state.error = '';
    try {
      let response = await window.Api.getCatalog({ limit: 100 });
      let tasks = response.items || [];
      while (tasks.length < response.total && response.items.length && version === routeVersion) {
        response = await window.Api.getCatalog({ limit: 100, offset: tasks.length });
        tasks = tasks.concat(response.items || []);
      }
      if (version !== routeVersion) return;
      state.tasks = tasks;
      state.examples = !tasks.length;
    } catch (error) {
      if (version !== routeVersion) return;
      state.tasks = [];
      state.examples = true;
      state.error = error.message;
    }
    if (state.examples && !state.hiddenExamples) state.tasks = window.ExampleTasks;
    populateFilters();
    updateResults();
  }
  function populateFilters() {
    const industries = [...new Set(state.tasks.map(task => task.card?.industry).filter(Boolean))].sort();
    const skills = [...new Set(state.tasks.flatMap(task => task.card?.tags || []))].sort();
    if (state.filters.industry && !industries.includes(state.filters.industry)) state.filters.industry = '';
    if (state.filters.skill && !skills.includes(state.filters.skill)) state.filters.skill = '';
    root.querySelector('#industry-tabs').innerHTML = ['', ...industries].map(industry => `<button class="industry-tab" type="button" data-industry="${escape(industry)}" aria-pressed="${state.filters.industry === industry}">${escape(industry || 'All industries')}</button>`).join('');
    root.querySelectorAll('[data-industry]').forEach(button => button.addEventListener('click', () => { state.filters.industry = button.dataset.industry; state.page = 0; root.querySelectorAll('[data-industry]').forEach(tab => tab.setAttribute('aria-pressed', String(tab === button))); updateResults(); }));
    const skill = root.querySelector('#skill-filter');
    skill.innerHTML = `<option value="">All skills</option>${skills.map(value => `<option value="${escape(value)}">${escape(value)}</option>`).join('')}`;
    skill.value = state.filters.skill;
  }
  function resetFilters() {
    state.filters = { q: '', industry: '', readiness: '', skill: '', sort: 'readiness' };
    state.page = 0;
    root.querySelector('#catalog-search').value = '';
    root.querySelector('[name="readiness"][value=""]').checked = true;
    root.querySelector('#sort-select').value = 'readiness';
    populateFilters(); updateResults();
  }
  function updateResults() {
    const grid = root.querySelector('#task-grid');
    if (!grid) return;
    const filters = state.filters;
    const query = filters.q.trim().toLocaleLowerCase();
    const tasks = state.tasks.filter(task => {
      const card = task.card || {};
      const searchable = [card.title, card.context, card.business_need, card.expected_result, card.industry, task.business_name, ...(card.tags || []), ...(card.required_skills || [])].join(' ').toLocaleLowerCase();
      return (!query || searchable.includes(query)) && (!filters.industry || card.industry === filters.industry) && (!filters.readiness || level(task.evaluation) === filters.readiness) && (!filters.skill || (card.tags || []).includes(filters.skill));
    }).sort((a,b) => filters.sort === 'title' ? (a.card?.title || '').localeCompare(b.card?.title || '') : filters.sort === 'newest' ? (b.published_at || '').localeCompare(a.published_at || '') : safeScore(b.evaluation) - safeScore(a.evaluation) || (b.published_at || '').localeCompare(a.published_at || ''));
    const pageSize = 6;
    const totalPages = Math.max(1, Math.ceil(tasks.length / pageSize));
    state.page = Math.min(state.page, totalPages - 1);
    root.querySelector('#results-count').innerHTML = `<strong>${String(tasks.length).padStart(2, '0')}</strong> ${state.examples ? 'example ' : ''}${tasks.length === 1 ? 'challenge' : 'challenges'} to explore`;
    root.querySelector('#catalog-notice').innerHTML = state.examples ? `<div class="example-notice"><span><strong>${state.error ? 'Preview mode.' : 'An open space for new ideas.'}</strong> ${state.error ? 'The marketplace is unavailable. ' : 'No live tasks yet. '}${state.hiddenExamples ? 'Example briefs are hidden.' : 'These fictional briefs show what’s possible.'}</span><button type="button" id="toggle-examples">${state.hiddenExamples ? 'Show examples' : 'Hide examples'}</button></div>` : '';
    root.querySelector('#toggle-examples')?.addEventListener('click', () => { state.hiddenExamples = !state.hiddenExamples; state.tasks = state.hiddenExamples ? [] : window.ExampleTasks; resetFilters(); });
    grid.setAttribute('aria-busy', 'false');
    grid.innerHTML = tasks.length ? tasks.slice(state.page * pageSize, (state.page + 1) * pageSize).map((task,index) => taskCard(task, state.page * pageSize + index)).join('') : `<div class="empty-state"><p class="eyebrow">ROOM FOR POSSIBILITY</p><h3>${state.tasks.length ? 'No matches. New possibilities.' : 'The next challenge could be yours.'}</h3><p>${state.tasks.length ? 'Try another search or clear your filters to explore all the challenges.' : 'Publish a clear business brief and give student teams a meaningful problem to solve.'}</p>${state.tasks.length ? '<button class="btn" type="button" id="clear-filters">Clear filters</button>' : '<a class="btn btn-primary" href="#create">Post a task ↗</a>'}</div>`;
    root.querySelector('#clear-filters')?.addEventListener('click', resetFilters);
    const pagination = root.querySelector('#catalog-pagination');
    pagination.innerHTML = totalPages > 1 ? `<button class="btn btn-small" id="previous-page" ${state.page === 0 ? 'disabled' : ''}>Previous</button><span>Page ${state.page + 1} / ${totalPages}</span><button class="btn btn-small" id="next-page" ${state.page + 1 === totalPages ? 'disabled' : ''}>Next</button>` : '';
    pagination.querySelector('#previous-page')?.addEventListener('click', () => { state.page--; updateResults(); grid.scrollIntoView({ block: 'start' }); });
    pagination.querySelector('#next-page')?.addEventListener('click', () => { state.page++; updateResults(); grid.scrollIntoView({ block: 'start' }); });
  }

  async function renderDetail(id, version) {
    root.innerHTML = '<div class="loading-state" role="status">Opening the task brief…</div>';
    try {
      const task = window.ExampleTasks.find(item => item.id === id) || await window.Api.getTask(id);
      if (version !== routeVersion) return;
      task.business_name ||= state.tasks.find(item => item.id === task.id)?.business_name;
      const card = task.card || {}, evaluation = task.evaluation || {};
      const list = value => Array.isArray(value) ? value : [];
      const section = (title, body) => `<section class="detail-section"><h2>${title}</h2>${body}</section>`;
      const text = value => `<p class="preserve-lines">${escape(value || 'To be clarified with the business.')}</p>`;
      const bullets = values => list(values).length ? `<ul class="detail-list">${values.map(value => `<li>${escape(value)}</li>`).join('')}</ul>` : text(null);
      const owned = !task.is_example && task.business_id === window.Api.getProfile('business')?.id && window.Api.getRole() === 'business';
      root.innerHTML = `<header class="page-header"><a class="text-link" href="#catalog">${icon('arrowLeft')} Back to challenges</a><p class="eyebrow" style="margin-top:28px">${escape(card.industry || 'BUSINESS CHALLENGE')} / ${task.is_example ? 'EXAMPLE BRIEF' : 'PUBLIC TASK'}</p><h1 class="page-title">${escape(card.title || 'Business challenge')}</h1><div class="task-detail-heading"><span>${escape(task.business_name || 'Business task')}</span>${readiness(evaluation)}</div></header>${task.is_example ? '<div class="example-notice"><span><strong>Illustrative brief.</strong> This fictional task and its score are for preview only. Proposals open when a business publishes a real task.</span></div>' : ''}<div class="workspace-layout"><article>${section('01 / The challenge', text(card.business_need))}${section('02 / The context', text(card.context))}${section('03 / What you’ll build', text(card.expected_result))}${section('04 / Who it’s for', bullets(card.target_users))}${section('05 / Skills you’ll bring', bullets(card.required_skills))}${section('06 / Data & materials', `${text(card.available_data?.description)}<div class="data-row"><span>Sources</span><span>${escape(list(card.available_data?.sources).join(', ') || 'Not specified')}</span></div><div class="data-row"><span>Access</span><span>${escape(card.available_data?.access_conditions || 'Not specified')}</span></div>`)}${section('07 / What success looks like', list(card.success_criteria).length ? card.success_criteria.map(item => `<div class="panel stack" style="margin-bottom:12px"><h3>${escape(item.metric || 'Metric to be defined')}</h3><p>Target: ${escape(item.target || 'To be defined')}</p><p>How it’s checked: ${escape(item.verification_method || 'To be defined')}</p></div>`).join('') : text(null))}${section('08 / Boundaries', bullets(card.limitations))}${section('09 / Working together', `<div class="data-row"><span>Business contact</span><span>${escape([card.business_contact?.name, card.business_contact?.role].filter(Boolean).join(' · ') || 'Not specified')}</span></div>${card.business_contact?.email ? `<div class="data-row"><span>Email</span><span>${escape(card.business_contact.email)}</span></div>` : ''}<div class="data-row"><span>Communication</span><span>${escape(card.interaction_format?.channel || 'Not specified')}</span></div><div class="data-row"><span>Frequency</span><span>${escape(card.interaction_format?.frequency || 'Not specified')}</span></div>${text(card.interaction_format?.feedback_process)}`)}</article><aside class="panel detail-score-panel swiss-grid-pattern"><p class="eyebrow">TASK READINESS</p><div class="score-number">${safeScore(evaluation)}<small> / 100</small></div><div class="score-track"><div class="score-fill" style="--score:${safeScore(evaluation)}%"></div></div><p>A clearer brief means a stronger starting point. This score measures the task’s completeness.</p><a class="text-link" href="#readiness">How scoring works ${icon('arrow')}</a><div class="detail-section" style="margin-top:25px"><div class="tags">${list(card.tags).map(tag => `<span class="tag">${escape(tag)}</span>`).join('')}</div></div>${task.is_example ? '<a class="btn btn-primary" href="#create">Create a real task ↗</a>' : owned ? `<a class="btn btn-primary" href="#edit/${encodeURIComponent(task.id)}">${task.status === 'published' ? 'Review proposals' : 'Continue editing'} ↗</a>` : task.status === 'published' ? `<button class="btn btn-accent" type="button" id="send-proposal">Propose a solution ${icon('arrow')}</button><p>Your approach. Your team. The business makes the final selection.</p>` : '<p>This task has not been published.</p>'}</aside></div>`;
      root.querySelector('#send-proposal')?.addEventListener('click', () => window.Workspace.showProposal(task));
    } catch (error) {
      if (version !== routeVersion) return;
      root.innerHTML = `<header class="page-header"><p class="eyebrow">TASK BRIEF</p><h1 class="page-title">A missing connection.</h1></header><div class="empty-state"><p role="alert">${escape(error.message)}</p><a class="btn btn-primary" href="#catalog">Back to challenges</a></div>`;
    }
  }
  function renderMethod() {
    root.innerHTML = `<header class="page-header"><p class="eyebrow"><span class="section-number">02</span>HOW IT WORKS</p><h1 class="page-title">From a real problem.<br>To a shared possibility.</h1><p class="page-description">A good collaboration starts with a clear brief. Sana helps businesses define the work and student teams find a meaningful place to contribute.</p></header><div class="method-grid"><section class="method-card"><div class="method-number">01.</div><h2>Make it clear.</h2><p>Businesses describe a challenge in their own words. Focused questions turn the idea into an editable task card, with a readiness score that makes missing details visible.</p></section><section class="method-card swiss-dots"><div class="method-number">02.</div><h2>Find your fit.</h2><p>Student teams explore published briefs, filter by skills and industry, and submit a proposal with their approach. Better-defined briefs appear higher in the catalog.</p></section><section class="method-card"><div class="method-number">03.</div><h2>Choose to build.</h2><p>The business reviews each proposal and manually accepts a team. Clear expectations and a direct point of contact give the collaboration a solid foundation.</p></section></div><div class="workspace-layout"><div><p class="eyebrow">A NOTE ON READINESS</p><h2 class="page-title" style="font-size:48px">Clarity earns<br>its place.</h2><p class="page-description">The score belongs to the task. It reflects the information a team needs to get started: the problem, the materials, the outcome, and how you’ll work together.</p><a class="text-link" href="#readiness">Explore the scoring system ${icon('arrow')}</a></div><aside class="panel stack"><p class="eyebrow">TAKE THE FIRST STEP</p><a class="btn btn-primary" href="#catalog">Explore challenges ${icon('arrow')}</a><a class="btn" href="#create">Post a task ${icon('plus')}</a></aside></div>${callout()}`;
  }
  function renderReadiness() {
    const weights = [['Context & business need',20],['Data & materials',20],['Expected result',15],['Success criteria',15],['Limitations',10],['Target users',10],['Contact & interaction',10]];
    root.innerHTML = `<header class="page-header"><p class="eyebrow">THE READINESS SYSTEM</p><h1 class="page-title">Better defined.<br>Better positioned.</h1><p class="page-description">Every task starts with a possibility. Its readiness score shows how much of the brief is clear, on a consistent scale from 0 to 100.</p></header><div class="workspace-layout"><section><h2 class="panel-title">Seven areas. One clearer brief.</h2><table class="readiness-table"><caption class="sr-only">Task readiness scoring weights</caption><thead><tr><th scope="col">What makes a task ready</th><th scope="col">Points</th></tr></thead><tbody>${weights.map(([name,score]) => `<tr><td>${name}</td><td>${score}</td></tr>`).join('')}<tr><th scope="row">Total</th><td>100</td></tr></tbody></table></section><aside class="panel stack swiss-grid-pattern"><p class="eyebrow">WHAT THE NUMBER MEANS</p><h2 class="panel-title">Less guesswork.<br>A stronger start.</h2><p>The score measures the completeness of task details. The business reviews the facts and confirms the brief before publishing.</p><p class="muted">Higher scores appear first in the catalog. Any confirmed task can be published, whatever its score.</p><a class="btn btn-primary" href="#create">Build your brief ${icon('arrow')}</a></aside></div><div class="readiness-levels">${[['0–39','Draft'],['40–69','Working'],['70–89','Ready'],['90–100','Priority']].map(([range,name]) => `<div><strong>${range}</strong><span class="eyebrow">${name}</span></div>`).join('')}</div>`;
  }
  async function route() {
    const version = ++routeVersion;
    const [name = 'catalog', encodedId] = (window.location.hash.replace(/^#\/?/, '') || 'catalog').split('/');
    let id;
    try { id = decodeURIComponent(encodedId || ''); } catch (_) { id = ''; }
    if (dialog.open) closeModal();
    refreshNavigation();
    document.querySelector('.main-nav').classList.remove('is-open');
    document.getElementById('mobile-menu').setAttribute('aria-expanded', 'false');
    window.scrollTo({ top: 0, behavior: 'instant' });
    const titles = { catalog: 'Real tasks. Real impact.', 'how-it-works': 'How it works', readiness: 'Task readiness', create: 'Post a task', workspace: 'Your workspace', edit: 'Your task studio', proposals: 'Your proposals', task: 'The task brief' };
    document.title = `Sana — ${titles[name] || titles.catalog}`;
    if (name === 'task') await renderDetail(id, version);
    else if (name === 'how-it-works') renderMethod();
    else if (name === 'readiness') renderReadiness();
    else if (['create','edit','workspace','proposals'].includes(name)) await window.Workspace.render(root, name, id);
    else await renderCatalog(version);
    if (version === routeVersion && !dialog.open) document.getElementById('main-content').focus({ preventScroll: true });
  }

  document.querySelector('.skip-link').addEventListener('click', event => {
    event.preventDefault();
    document.getElementById('main-content').focus();
  });
  document.getElementById('close-dialog').addEventListener('click', closeModal);
  dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeModal(); } });
  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    dialog.querySelectorAll('input[autocomplete="current-password"], input[autocomplete="new-password"]').forEach(input => { input.value = ''; input.removeAttribute('value'); });
    if (modalReturnFocus?.isConnected) modalReturnFocus.focus({ preventScroll: true });
  });
  document.getElementById('mobile-menu').addEventListener('click', event => { const open = document.querySelector('.main-nav').classList.toggle('is-open'); event.currentTarget.setAttribute('aria-expanded', String(open)); event.currentTarget.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation'); });
  document.getElementById('account-button').addEventListener('click', () => {
    if (window.Api.getUser()) { window.Auth.showAccount(); return; }
    const page = window.location.hash.replace(/^#\/?/, '').split('/')[0];
    const preserveForm = ['create', 'edit'].includes(page) && !!root.querySelector('form');
    window.Auth.show({ role: ['create', 'edit', 'workspace'].includes(page) ? 'business' : 'team', ...(preserveForm ? { afterSuccess: () => {} } : {}) });
  });
  window.addEventListener('hashchange', route);
  window.addEventListener('sessionchange', event => {
    refreshNavigation();
    const reason = event.detail?.reason;
    const user = window.Api.getUser();
    if (reason === 'logout') {
      lastAuthenticatedId = null;
      routeVersion++;
      root.innerHTML = '<div class="loading-state" role="status">Signing out…</div>';
      closeModal();
      navigate('#catalog');
    } else if (reason === 'switch') {
      lastAuthenticatedId = null;
      route();
    } else if (reason === 'expired') {
      toast('Your session has ended. Sign in again to continue.');
    } else if (user) {
      const changed = lastAuthenticatedId && lastAuthenticatedId !== user.id;
      lastAuthenticatedId = user.id;
      if (changed && /#\/?(workspace|proposals|edit)/.test(window.location.hash)) route();
    }
  });
  (async () => {
    try { await window.Api.initSession(); }
    catch (_) { /* Public browsing still works when session restoration is unavailable. */ }
    await route();
  })();
})();
