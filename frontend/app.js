const API_BASE = '';

// Polling interval (ms)
const POLL_INTERVAL = 3000;

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

async function openNewBuildDialog() {
    document.getElementById('dialog-overlay').classList.add('active');
    await loadManifest();
}

function closeDialog() {
    document.getElementById('dialog-overlay').classList.remove('active');
}


document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDialog();
});

// Compare dialog
function openCompareDialog() {
    document.getElementById('compare-overlay').classList.add('active');
    document.getElementById('compare-result').style.display = 'none';
    document.getElementById('compare-left').value = '';
    document.getElementById('compare-right').value = '';
}

function closeCompareDialog() {
    document.getElementById('compare-overlay').classList.remove('active');
}


// Auto-reload manifest when project selection changes
document.addEventListener('DOMContentLoaded', () => {
    const projectSelect = document.getElementById('dialog-project');
    if (projectSelect) {
        projectSelect.addEventListener('change', () => {
            loadManifest();
        });
    }
});

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

async function fetchBuilds() {
    const res = await fetch(`${API_BASE}/api/builds`);
    if (!res.ok) throw new Error('Failed to fetch builds');
    return res.json();
}

async function createBuild(project, mode, platform, manifest) {
    const res = await fetch(`${API_BASE}/api/builds`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project, mode, platform, manifest }),
    });
    if (!res.ok) throw new Error('Failed to create build');
    return res.json();
}

async function fetchProjects() {
    const res = await fetch(`${API_BASE}/api/projects`);
    if (!res.ok) throw new Error('Failed to fetch projects');
    return res.json();
}

async function fetchCompare(leftId, rightId) {
    const res = await fetch(`${API_BASE}/api/builds/compare?left=${encodeURIComponent(leftId)}&right=${encodeURIComponent(rightId)}`);
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `Compare failed (${res.status})`);
    }
    return res.json();
}

async function fetchWorkspaceManifest() {
    const res = await fetch(`${API_BASE}/api/manifest`);
    if (!res.ok) throw new Error('Failed to fetch workspace manifest');
    const data = await res.json();
    return data.content || '';
}

async function fetchProjectManifest(projectName) {
    const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectName)}/manifest`);
    if (!res.ok) throw new Error('Project manifest not found');
    const data = await res.json();
    return data.content || '';
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function loadManifest() {
    const btn = document.getElementById('btn-load-manifest');
    const textarea = document.getElementById('dialog-manifest');
    const project = document.getElementById('dialog-project').value;
    btn.disabled = true;
    btn.textContent = '加载中...';
    textarea.value = '';
    try {
        // Load project-specific manifest from config repo
        const content = await fetchProjectManifest(project);
        textarea.value = content;
    } catch (err) {
        // Fallback: try workspace manifest
        try {
            const content = await fetchWorkspaceManifest();
            textarea.value = content || `# 项目 "${project}" 的 manifest 未找到\n# 请手动填写`;
        } catch {
            textarea.value = `# 加载失败: ${err.message}\n# 请手动填写 manifest 内容`;
        }
    } finally {
        btn.disabled = false;
        btn.textContent = '↻ 加载';
    }
}

async function confirmBuild() {
    const project  = document.getElementById('dialog-project').value;
    const mode     = document.getElementById('dialog-mode').value;
    const platform = document.getElementById('dialog-platform').value;
    const manifest = document.getElementById('dialog-manifest').value;

    const btn = document.getElementById('dialog-confirm');
    btn.disabled = true;
    btn.textContent = '构建中...';

    try {
        await createBuild(project, mode, platform, manifest);
        closeDialog();
        await loadBuilds();
    } catch (err) {
        alert('发起构建失败: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '确认构建';
    }
}

async function loadBuilds() {
    try {
        const data = await fetchBuilds();
        renderBuilds(data.builds || []);
    } catch (err) {
        console.error('Failed to load builds:', err);
        document.getElementById('builds-tbody').innerHTML =
            '<tr><td colspan="7" class="error">加载失败，服务是否运行中？</td></tr>';
    }
}

// ---------------------------------------------------------------------------
// UI Rendering
// ---------------------------------------------------------------------------

function statusLabel(status) {
    const labels = {
        pending:   'Pending',
        running:   'Running...',
        success:   'Success',
        failed:    'Failed',
        cancelled: 'Cancelled',
        deleted:   'Deleted',
    };
    return `<span class="status ${status}">${labels[status] || status}</span>`;
}

function formatTime(isoString) {
    if (!isoString) return '-';
    const d = new Date(isoString);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ` +
           `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function renderBuildRow(build) {
    const time = formatTime(build.created_at);
    const downloadBtn = build.status === 'success'
        ? `<a href="/api/builds/${build.id}/download" class="download-btn" target="_blank">Download</a>`
        : '-';

    // 兼容旧数据格式：build_type -> mode
    const project = build.project || build.project_name || '-';
    const mode = build.mode || build.build_type || '-';

    return `
        <tr>
            <td class="build-id" onclick="copyBuildId('${build.id}')" title="点击复制">${build.id}</td>
            <td class="meta"><span>${project}</span></td>
            <td class="meta"><span>${build.platform || '-'}</span></td>
            <td class="meta"><span>${mode}</span></td>
            <td>${statusLabel(build.status)}</td>
            <td>${time}</td>
            <td>${downloadBtn}</td>
        </tr>
    `;
}

function renderBuilds(builds) {
    const tbody = document.getElementById('builds-tbody');

    const active = builds.filter(b => b.status !== 'deleted');
    if (active.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无构建记录，点击上方「发起新构建」开始</td></tr>';
        return;
    }

    tbody.innerHTML = active.map(renderBuildRow).join('');
}


// ---------------------------------------------------------------------------
// Copy Build ID
// ---------------------------------------------------------------------------

function copyBuildId(id) {
    navigator.clipboard.writeText(id).then(() => {
        // Brief visual feedback could be added here
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

async function loadProjects() {
    const select = document.getElementById('dialog-project');
    try {
        const data = await fetchProjects();
        const projects = data.projects || [];
        if (projects.length > 0) {
            select.innerHTML = projects.map(p =>
                `<option value="${p.name}">${p.name}</option>`
            ).join('');
        }
    } catch (err) {
        console.error('Failed to load projects:', err);
    }
}

// ---------------------------------------------------------------------------
// Compare
// ---------------------------------------------------------------------------

async function runCompare() {
    const leftId = document.getElementById('compare-left').value.trim();
    const rightId = document.getElementById('compare-right').value.trim();
    const resultDiv = document.getElementById('compare-result');
    const btn = document.getElementById('btn-run-compare');

    if (!leftId || !rightId) {
        alert('请输入两个 Build ID');
        return;
    }

    btn.disabled = true;
    btn.textContent = '比较中...';
    resultDiv.style.display = 'none';

    try {
        const data = await fetchCompare(leftId, rightId);
        renderCompareResult(data, resultDiv);
        resultDiv.style.display = 'block';
    } catch (err) {
        resultDiv.innerHTML = `<div class="compare-error">${err.message}</div>`;
        resultDiv.style.display = 'block';
    } finally {
        btn.disabled = false;
        btn.textContent = '比较';
    }
}

function renderCompareResult(data, container) {
    const { left, right, summary, repo_comparisons } = data;

    const statusColors = {
        unchanged: '#d4edda',
        modified: '#fff3cd',
        left_only: '#f8d7da',
        right_only: '#f8d7da',
    };
    const statusTextColors = {
        unchanged: '#155724',
        modified: '#856404',
        left_only: '#721c24',
        right_only: '#721c24',
    };

    let html = `
        <div class="compare-builds-info">
            <div class="compare-build-card">
                <strong>左: ${left.id}</strong>
                <span>${left.project} / ${left.mode} / ${left.platform}</span>
                <span class="status ${left.status}">${left.status}</span>
            </div>
            <div class="compare-build-card">
                <strong>右: ${right.id}</strong>
                <span>${right.project} / ${right.mode} / ${right.platform}</span>
                <span class="status ${right.status}">${right.status}</span>
            </div>
        </div>
        <div class="compare-summary">
            同项目: ${summary.same_project ? '✓' : '✗'} &nbsp;
            同平台: ${summary.same_platform ? '✓' : '✗'} &nbsp;
            同模式: ${summary.same_mode ? '✓' : '✗'}
        </div>
    `;

    if (repo_comparisons.length > 0) {
        html += '<div class="compare-repos"><strong>Repo 对比:</strong>';
        for (const repo of repo_comparisons) {
            const bg = statusColors[repo.status] || '#f0f0f0';
            const fg = statusTextColors[repo.status] || '#333';
            let detail = repo.status;
            if (repo.status === 'modified') {
                detail += ` (${(repo.left_commit || '').slice(0, 7)} → ${(repo.right_commit || '').slice(0, 7)})`;
            }
            html += `<div class="compare-repo-item" style="background:${bg};color:${fg};">
                <span class="repo-name">${repo.name}</span>
                <span class="repo-status">${detail}</span>
            </div>`;
        }
        html += '</div>';
    } else {
        html += '<div class="compare-no-repos">无 repo 数据可比较</div>';
    }

    container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

loadProjects();
loadBuilds();
setInterval(loadBuilds, POLL_INTERVAL);
