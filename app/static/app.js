let activeTaskId = null;
let pollInterval = null;
let currentTab = 'logs';
let activeTaskStatus = 'idle';
let selectedTimelineStep = null;

document.addEventListener('DOMContentLoaded', () => {
    loadTaskHistory();
    
    document.getElementById('btn-run').addEventListener('click', startAgentTask);
    document.getElementById('btn-stop').addEventListener('click', stopAgentTask);
    
    // Auto-expand textarea on typing
    const promptInput = document.getElementById('prompt-input');
    promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            startAgentTask();
        }
    });
});

// Tab navigation
function switchTab(tabName) {
    currentTab = tabName;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    // Find matching button and content
    event.target.classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

// Load historical tasks list
async function loadTaskHistory() {
    try {
        const response = await fetch('/api/tasks');
        const tasks = await response.json();
        
        const container = document.getElementById('task-history-list');
        container.innerHTML = '';
        
        if (tasks.length === 0) {
            container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem; text-align: center; padding: 10px;">No historical runs.</div>';
            return;
        }
        
        tasks.forEach(task => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.onclick = () => selectHistoricalTask(task.id);
            
            const start = new Date(task.started_at);
            const timeStr = start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            item.innerHTML = `
                <div class="history-item-header">
                    <span class="status-pill ${task.status}">${task.status}</span>
                    <span style="color: var(--text-muted); font-size: 0.75rem;">${timeStr}</span>
                </div>
                <div class="history-item-prompt">${escapeHtml(task.prompt)}</div>
            `;
            container.appendChild(item);
        });
    } catch (error) {
        console.error('Error loading task history:', error);
    }
}

// Start a new agent run
async function startAgentTask() {
    const promptInput = document.getElementById('prompt-input');
    const prompt = promptInput.value.trim();
    if (!prompt) return;
    
    promptInput.value = '';
    setUIState('running');
    
    try {
        const response = await fetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });
        
        if (!response.ok) {
            throw new Error(await response.text());
        }
        
        const data = await response.json();
        activeTaskId = data.task_id;
        selectedTimelineStep = null;
        
        addChatMessage('user', prompt);
        addChatMessage('agent', `Task started! ID: ${activeTaskId}. Monitoring live execution...`);
        
        // Start polling backend state
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(pollTaskDetails, 1500);
        pollTaskDetails(); // trigger first fetch immediately
        
    } catch (error) {
        console.error('Error launching task:', error);
        addChatMessage('agent', `Failed to launch task: ${error.message}`);
        setUIState('idle');
    }
}

// Stop current running task
async function stopAgentTask() {
    if (!activeTaskId) return;
    
    try {
        addChatMessage('agent', "Sending stop signal...");
        const response = await fetch(`/api/tasks/${activeTaskId}/stop`, { method: 'POST' });
        const res = await response.json();
        addChatMessage('agent', res.message);
    } catch (error) {
        console.error('Error stopping task:', error);
    }
}

// Poll state details
async function pollTaskDetails() {
    if (!activeTaskId) return;
    
    try {
        const response = await fetch(`/api/tasks/${activeTaskId}`);
        if (!response.ok) throw new Error('Failed to fetch details');
        
        const data = await response.json();
        const task = data.task;
        activeTaskStatus = task.status;
        
        // Update global status bar
        updateGlobalStatus(task.status);
        
        // Update URL bar
        const urlText = document.getElementById('browser-url-text');
        const latestAction = data.actions[data.actions.length - 1];
        urlText.textContent = latestAction ? latestAction.url || 'about:blank' : 'about:blank';
        
        // Update viewport elements
        const screenshotImg = document.getElementById('browser-screenshot');
        const videoElement = document.getElementById('browser-video');
        const placeholder = document.getElementById('viewport-placeholder');
        
        if (task.status === 'completed' && data.video_exists) {
            // Task finished, show recording video instead of screenshot
            screenshotImg.style.display = 'none';
            placeholder.style.display = 'none';
            videoElement.style.display = 'block';
            videoElement.src = `/api/tasks/${activeTaskId}/video`;
        } else if (data.latest_screenshot && selectedTimelineStep === null) {
            // Show latest live screenshot
            videoElement.style.display = 'none';
            placeholder.style.display = 'none';
            screenshotImg.style.display = 'block';
            screenshotImg.src = data.latest_screenshot + `&cb=${Date.now()}`;
            
            const stepNum = document.getElementById('viewport-step-num');
            stepNum.textContent = `Step ${latestAction ? latestAction.step : 0} (LIVE)`;
        }
        
        // Render timeline
        renderTimeline(data.actions);
        
        // Populate logs terminal
        renderLogs(data.logs);
        
        // Populate extracted data table
        renderDataTable(data.extracted_data);
        
        // Check if report tab needs updating
        if (task.status === 'completed' || task.status === 'failed') {
            loadReportMarkdown();
            clearInterval(pollInterval);
            pollInterval = null;
            setUIState('idle');
            loadTaskHistory();
        }
        
    } catch (error) {
        console.error('Polling error:', error);
        clearInterval(pollInterval);
    }
}

// Select a task from history
async function selectHistoricalTask(taskId) {
    activeTaskId = taskId;
    selectedTimelineStep = null;
    setUIState('idle');
    
    // Clear chats and inputs
    document.getElementById('chat-messages').innerHTML = '';
    addChatMessage('agent', `Loading historical task: ${taskId}...`);
    
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    
    // Fetch and populate details once
    await pollTaskDetails();
    loadReportMarkdown();
}

// Switch screenshot viewport to past timeline step
async function viewPastStepScreenshot(step) {
    if (!activeTaskId) return;
    selectedTimelineStep = step;
    
    const screenshotImg = document.getElementById('browser-screenshot');
    const videoElement = document.getElementById('browser-video');
    const placeholder = document.getElementById('viewport-placeholder');
    
    videoElement.style.display = 'none';
    placeholder.style.display = 'none';
    screenshotImg.style.display = 'block';
    
    screenshotImg.src = `/api/tasks/${activeTaskId}/screenshot?step=${step}&cb=${Date.now()}`;
    
    const stepNum = document.getElementById('viewport-step-num');
    stepNum.textContent = `Step ${step} (Inspecting)`;
    
    // Add active highlight to selected timeline card
    document.querySelectorAll('.timeline-step').forEach(card => {
        card.classList.remove('active');
        if (card.dataset.step == step) {
            card.classList.add('active');
        }
    });
}

// Resume live screenshot view
function resumeLiveViewport() {
    selectedTimelineStep = null;
    pollTaskDetails();
}

// Render action timeline
function renderTimeline(actions) {
    const container = document.getElementById('timeline-container');
    container.innerHTML = '';
    
    if (!actions || actions.length === 0) {
        container.innerHTML = '<span style="color: var(--text-muted); font-size: 0.75rem;">Timeline empty.</span>';
        return;
    }
    
    actions.forEach(a => {
        const card = document.createElement('div');
        card.className = `timeline-step ${selectedTimelineStep === a.step ? 'active' : ''}`;
        card.dataset.step = a.step;
        card.onclick = () => viewPastStepScreenshot(a.step);
        
        card.innerHTML = `
            <div class="timeline-step-num">Step ${a.step}</div>
            <div class="timeline-step-desc" title="${escapeHtml(a.description)}">
                <strong>${a.action_type.toUpperCase()}</strong>: ${escapeHtml(a.description)}
            </div>
        `;
        container.appendChild(card);
    });
    
    // Add "Live View" button if inspecting past step
    if (selectedTimelineStep !== null) {
        const liveBtn = document.createElement('button');
        liveBtn.className = 'btn-secondary';
        liveBtn.style.minWidth = '120px';
        liveBtn.textContent = 'Go to Live ➔';
        liveBtn.onclick = resumeLiveViewport;
        container.appendChild(liveBtn);
    }
}

// Populate Logs Terminal
function renderLogs(logs) {
    const term = document.getElementById('terminal-logs');
    term.innerHTML = '';
    
    if (!logs || logs.length === 0) {
        term.innerHTML = '<div class="log-row"><span class="log-message">Waiting for agent thoughts...</span></div>';
        return;
    }
    
    logs.forEach(l => {
        const row = document.createElement('div');
        row.className = 'log-row';
        
        const timestamp = new Date(l.timestamp).toLocaleTimeString([], { hour12: false });
        
        row.innerHTML = `
            <span class="log-time">[${timestamp}]</span>
            <span class="log-level ${l.level}">${l.level.toUpperCase()}</span>
            <span class="log-message ${l.level}">${escapeHtml(l.message)}</span>
        `;
        term.appendChild(row);
    });
    
    term.scrollTop = term.scrollHeight; // Auto-scroll
}

// Populate Data Table
function renderDataTable(data) {
    const headersTr = document.getElementById('data-table-headers');
    const tbody = document.getElementById('data-table-body');
    
    headersTr.innerHTML = '';
    tbody.innerHTML = '';
    
    if (!data || data.length === 0) {
        headersTr.innerHTML = '<th>Fields</th>';
        tbody.innerHTML = '<tr><td style="text-align: center; color: var(--text-muted);">No structured data collected yet.</td></tr>';
        return;
    }
    
    // Find all keys across entries
    const keys = [];
    data.forEach(item => {
        if (typeof item === 'object') {
            Object.keys(item).forEach(k => {
                if (!keys.includes(k)) keys.push(k);
            });
        }
    });
    
    // Build headers
    keys.forEach(k => {
        const th = document.createElement('th');
        th.textContent = k;
        headersTr.appendChild(th);
    });
    
    // Build rows
    data.forEach(item => {
        const tr = document.createElement('tr');
        keys.forEach(k => {
            const td = document.createElement('td');
            td.textContent = item[k] !== undefined ? item[k] : '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

// Load Markdown report
async function loadReportMarkdown() {
    if (!activeTaskId) return;
    
    try {
        const res = await fetch(`/api/tasks/${activeTaskId}/report`);
        if (!res.ok) throw new Error('No report generated yet.');
        const data = await res.json();
        
        const reportDiv = document.getElementById('report-md-content');
        reportDiv.textContent = data.content; // Render as preformatted plain text for simplicity
    } catch (err) {
        document.getElementById('report-md-content').textContent = err.message;
    }
}

// Data exports downloads
function exportData(format) {
    if (!activeTaskId) return;
    window.open(`/api/tasks/${activeTaskId}/export/${format}`);
}

// Chat UI helpers
function addChatMessage(sender, text) {
    const container = document.getElementById('chat-messages');
    
    // Remove welcome card if present
    const welcome = container.querySelector('.chat-welcome');
    if (welcome) welcome.remove();
    
    const div = document.createElement('div');
    div.style.padding = '10px 14px';
    div.style.borderRadius = '8px';
    div.style.fontSize = '0.8rem';
    div.style.lineHeight = '1.4';
    div.style.maxWidth = '85%';
    
    if (sender === 'user') {
        div.style.backgroundColor = 'var(--accent-color)';
        div.style.color = '#fff';
        div.style.alignSelf = 'flex-end';
        div.style.marginLeft = 'auto';
    } else {
        div.style.backgroundColor = 'var(--bg-tertiary)';
        div.style.border = '1px solid var(--border-color)';
        div.style.color = 'var(--text-main)';
        div.style.alignSelf = 'flex-start';
    }
    
    div.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// UI State Management
function setUIState(state) {
    const runBtn = document.getElementById('btn-run');
    const stopBtn = document.getElementById('btn-stop');
    
    if (state === 'running') {
        runBtn.style.display = 'none';
        stopBtn.style.display = 'block';
    } else {
        runBtn.style.display = 'block';
        stopBtn.style.display = 'none';
    }
}

function updateGlobalStatus(status) {
    const dot = document.getElementById('global-status-dot');
    const text = document.getElementById('global-status-text');
    
    text.textContent = status.toUpperCase();
    dot.className = 'status-dot';
    
    if (status === 'running') {
        dot.classList.add('active');
    }
}

function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}
