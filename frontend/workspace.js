/* Business and team workflows. All mutations go through the marketplace API. */
(() => {
    'use strict';

    let renderVersion = 0;
    window.addEventListener('hashchange', () => { renderVersion += 1; });
    window.addEventListener('sessionchange', event => { if (['logout', 'switch'].includes(event.detail?.reason)) renderVersion += 1; });
    const e = value => window.UI.escape(value == null ? '' : String(value));
    const list = value => Array.isArray(value) ? value : [];
    const lines = value => String(value || '').split('\n').map(item => item.trim()).filter(Boolean);
    const words = value => String(value || '').split(',').map(item => item.trim()).filter(Boolean);
    const statusLabel = value => ({ awaiting_answers: 'Questions to answer', card_ready: 'Ready to review', confirmed: 'Confirmed', published: 'Published', submitted: 'Under review', accepted: 'Accepted', rejected: 'Not selected' }[value] || value);
    const field = (label, name, value = '', options = {}) => {
        const attrs = `name="${e(name)}" ${options.required ? 'required' : ''} ${options.max ? `maxlength="${Number(options.max)}"` : ''} ${options.placeholder ? `placeholder="${e(options.placeholder)}"` : ''}`;
        return `<label class="field${options.wide ? ' field-wide' : ''}"><span>${e(label)}${options.optional ? ' <small>(optional)</small>' : ''}</span>${options.area ? `<textarea ${attrs} rows="${options.rows || 3}">${e(value)}</textarea>` : `<input ${attrs} type="${options.type || 'text'}" value="${e(value)}">`}${options.hint ? `<small class="muted">${e(options.hint)}</small>` : ''}</label>`;
    };
    const heading = (number, title, description, action = '') => `<header class="page-header"><div><p class="eyebrow">${e(number)} / YOUR WORKSPACE</p><h1 class="page-title">${e(title)}</h1><p class="page-description">${e(description)}</p></div>${action}</header>`;
    const errorBox = () => '<p class="error-message" role="alert" hidden></p>';
    const steps = current => `<ol class="steps" aria-label="Task publishing progress">${['Describe', 'Clarify', 'Review', 'Publish'].map((name, index) => `<li class="step${index === current ? ' is-active' : ''}"${index === current ? ' aria-current="step"' : ''}><span>${String(index + 1).padStart(2, '0')}</span> ${name}</li>`).join('')}</ol>`;
    function formError(form, message) {
        const target = form.querySelector('.error-message');
        if (!target) return;
        target.textContent = message;
        target.hidden = !message;
    }
    async function busy(form, button, label, action) {
        if (form.dataset.busy) return;
        form.dataset.busy = 'true';
        form.setAttribute('aria-busy', 'true');
        formError(form, '');
        const previous = button ? button.innerHTML : '';
        const controls = Array.from(form.querySelectorAll('button, input, textarea, select')).map(control => [control, control.disabled]);
        controls.forEach(([control]) => { control.disabled = true; });
        if (button) button.textContent = label;
        try { await action(); }
        catch (error) {
            formError(form, error.message || 'Something went wrong. Please try again.');
            if ((error.status === 401 || error.code === 'authentication_required') && form.isConnected && !form.closest('dialog')) {
                window.Auth.require('business', () => {
                    if (form.isConnected) formError(form, '');
                    window.UI.toast('Signed in. Your changes are still here; try the action again.');
                });
            }
        }
        finally {
            delete form.dataset.busy;
            form.removeAttribute('aria-busy');
            controls.forEach(([control, wasDisabled]) => { control.disabled = wasDisabled; });
            if (button) button.innerHTML = previous;
        }
    }
    function showProfile(role = window.Api.getRole() || 'team', afterSave) {
        window.Auth.require(role, afterSave);
    }

    async function render(root, route, id) {
        const version = ++renderVersion;
        const current = () => version === renderVersion && root.isConnected;
        const requiredRole = route === 'proposals' ? 'team' : 'business';
        const showGate = () => window.Auth.renderGate(root, requiredRole, () => render(root, route, id));
        root.innerHTML = '<div class="empty-state" role="status"><p class="eyebrow">YOUR WORKSPACE</p><h2>Loading…</h2></div>';
        try {
            if (window.Api.getUser() && window.Api.getRole() !== requiredRole || route !== 'create' && !window.Api.getUser()) {
                showGate();
                return;
            }
            if (route === 'create') { renderCreate(root); return; }
            if (route === 'workspace') {
                const profile = window.Api.getProfile('business');
                if (!profile) throw new Error('Your account has no linked business profile. Sign out and sign in again.');
                const tasks = await window.Api.getBusinessTasks();
                if (current()) {
                    if (!window.Api.getUser()) showGate();
                    else renderTaskList(root, tasks, profile);
                }
            } else if (route === 'edit') {
                const task = await window.Api.getTask(id);
                if (!current()) return;
                const profile = window.Api.getProfile('business');
                if (!profile || task.business_id !== profile.id) throw new Error('This task belongs to another business. Open your workspace to manage your own tasks.');
                renderOwnedTask(root, task);
            } else if (route === 'proposals') {
                const profile = window.Api.getProfile('team');
                if (!profile) throw new Error('Your account has no linked team profile. Sign out and sign in again.');
                const proposals = await window.Api.getTeamProposals();
                if (current()) {
                    if (!window.Api.getUser()) showGate();
                    else await renderTeamProposals(root, proposals, current);
                }
            }
        } catch (error) {
            if (!current()) return;
            if (error.status === 401 || !window.Api.getUser()) { showGate(); return; }
            root.innerHTML = `${heading('02', 'Let’s try again.', 'Your work stays with your workspace.')}<section class="panel stack"><p class="error-message" role="alert">${e(error.message)}</p><div class="inline-actions"><button class="btn btn-primary" data-retry>Try again</button><a class="btn" href="#catalog">Explore tasks</a></div></section>`;
            root.querySelector('[data-retry]').addEventListener('click', () => render(root, route, id));
        }
    }
    function renderCreate(root, initialDraft = '') {
        root.innerHTML = `${heading('02', 'Start with a problem.', 'You bring the challenge. We help you make it clear.')} ${steps(0)}<div class="workspace-layout"><section class="panel"><form class="stack" id="draft-form"><div><p class="eyebrow">01 / THE STARTING POINT</p><h2 class="panel-title">What could work better?</h2><p class="muted">Describe the problem in your own words. Kazakh, Russian, English, or a mix — all welcome.</p></div>${field('Your business challenge', 'initial_draft', '', { area: true, rows: 9, required: true, max: 12000, placeholder: 'We run a local business, and we want to improve…' })}<div class="data-row"><span class="muted">A rough idea is enough to begin.</span><span class="muted" data-count>0 / 12,000</span></div>${errorBox()}<div class="form-actions"><button class="btn btn-primary" type="submit">Clarify my task ${window.UI.icon('arrow')}</button><a class="text-link" href="#workspace">Back to workspace</a></div></form></section><aside class="panel stack"><p class="eyebrow">A CLEARER PATH</p><h2 class="panel-title">Small details.<br>Better outcomes.</h2><div class="detail-section"><h3>01 / Describe</h3><p class="muted">Start with the issue your business needs to solve.</p></div><div class="detail-section"><h3>02 / Clarify</h3><p class="muted">Answer a few focused questions to fill in the gaps.</p></div><div class="detail-section"><h3>03 / Review & publish</h3><p class="muted">Edit your task card, check its readiness, then publish when you choose.</p></div><p class="muted">You review every proposal and choose your team.</p></aside></div>`;
        const form = root.querySelector('form');
        const draft = form.elements.initial_draft;
        draft.value = initialDraft;
        form.querySelector('[data-count]').textContent = `${draft.value.length.toLocaleString()} / 12,000`;
        draft.addEventListener('input', () => { form.querySelector('[data-count]').textContent = `${draft.value.length.toLocaleString()} / 12,000`; });
        form.addEventListener('submit', event => {
            event.preventDefault();
            if (!draft.value.trim()) { formError(form, 'Describe your challenge before continuing.'); draft.focus(); return; }
            const create = () => busy(form, form.querySelector('[type="submit"]'), 'Preparing your questions…', async () => {
                const task = await window.Api.createTask(draft.value.trim());
                if (form.isConnected) window.UI.navigate(`#edit/${encodeURIComponent(task.id)}`);
            });
            const savedDraft = draft.value;
            window.Auth.require('business', () => {
                if (form.isConnected) create();
                else if (/^#\/?create$/.test(window.location.hash)) {
                    renderCreate(root, savedDraft);
                    root.querySelector('#draft-form').requestSubmit();
                }
            });
        });
    }
    function renderTaskList(root, tasks, profile) {
        root.innerHTML = `${heading('02', 'Your task studio.', `A home for ${profile.name}’s challenges, from first thought to first collaboration.`, `<a class="btn btn-primary" href="#create">New task ${window.UI.icon('plus')}</a>`)}<section class="stack">${tasks.length ? tasks.map((task, index) => `<article class="panel workspace-task"><div><p class="eyebrow">${String(index + 1).padStart(2, '0')} / <span class="status-badge">${e(statusLabel(task.status))}</span></p><h2 class="panel-title">${e(task.card?.title || task.initial_draft?.slice(0, 100) || 'Untitled task')}</h2><p class="muted">${e(task.card?.business_need || (task.status === 'awaiting_answers' ? 'Answer the clarification questions to build your task card.' : 'Review the details and take the next step.'))}</p></div><div class="stack">${task.evaluation ? window.UI.readiness(task.evaluation) : '<span class="muted">Not scored yet</span>'}<a class="btn" href="#edit/${encodeURIComponent(task.id)}">${task.status === 'published' ? 'View proposals' : 'Continue task'} ${window.UI.icon('arrow')}</a></div></article>`).join('') : '<div class="panel empty-state"><p class="eyebrow">A BLANK PAGE. A GOOD START.</p><h2>Your first challenge goes here.</h2><p class="muted">Turn a business problem into a task student teams can act on.</p><a class="btn btn-primary" href="#create">Create a task</a></div>'}</section>`;
    }
    function renderOwnedTask(root, task) {
        if (task.status === 'awaiting_answers' || !task.card) renderQuestions(root, task);
        else if (task.status === 'published') renderPublished(root, task);
        else renderEditor(root, task);
        const title = root.querySelector('h1');
        if (title) {
            title.tabIndex = -1;
            title.focus({ preventScroll: true });
        }
    }
    function renderQuestions(root, task) {
        const questions = list(task.clarifying_questions);
        const prior = list(task.answers);
        root.innerHTML = `${heading('02', 'Fill in the picture.', 'A few focused answers make your task easier to understand and act on.')} ${steps(1)}<div class="workspace-layout"><section class="panel"><form class="stack" id="answers-form"><p class="eyebrow">02 / MAKE IT SPECIFIC</p><p class="muted">Answer at least three questions. If a detail is unknown, say so — you can refine the card later.</p>${questions.map((question, index) => {
            const answer = prior.find(item => item && typeof item === 'object' && item.question === question)?.answer || (typeof prior[index] === 'string' ? prior[index] : '');
            return field(`${String(index + 1).padStart(2, '0')} / ${question}`, `answer_${index}`, answer, { area: true, max: 8000, placeholder: 'Add the details your team will need…' });
        }).join('')}<p class="muted" data-answer-count aria-live="polite">0 of ${questions.length} answered · at least 3 needed</p>${errorBox()}<div class="form-actions"><button class="btn btn-primary" type="submit">Build task card ${window.UI.icon('arrow')}</button><a href="#workspace" class="text-link">Back to workspace</a></div><p class="muted">Your task has been saved. Submit your answers to save this step.</p></form></section><aside class="panel stack"><p class="eyebrow">YOUR STARTING POINT</p><h2 class="panel-title">The original idea.</h2><p class="preserve-lines">${e(task.initial_draft)}</p><p class="muted">Your answers take priority when the task card is created. Review the generated card before publishing.</p></aside></div>`;
        const form = root.querySelector('form');
        const answers = () => questions.map((question, index) => ({ question, answer: form.elements[`answer_${index}`].value.trim() })).filter(item => item.answer);
        const updateCount = () => { form.querySelector('[data-answer-count]').textContent = `${answers().length} of ${questions.length} answered · at least 3 needed`; };
        form.addEventListener('input', updateCount);
        updateCount();
        form.addEventListener('submit', event => {
            event.preventDefault();
            const values = answers();
            if (values.length < 3) { formError(form, 'Please answer at least three questions to build your task card.'); return; }
            busy(form, form.querySelector('[type="submit"]'), 'Building your task card…', async () => {
                const updated = await window.Api.submitAnswers(task.id, values);
                if (form.isConnected) { renderOwnedTask(root, updated); window.scrollTo({ top: 0, behavior: 'instant' }); }
            });
        });
    }
    function scorePanel(task) {
        const evaluation = task.evaluation || {};
        const score = Math.max(0, Math.min(100, Number(evaluation.score) || 0));
        const suggestions = list(evaluation.improvement_suggestions);
        return `<aside class="panel readiness-panel stack"><p class="eyebrow">TASK READINESS</p><div><span class="score-number">${score}</span><span class="muted"> / 100</span></div>${window.UI.readiness(evaluation)}<div class="score-track" role="meter" aria-label="Task readiness" aria-valuenow="${score}" aria-valuemin="0" aria-valuemax="100"><span class="score-fill" style="width:${score}%"></span></div><p class="muted">Clearer task details earn a higher score and a better position in the catalog.</p><div class="stack">${list(evaluation.breakdown).map(item => `<div class="score-criterion"><div class="data-row"><span>${e(item.label)}</span><strong>${Number(item.score) || 0}/${Number(item.max_score) || 0}</strong></div><p class="muted">${e(item.explanation)}</p></div>`).join('')}</div>${suggestions.length ? `<div class="detail-section"><h3>Ways to improve</h3><ul class="detail-list">${suggestions.map(item => `<li>${e(item)}</li>`).join('')}</ul></div>` : '<p class="muted">All readiness areas are complete. Review the facts before publishing.</p>'}<p class="muted">The score reflects completeness. It does not verify the accuracy of your task.</p></aside>`;
    }
    function criterionFields(criterion = {}) {
        return `<div class="criterion-row panel stack"><div class="form-grid">${field('Metric', 'criterion_metric', criterion.metric, { placeholder: 'What will you measure?' })}${field('Target', 'criterion_target', criterion.target, { placeholder: 'What result is enough?' })}${field('Verification method', 'criterion_verification', criterion.verification_method, { wide: true, placeholder: 'How will you check the result?' })}</div><button class="text-link" type="button" data-remove-criterion>Remove criterion</button></div>`;
    }
    function editorFields(card) {
        const data = card.available_data || {}, contact = card.business_contact || {}, interaction = card.interaction_format || {};
        return `<section class="stack"><div><p class="eyebrow">01 / THE BRIEF</p><h2 class="panel-title">Make the challenge clear.</h2></div><div class="form-grid">${field('Task title', 'title', card.title, { required: true, wide: true, max: 200 })}${field('Industry', 'industry', card.industry, { placeholder: 'e.g. Retail' })}${field('Discovery tags', 'tags', list(card.tags).join(', '), { hint: 'Separate tags with commas.' })}${field('Business context', 'context', card.context, { area: true, wide: true })}${field('Business need', 'business_need', card.business_need, { area: true, wide: true })}${field('Expected result', 'expected_result', card.expected_result, { area: true, wide: true, hint: 'Describe the deliverable your team will produce.' })}${field('Target users', 'target_users', list(card.target_users).join('\n'), { area: true, hint: 'One user group per line.' })}${field('Required skills', 'required_skills', list(card.required_skills).join('\n'), { area: true, hint: 'One skill per line.' })}</div></section><section class="detail-section stack"><div><p class="eyebrow">02 / THE RESOURCES</p><h2 class="panel-title">Set the team up to work.</h2></div><div class="form-grid">${field('Available data & materials', 'data_description', data.description, { area: true, wide: true })}${field('Data sources', 'data_sources', list(data.sources).join('\n'), { area: true, hint: 'One source per line.' })}${field('Access conditions', 'data_access', data.access_conditions, { area: true, placeholder: 'How can the team access these materials?' })}${field('Limitations', 'limitations', list(card.limitations).join('\n'), { area: true, wide: true, hint: 'One constraint per line. Include scope, time, privacy, or budget limits.' })}</div></section><section class="detail-section stack"><div><p class="eyebrow">03 / THE OUTCOME</p><h2 class="panel-title">Define what success means.</h2></div><div class="stack" data-criteria>${(list(card.success_criteria).length ? card.success_criteria : [{}]).map(criterionFields).join('')}</div><div><button class="btn btn-small" type="button" data-add-criterion>${window.UI.icon('plus')} Add success criterion</button></div></section><section class="detail-section stack"><div><p class="eyebrow">04 / THE COLLABORATION</p><h2 class="panel-title">Keep communication clear.</h2></div><p class="muted">These contact details will be included in the public task card.</p><div class="form-grid">${field('Contact name', 'contact_name', contact.name)}${field('Contact role', 'contact_role', contact.role)}${field('Contact email', 'contact_email', contact.email, { type: 'email' })}${field('Communication channel', 'interaction_channel', interaction.channel)}${field('Meeting or feedback frequency', 'interaction_frequency', interaction.frequency)}${field('Feedback process', 'interaction_feedback', interaction.feedback_process, { area: true })}</div></section>`;
    }
    function readCard(form) {
        const value = name => form.elements[name].value.trim() || null;
        return {
            title: value('title'), context: value('context'), business_need: value('business_need'), expected_result: value('expected_result'), industry: value('industry'), tags: words(value('tags')),
            target_users: lines(value('target_users')), required_skills: lines(value('required_skills')), limitations: lines(value('limitations')),
            available_data: { description: value('data_description'), sources: lines(value('data_sources')), access_conditions: value('data_access') },
            business_contact: { name: value('contact_name'), role: value('contact_role'), email: value('contact_email') },
            interaction_format: { channel: value('interaction_channel'), frequency: value('interaction_frequency'), feedback_process: value('interaction_feedback') },
            success_criteria: Array.from(form.querySelectorAll('.criterion-row')).map(row => ({ metric: row.querySelector('[name="criterion_metric"]').value.trim() || null, target: row.querySelector('[name="criterion_target"]').value.trim() || null, verification_method: row.querySelector('[name="criterion_verification"]').value.trim() || null })).filter(item => Object.values(item).some(Boolean))
        };
    }
    function renderEditor(root, task) {
        const confirmed = task.status === 'confirmed';
        root.innerHTML = `${heading('02', 'Clarity is progress.', 'Review every detail. Your task goes live only when you publish it.')} ${steps(confirmed ? 3 : 2)}<div class="workspace-layout"><div class="stack"><section class="panel"><form id="card-form" class="stack">${editorFields(task.card)}${list(task.card.warnings).length ? `<div class="detail-section"><h3>Review notes</h3><ul class="detail-list">${task.card.warnings.map(item => `<li>${e(item)}</li>`).join('')}</ul></div>` : ''}${errorBox()}<div class="form-actions"><button class="btn btn-primary" type="submit">Save & update score ${window.UI.icon('arrow')}</button><span class="muted" data-save-status aria-live="polite">All changes saved</span></div></form></section><section class="panel"><form id="publish-form" class="stack"><p class="eyebrow">${confirmed ? '04 / READY FOR THE CATALOG' : 'FINAL REVIEW'}</p><h2 class="panel-title">${confirmed ? 'Your next move: publish.' : 'You have the final say.'}</h2><p class="muted">${confirmed ? 'Your card is confirmed. Publishing makes its details and business contact visible to student teams.' : 'Check that the details are accurate and that you are comfortable sharing the contact information publicly.'}</p>${confirmed ? '' : '<label class="checkbox-field"><input type="checkbox" name="reviewed" required><span>I have reviewed this task card and confirm the details.</span></label>'}<p class="muted" data-unsaved hidden>Save your changes above before continuing.</p>${errorBox()}<div class="form-actions"><button class="btn btn-accent" type="submit" data-publish-action>${confirmed ? 'Publish task' : 'Confirm task card'} ${window.UI.icon('arrow')}</button><a class="text-link" href="#workspace">Back to workspace</a></div></form></section></div>${scorePanel(task)}</div>`;
        const form = root.querySelector('#card-form');
        const publication = root.querySelector('#publish-form');
        const original = JSON.stringify(readCard(form));
        const updateDirty = () => {
            const dirty = JSON.stringify(readCard(form)) !== original;
            form.querySelector('[data-save-status]').textContent = dirty ? 'Unsaved changes' : 'All changes saved';
            publication.querySelector('[data-publish-action]').disabled = dirty;
            publication.querySelector('[data-unsaved]').hidden = !dirty;
            return dirty;
        };
        form.addEventListener('input', updateDirty);
        form.addEventListener('click', event => {
            if (event.target.closest('[data-add-criterion]')) { form.querySelector('[data-criteria]').insertAdjacentHTML('beforeend', criterionFields()); form.querySelector('[data-criteria]').lastElementChild.querySelector('input').focus(); updateDirty(); }
            if (event.target.closest('[data-remove-criterion]')) { event.target.closest('.criterion-row').remove(); updateDirty(); }
        });
        form.addEventListener('submit', event => {
            event.preventDefault();
            if (!updateDirty()) { window.UI.toast('Your task card is already saved.'); return; }
            const card = readCard(form);
            busy(form, form.querySelector('[type="submit"]'), 'Saving your task…', async () => {
                const updated = await window.Api.updateCard(task.id, card);
                if (form.isConnected) renderOwnedTask(root, updated);
                window.UI.toast('Task card saved. Readiness score updated.');
            });
        });
        publication.addEventListener('submit', async event => {
            event.preventDefault();
            if (updateDirty()) { formError(publication, 'Save your changes before continuing.'); return; }
            form.inert = true;
            try {
                await busy(publication, publication.querySelector('[type="submit"]'), confirmed ? 'Publishing…' : 'Confirming…', async () => {
                    const updated = confirmed ? await window.Api.publishTask(task.id) : await window.Api.confirmTask(task.id);
                    if (publication.isConnected) { renderOwnedTask(root, updated); window.scrollTo({ top: 0, behavior: 'instant' }); }
                    window.UI.toast(confirmed ? 'Your task is now published in the catalog.' : 'Task card confirmed. You can now publish it.');
                });
            } finally { form.inert = false; }
        });
    }
    function renderPublished(root, task) {
        root.innerHTML = `${heading('02', task.card?.title || 'Your published task.', 'Your challenge is live. Review proposals and choose the team you want to work with.', `<a class="btn" href="#task/${encodeURIComponent(task.id)}">View public task ${window.UI.icon('arrow')}</a>`)}<div class="workspace-layout"><div class="stack"><section class="panel stack"><p class="eyebrow">PUBLISHED / OPEN FOR PROPOSALS</p><h2 class="panel-title">Ready to meet your team.</h2><p>${e(task.card?.business_need || task.card?.context || 'Your task is available in the catalog.')}</p><p class="muted">Published cards are locked. Each team sends a proposal, and you make the selection.</p></section><section class="panel stack" data-proposal-review><p role="status">Loading proposals…</p></section></div>${scorePanel(task)}</div>`;
        renderProposalReview(root.querySelector('[data-proposal-review]'), task);
    }
    function safeLink(value) {
        try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
        catch (_) { return null; }
    }
    function proposalContent(proposal) {
        const links = list(proposal.portfolio_links).map(value => ({ label: value, href: safeLink(value) })).filter(item => item.href);
        return `<div class="detail-section"><h3>Why this task</h3><p class="preserve-lines">${e(proposal.message)}</p></div><div class="detail-section"><h3>Proposed approach</h3><p class="preserve-lines">${e(proposal.approach)}</p></div>${proposal.estimated_timeline ? `<div class="detail-section"><h3>Estimated timeline</h3><p>${e(proposal.estimated_timeline)}</p></div>` : ''}${links.length ? `<div class="detail-section"><h3>Portfolio</h3><ul class="detail-list">${links.map(item => `<li><a class="text-link" href="${e(item.href)}" target="_blank" rel="noopener noreferrer">${e(item.label)} ↗</a></li>`).join('')}</ul></div>` : ''}`;
    }
    async function renderProposalReview(container, task) {
        try {
            const proposals = await window.Api.getTaskProposals(task.id);
            if (!container.isConnected) return;
            const accepted = proposals.some(item => item.status === 'accepted');
            container.innerHTML = `<div class="data-row"><div><p class="eyebrow">TEAM PROPOSALS</p><h2 class="panel-title">${proposals.length} ${proposals.length === 1 ? 'proposal' : 'proposals'} to review.</h2></div><button class="btn btn-small" type="button" data-refresh>Refresh</button></div>${proposals.length ? proposals.map(proposal => `<article class="proposal-card panel stack"><div><span class="status-badge">${e(statusLabel(proposal.status))}</span><h3 class="panel-title">${e(proposal.team?.name || 'Student team')}</h3>${proposal.team?.description ? `<p class="muted">${e(proposal.team.description)}</p>` : ''}${proposal.team?.contact_email ? `<p>${e(proposal.team.contact_email)}</p>` : ''}${list(proposal.team?.skills).length ? `<p class="muted">${e(proposal.team.skills.join(' · '))}</p>` : ''}</div>${proposalContent(proposal)}${proposal.status === 'submitted' ? `<form class="stack" data-decision="${e(proposal.id)}">${errorBox()}<div class="inline-actions"><button class="btn btn-primary" type="button" data-choice="accepted" ${accepted ? 'disabled' : ''}>Accept team ${window.UI.icon('check')}</button><button class="btn" type="button" data-choice="rejected">Decline proposal</button></div>${accepted ? '<p class="muted">You have already accepted a team for this task.</p>' : '<p class="muted">Accepting selects this team for the task. Other proposals remain open for your review.</p>'}</form>` : ''}</article>`).join('') : '<div class="empty-state"><h3>Good collaborations start here.</h3><p class="muted">Proposals from student teams will appear here. You choose who to work with.</p></div>'}`;
            container.querySelector('[data-refresh]').addEventListener('click', () => renderProposalReview(container, task));
            container.querySelectorAll('[data-decision]').forEach(form => form.addEventListener('click', event => {
                const button = event.target.closest('[data-choice]');
                if (!button || button.disabled) return;
                const decision = button.dataset.choice;
                busy(form, button, decision === 'accepted' ? 'Accepting…' : 'Declining…', async () => {
                    await window.Api.decideProposal(form.dataset.decision, decision);
                    await renderProposalReview(container, task);
                    window.UI.toast(decision === 'accepted' ? 'Team accepted. Their proposal status has been updated.' : 'Proposal declined.');
                });
            }));
        } catch (error) {
            if (!container.isConnected) return;
            container.innerHTML = `<h2 class="panel-title">Team proposals</h2><p class="error-message" role="alert">${e(error.message)}</p><button class="btn" data-retry>Try again</button>`;
            container.querySelector('[data-retry]').addEventListener('click', () => renderProposalReview(container, task));
        }
    }
    function showProposal(task, draftValues = {}) {
        if (task.is_example) { window.UI.toast('This is an example task. Proposals are available for published business tasks.'); return; }
        if (!window.Api.getProfile('team')) { showProfile('team', () => showProposal(task, draftValues)); return; }
        const dialog = window.UI.modal('Make your first move.', `<form class="stack"><div><p class="eyebrow">YOUR PROPOSAL</p><h3 class="panel-title">${e(task.card?.title || 'Business task')}</h3><p class="muted">From ${e(window.Api.getProfile('team').name)}. The business reviews every proposal and makes the decision.</p></div>${field('Why is your team a good fit?', 'message', draftValues.message || '', { area: true, required: true, max: 5000, placeholder: 'Introduce your team and what you bring to this challenge.' })}${field('How would you approach the task?', 'approach', draftValues.approach || '', { area: true, rows: 4, required: true, max: 8000, placeholder: 'Outline your first steps, process, and intended outcome.' })}${field('Estimated timeline', 'estimated_timeline', draftValues.estimated_timeline || '', { optional: true, max: 500, placeholder: 'e.g. An initial prototype in three weeks' })}${field('Portfolio links', 'portfolio_links', list(draftValues.portfolio_links).join('\n'), { area: true, rows: 2, optional: true, hint: 'One full https:// link per line. Up to 10 links.' })}${errorBox()}<button class="btn btn-primary" type="submit">Send proposal ${window.UI.icon('arrow')}</button></form>`);
        const form = dialog.querySelector('form');
        form.addEventListener('submit', event => {
            event.preventDefault();
            const data = new FormData(form);
            const links = lines(data.get('portfolio_links'));
            if (links.length > 10 || links.some(value => !safeLink(value))) { formError(form, 'Add up to 10 valid links starting with http:// or https://, one per line.'); return; }
            const payload = { message: data.get('message').trim(), approach: data.get('approach').trim(), estimated_timeline: data.get('estimated_timeline').trim() || null, portfolio_links: links };
            if (!payload.message || !payload.approach) { formError(form, 'Tell the business why your team is a good fit and how you would approach the task.'); return; }
            busy(form, form.querySelector('[type="submit"]'), 'Sending proposal…', async () => {
                try { await window.Api.submitProposal(task.id, payload); }
                catch (error) {
                    if ((error.status === 401 || error.code === 'authentication_required') && dialog.open && form.isConnected) {
                        window.Auth.require('team', () => showProposal(task, payload));
                    }
                    throw error;
                }
                const stillOpen = dialog.open && form.isConnected;
                if (stillOpen) window.UI.closeModal();
                window.UI.toast('Proposal sent. The business will review your approach.');
                if (stillOpen) window.UI.navigate('#proposals');
            });
        });
    }
    async function renderTeamProposals(root, proposals, current) {
        root.innerHTML = `${heading('02', 'Your next chapter.', 'Every proposal is the start of a possible collaboration.', '<a class="btn btn-primary" href="#catalog">Explore tasks</a>')}<section class="stack">${proposals.length ? proposals.map((proposal, index) => `<article class="panel stack"><div class="data-row"><p class="eyebrow">${String(index + 1).padStart(2, '0')} / YOUR PROPOSAL</p><span class="status-badge">${e(statusLabel(proposal.status))}</span></div><h2 class="panel-title"><a class="text-link" data-task-title="${e(proposal.task_id)}" href="#task/${encodeURIComponent(proposal.task_id)}">View business task ${window.UI.icon('arrow')}</a></h2>${proposalContent(proposal)}<p class="muted">${proposal.status === 'accepted' ? 'The business has accepted your team. Use the contact details on the task card to coordinate your next steps.' : proposal.status === 'rejected' ? 'The business did not select this proposal. Explore the catalog for another challenge.' : 'Your proposal is with the business. They will choose the team manually.'}</p></article>`).join('') : '<div class="panel empty-state"><p class="eyebrow">POSSIBILITY STARTS WITH A PROPOSAL</p><h2>Find a problem worth solving.</h2><p class="muted">Explore real business tasks and tell a business how your team would approach one.</p><a class="btn btn-primary" href="#catalog">Explore tasks</a></div>'}</section>`;
        const taskIds = [...new Set(proposals.map(item => item.task_id))];
        await Promise.allSettled(taskIds.map(async id => {
            const task = await window.Api.getTask(id);
            if (!current()) return;
            root.querySelectorAll('[data-task-title]').forEach(link => { if (link.dataset.taskTitle === id) link.textContent = task.card?.title || 'View business task'; });
        }));
    }

    window.Workspace = { render, showProfile, showProposal };
})();
