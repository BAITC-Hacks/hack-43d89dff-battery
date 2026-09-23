document.addEventListener('DOMContentLoaded', () => {
    // UI Elements
    const step1 = document.getElementById('step-1');
    const step2 = document.getElementById('step-2');
    const step3 = document.getElementById('step-3');
    
    // Forms & Buttons
    const draftForm = document.getElementById('draft-form');
    const questionsForm = document.getElementById('questions-form');
    const btnGenerateQuestions = document.getElementById('btn-generate-questions');
    const btnGenerateCard = document.getElementById('btn-generate-card');
    const loader1 = document.getElementById('loader-1');
    const loader2 = document.getElementById('loader-2');
    
    // State variables
    let currentDraft = "";
    let currentTargetLanguage = "EN";
    let extractedQuestions = [];

    // Step 1: Request Analysis & Questions
    draftForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        currentDraft = document.getElementById('initial-draft').value.trim();
        currentTargetLanguage = document.getElementById('target-language').value;
        
        if (!currentDraft) {
            alert('Please enter a business draft.');
            return;
        }

        // UI Loading logic
        btnGenerateQuestions.disabled = true;
        loader1.classList.remove('hidden');

        try {
            const response = await fetch('/api/generate-questions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    initial_draft: currentDraft,
                    target_language: currentTargetLanguage
                })
            });

            if (!response.ok) throw new Error('Failed to generate questions');
            
            const data = await response.json();
            
            // Populate AI provisional score
            document.getElementById('ai-score').innerText = data.total_score || 0;

            // Generate Input Fields for questions
            const container = document.getElementById('questions-container');
            container.innerHTML = '';
            extractedQuestions = data.follow_up_questions || [];

            extractedQuestions.forEach((q, index) => {
                const item = document.createElement('div');
                item.className = 'question-item form-group';
                item.innerHTML = `
                    <label>${q.target_field.toUpperCase()} (Target: +${q.potential_points} pts)</label>
                    <p>${q.question}</p>
                    <textarea id="answer-${index}" placeholder="Your answer here..." required></textarea>
                `;
                container.appendChild(item);
            });

            // Transition UI
            step1.classList.add('hidden');
            step2.classList.remove('hidden');

        } catch (error) {
            alert('Error connecting to the AI architect. ' + error.message);
        } finally {
            btnGenerateQuestions.disabled = false;
            loader1.classList.add('hidden');
        }
    });

    // Step 2: Request Final Card and Deterministic Evaluation
    questionsForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Collect answers
        const answers = [];
        extractedQuestions.forEach((q, index) => {
            const el = document.getElementById(`answer-${index}`);
            answers.push({
                question: q.question,
                answer: el.value.trim()
            });
        });

        // UI Loading logic
        btnGenerateCard.disabled = true;
        loader2.classList.remove('hidden');

        try {
            // First API Call: Generate Task Card
            const cardResponse = await fetch('/api/generate-task-card', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    initial_draft: currentDraft,
                    clarifying_questions: extractedQuestions.map(q => q.question),
                    answers: answers,
                    task_summary: "" 
                })
            });
            if (!cardResponse.ok) throw new Error('Failed to generate task card');
            const taskCard = await cardResponse.json();

            // Second API Call: Deterministic Evaluation
            const evalResponse = await fetch('/api/evaluate-task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskCard)
            });
            if (!evalResponse.ok) throw new Error('Failed to evaluate task card');
            const evalData = await evalResponse.json();

            // Render Results in Step 3
            renderTaskCard(taskCard, evalData);

            // Transition UI
            step2.classList.add('hidden');
            step3.classList.remove('hidden');

        } catch (error) {
            alert('Error generating final task card. ' + error.message);
        } finally {
            btnGenerateCard.disabled = false;
            loader2.classList.add('hidden');
        }
    });

    function renderTaskCard(card, evalData) {
        // Score
        document.getElementById('final-score').innerText = evalData.total_score || 0;
        document.getElementById('readiness-level').innerText = `Readiness Level: ${(evalData.readiness_level || '').toUpperCase()}`;
        
        // Fields
        document.getElementById('card-title').innerText = card.title || 'Untitled Project';
        document.getElementById('card-context').innerText = card.context || 'Not provided';
        document.getElementById('card-need').innerText = card.business_need || 'Not provided';
        document.getElementById('card-expected').innerText = card.expected_result || 'Not provided';
        document.getElementById('card-data').innerText = card.available_data?.description || 'No data described';
        
        // Tags
        const tagsContainer = document.getElementById('card-tags');
        tagsContainer.innerHTML = '';
        if (card.tags && Array.isArray(card.tags)) {
            card.tags.forEach(tag => {
                const span = document.createElement('span');
                span.className = 'tag';
                span.innerText = tag;
                tagsContainer.appendChild(span);
            });
        }

        // Users
        const users = card.target_users || [];
        document.getElementById('card-users').innerText = users.length ? users.join(', ') : 'None specified';

        // Success Criteria
        const criteria = card.success_criteria || [];
        const criteriaText = criteria.map(c => `• ${c.metric}: ${c.target}`).join('\n');
        document.getElementById('card-success').innerText = criteriaText || 'None defined';

        // Missing Information
        const missing = card.missing_information || [];
        document.getElementById('card-missing').innerText = missing.length ? missing.join(', ') : 'None! Card is fully grounded.';
    }
});
