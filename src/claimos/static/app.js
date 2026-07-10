// Tab switching — reads URL hash, shows matching panel, updates nav styles.
function initTabs() {
    const links = document.querySelectorAll('[data-tab]');
    const panels = document.querySelectorAll('[data-panel]');
    if (!links.length) return;

    function activate(name) {
        links.forEach(link => {
            const active = link.dataset.tab === name;
            link.classList.toggle('border-primary', active);
            link.classList.toggle('text-primary', active);
            link.classList.toggle('border-transparent', !active);
            link.classList.toggle('text-neutral-500', !active);
        });
        panels.forEach(panel => {
            panel.classList.toggle('hidden', panel.dataset.panel !== name);
        });
    }

    const initial = window.location.hash.replace('#', '') || 'overview';
    activate(initial);

    links.forEach(link => {
        link.addEventListener('click', () => activate(link.dataset.tab));
    });

    window.addEventListener('hashchange', () => {
        activate(window.location.hash.replace('#', '') || 'overview');
    });
}

document.addEventListener('DOMContentLoaded', initTabs);

// CSRF: cover both HTMX requests (via hx-headers) and plain form POSTs (via hidden field).
function addCsrfToPlainForms(root, csrf) {
    (root || document).querySelectorAll('form').forEach(function (form) {
        if ((form.getAttribute('method') || '').toUpperCase() !== 'POST') return;
        if (form.querySelector('input[name="_csrf"]')) return;
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = '_csrf';
        input.value = csrf;
        form.appendChild(input);
    });
}

document.addEventListener('DOMContentLoaded', function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var csrf = meta ? meta.content : '';
    if (!csrf) return;

    // HTMX requests pick up X-CSRF-Token from hx-headers on <body>
    document.body.setAttribute('hx-headers', JSON.stringify({'X-CSRF-Token': csrf}));

    // Plain method="post" forms get a hidden _csrf field so the server can validate
    addCsrfToPlainForms(document, csrf);
});

// Re-retrofit any plain POST forms that arrive via HTMX swaps
document.addEventListener('htmx:afterSwap', function (e) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var csrf = meta ? meta.content : '';
    if (!csrf) return;
    addCsrfToPlainForms(e.detail.elt, csrf);
});

// ── Serp panel toggle ────────────────────────────────────────────────────
function toggleSerpPanel(itemId) {
  const existing = document.getElementById('serp-panel-' + itemId);
  if (existing) {
    existing.remove();
    return;
  }
  htmx.ajax('GET', '/api/items/' + itemId + '/serp-panel', {
    target: document.getElementById('item-row-' + itemId),
    swap: 'afterend',
  });
}

function showCropPanel(itemId, cropId) {
  // Hide all crop panels for this item, show the selected one
  const panel = document.getElementById('serp-panel-' + itemId);
  if (!panel) return;
  panel.querySelectorAll('[id^="crop-panel-"]').forEach(el => el.classList.add('hidden'));
  panel.querySelectorAll('[id^="crop-tab-"]').forEach(el => {
    el.classList.remove('border-primary-light');
    el.classList.add('border-transparent');
  });
  const target = document.getElementById('crop-panel-' + cropId);
  if (target) target.classList.remove('hidden');
  const tab = document.getElementById('crop-tab-' + cropId);
  if (tab) {
    tab.classList.remove('border-transparent');
    tab.classList.add('border-primary-light');
  }
}

// ── Edit-form crop selector (Google Lens section) ────────────────────────
function showEditCrop(itemId, cropId) {
  document.querySelectorAll('[id^="edit-crop-panel-"]').forEach(function(el) {
    el.classList.add('hidden');
  });
  document.querySelectorAll('[id^="edit-crop-tab-"]').forEach(function(el) {
    el.classList.remove('border-primary-light');
    el.classList.add('border-transparent');
  });
  var panel = document.getElementById('edit-crop-panel-' + cropId);
  if (panel) panel.classList.remove('hidden');
  var tab = document.getElementById('edit-crop-tab-' + cropId);
  if (tab) {
    tab.classList.remove('border-transparent');
    tab.classList.add('border-primary-light');
  }
}

// ── Crop editor toggle ───────────────────────────────────────────────────
function toggleCropEditor(fileId, opts) {
  opts = opts || {};
  const root = document.getElementById('crop-editor-modal-root');
  if (!root) return;
  // Re-entrancy guard: don't stack a second open while one is loaded or in flight.
  if (root.children.length > 0 || root.dataset.loading === '1') return;
  if (opts.preselectCropId) {
    root.dataset.preselectCrop = opts.preselectCropId;
  }
  root.dataset.loading = '1';
  document.body.classList.add('overflow-hidden');
  htmx.ajax('GET', '/api/evidence/' + fileId + '/crop-editor', {
    target: root,
    swap: 'innerHTML',
  }).finally(function () {
    delete root.dataset.loading;
    // If the request failed, the root is still empty — release the body scroll lock so the page isn't stuck.
    if (root.children.length === 0) {
      document.body.classList.remove('overflow-hidden');
    }
  });
}

// ── Crop-edit deep-link auto-init ────────────────────────────────────────────
// When the page is opened via the "Edit crop" thumbnail link (?file=&crop=#evidence),
// auto-open the modal for the evidence file and pre-select the item's crop.
// Preselect handling is consolidated in crop-editor.js (reads root.dataset.preselectCrop
// after htmx:afterSettle).
document.addEventListener('DOMContentLoaded', function () {
  var params = new URLSearchParams(window.location.search);
  var fileId = params.get('file');
  var cropId = params.get('crop');
  if (!fileId) return;
  // The hash is already #evidence (handled by initTabs).
  toggleCropEditor(fileId, cropId ? { preselectCropId: cropId } : {});
});

// ── Evidence drag-drop upload ─────────────────────────────────────────────
// Per-file uploads with bounded concurrency. Caps come from data-* attrs on
// the drop zone (server-rendered from runtime_config).
function initEvidenceUpload() {
    var zone = document.getElementById('drop-zone');
    var input = document.getElementById('evidence-input');
    var progress = document.getElementById('evidence-upload-progress');
    var grid = document.getElementById('evidence-grid');
    if (!zone || !input) return;

    var claimId = zone.dataset.claimId;
    var csrf = zone.dataset.csrfToken || '';
    var concurrency = Math.max(1, parseInt(zone.dataset.evidenceUploadConcurrency, 10) || 4);
    var maxFileBytes = (parseInt(zone.dataset.evidenceUploadMaxFileMb, 10) || 10) * 1024 * 1024;
    var maxBatch = parseInt(zone.dataset.evidenceUploadMaxBatchCount, 10) || 500;

    var queue = [];
    var inFlight = 0;
    var rowId = 0;

    function newRow(name, state, message) {
        rowId += 1;
        var div = document.createElement('div');
        div.id = 'upload-row-' + rowId;
        div.className = 'flex items-center gap-2 text-xs';

        var nameSpan = document.createElement('span');
        nameSpan.className = 'truncate flex-1';
        nameSpan.textContent = name;
        div.appendChild(nameSpan);

        var stateSpan = document.createElement('span');
        stateSpan.setAttribute('data-state', '');
        stateSpan.className = stateClass(state);
        stateSpan.textContent = message || state;
        div.appendChild(stateSpan);

        progress.appendChild(div);
        return div;
    }

    function stateClass(state) {
        if (state === 'done') return 'text-success-emphasis';
        if (state === 'failed') return 'text-error cursor-pointer underline';
        if (state === 'uploading') return 'text-primary';
        return 'text-neutral-400';
    }

    function setRowState(row, state, message) {
        var badge = row.querySelector('[data-state]');
        badge.className = stateClass(state);
        badge.textContent = message || state;
        if (state === 'done') {
            setTimeout(function () { row.remove(); }, 2000);
        }
    }

    function enqueueDrop(fileList) {
        var files = Array.from(fileList || []);
        if (files.length === 0) return;
        if (files.length > maxBatch) {
            alert('Limit is ' + maxBatch + ' files per drop. Try smaller batches.');
            return;
        }
        files.forEach(function (f) {
            if (f.size > maxFileBytes) {
                newRow(f.name, 'failed', 'Too large (max ' + (maxFileBytes / 1024 / 1024) + ' MB)');
                return;
            }
            var row = newRow(f.name, 'queued', 'Queued');
            queue.push({ file: f, row: row });
        });
        pump();
    }

    function pump() {
        while (inFlight < concurrency && queue.length > 0) {
            var job = queue.shift();
            startJob(job);
        }
        if (inFlight === 0 && queue.length === 0) {
            // Queue fully drained — refresh grid chrome (counts, banners) once.
            htmx.ajax('GET', '/api/claims/' + claimId + '/evidence-grid', '#evidence-grid');
        }
    }

    function startJob(job) {
        inFlight += 1;
        setRowState(job.row, 'uploading', 'Uploading…');
        var form = new FormData();
        form.append('file', job.file, job.file.name);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/claims/' + claimId + '/evidence');
        if (csrf) xhr.setRequestHeader('X-CSRF-Token', csrf);
        xhr.onload = function () {
            inFlight -= 1;
            if (xhr.status >= 200 && xhr.status < 300) {
                if (grid && xhr.responseText) {
                    grid.insertAdjacentHTML('beforeend', xhr.responseText);
                    htmx.process(grid);
                }
                setRowState(job.row, 'done', '✓');
            } else {
                var msg = (xhr.status === 413) ? 'Too large' : ('Failed (' + xhr.status + ')');
                setRowState(job.row, 'failed', msg + ' — retry');
                job.row.addEventListener('click', function retry() {
                    job.row.removeEventListener('click', retry);
                    setRowState(job.row, 'queued', 'Queued');
                    queue.push(job);
                    pump();
                });
            }
            pump();
        };
        xhr.onerror = function () {
            inFlight -= 1;
            setRowState(job.row, 'failed', 'Network — retry');
            pump();
        };
        xhr.send(form);
    }

    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () {
        enqueueDrop(input.files);
        input.value = ''; // allow re-selecting same files
    });
    zone.addEventListener('dragover', function (e) {
        e.preventDefault();
        zone.classList.add('border-primary-light', 'bg-primary-subtle');
    });
    zone.addEventListener('dragleave', function () {
        zone.classList.remove('border-primary-light', 'bg-primary-subtle');
    });
    zone.addEventListener('drop', function (e) {
        e.preventDefault();
        zone.classList.remove('border-primary-light', 'bg-primary-subtle');
        enqueueDrop(e.dataTransfer.files);
    });

    window.addEventListener('beforeunload', function (e) {
        if (inFlight > 0 || queue.length > 0) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
}

document.addEventListener('DOMContentLoaded', initEvidenceUpload);

// ── Room rename ───────────────────────────────────────────────────────────
function startRename(roomId) {
    var li = document.getElementById('room-' + roomId);
    var nameSpan = document.getElementById('room-name-' + roomId);
    var currentName = nameSpan.textContent.trim();

    var form = document.createElement('form');
    form.style.display = 'contents';
    form.setAttribute('hx-patch', '/api/rooms/' + roomId);
    form.setAttribute('hx-target', '#room-' + roomId);
    form.setAttribute('hx-swap', 'outerHTML');

    var input = document.createElement('input');
    input.name = 'name';
    input.value = currentName;
    input.required = true;
    input.maxLength = 100;
    input.className = 'rounded-sm border border-primary-light px-2 py-0.5 text-sm focus:outline-hidden focus:ring-1 focus:ring-primary-light flex-1';

    var save = document.createElement('button');
    save.type = 'submit';
    save.textContent = 'Save';
    save.className = 'rounded-sm px-2 py-0.5 text-xs bg-primary text-white hover:bg-primary-light';

    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = 'Cancel';
    cancel.className = 'rounded-sm px-2 py-0.5 text-xs text-neutral-500 hover:bg-neutral-100';
    cancel.addEventListener('click', function () { location.reload(); });

    form.appendChild(input);
    form.appendChild(save);
    form.appendChild(cancel);

    li.innerHTML = '';
    li.appendChild(form);
    htmx.process(form);
    input.focus();
    input.select();
}

// Delegated click: rename buttons use data-rename-room-id instead of onclick
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-rename-room-id]');
    if (btn) startRename(btn.dataset.renameRoomId);
});

// Delegated click: data-toggle-crop-editor → toggleCropEditor(fileId, opts)
document.addEventListener('click', function (e) {
  var btn = e.target.closest('[data-toggle-crop-editor]');
  if (!btn) return;
  e.preventDefault();
  var opts = {};
  if (btn.dataset.preselectCrop) {
    opts.preselectCropId = btn.dataset.preselectCrop;
  }
  toggleCropEditor(btn.dataset.toggleCropEditor, opts);
});

// Esc closes the crop editor modal (ignores when typing in form fields).
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var root = document.getElementById('crop-editor-modal-root');
  if (!root || root.children.length === 0) return;
  var tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  root.innerHTML = '';
  delete root.dataset.preselectCrop;
  document.body.classList.remove('overflow-hidden');
});

// Delegated click: data-serp-panel-close → remove serp panel row
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-serp-panel-close]');
    if (btn) {
        var el = document.getElementById('serp-panel-' + btn.dataset.serpPanelClose);
        if (el) el.remove();
    }
});

// Delegated click: data-show-crop-panel-item / data-show-crop-panel-crop → showCropPanel
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-show-crop-panel-item]');
    if (btn) showCropPanel(btn.dataset.showCropPanelItem, btn.dataset.showCropPanelCrop);
});

// Delegated click: data-show-edit-crop-item / data-show-edit-crop-crop → showEditCrop
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-show-edit-crop-item]');
    if (btn) showEditCrop(btn.dataset.showEditCropItem, btn.dataset.showEditCropCrop);
});

// Delegated click: data-reload-on-click → location.reload()
document.addEventListener('click', function (e) {
    if (e.target.closest('[data-reload-on-click]')) location.reload();
});

// Delegated click: data-clear-element="<id>" → element.innerHTML = ''
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-clear-element]');
    if (btn) {
        var el = document.getElementById(btn.dataset.clearElement);
        if (el) el.innerHTML = '';
    }
});

// Delegated click: data-print-page → window.print()
document.addEventListener('click', function (e) {
    if (e.target.closest('[data-print-page]')) window.print();
});

// Replace hx-on::after-request on add-room form (HTMX uses new Function() for hx-on, blocked by CSP)
document.addEventListener('htmx:afterRequest', function (e) {
    if (e.detail.elt && e.detail.elt.id === 'add-room-form' && e.detail.successful) {
        e.detail.elt.reset();
        var empty = document.getElementById('rooms-empty');
        if (empty) empty.remove();
    }
});

// Same pattern for the add-item-group form on the Rooms & Groups tab.
document.addEventListener('htmx:afterRequest', function (e) {
    if (e.detail.elt && e.detail.elt.id === 'add-item-group-form' && e.detail.successful) {
        e.detail.elt.reset();
        var empty = document.getElementById('item-groups-empty');
        if (empty) empty.remove();
    }
});

// Lens search: "Searching…" while in-flight
document.addEventListener('htmx:beforeRequest', function (e) {
    if (!e.detail.elt.hasAttribute('data-lens-form')) return;
    var btn = e.detail.elt.querySelector('button[data-lens-btn]');
    if (btn) btn.textContent = 'Searching…';
});

// Lens search: permanently lock button after any result (success or error)
document.addEventListener('htmx:afterRequest', function (e) {
    if (!e.detail.elt.hasAttribute('data-lens-form')) return;
    var btn = e.detail.elt.querySelector('button[data-lens-btn]');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = 'Searched';
    btn.classList.remove('bg-primary', 'hover:bg-primary-strong', 'transition');
    btn.classList.add('bg-neutral-400', 'cursor-not-allowed');
});

// ── Bulk evidence actions ────────────────────────────────────────────────

// Delegated click: data-remove-all-count → confirmRemoveAll(count)
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-remove-all-count]');
    if (btn) confirmRemoveAll(parseInt(btn.dataset.removeAllCount, 10));
});

// Delegated click: data-dismiss-scan-banner="<jobId>" → dismissScanBanner(jobId)
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-dismiss-scan-banner]');
    if (btn) dismissScanBanner(btn.dataset.dismissScanBanner);
});

function confirmRemoveAll(count) {
  var input = prompt(
    'This will permanently remove all ' + count + ' images and their scanned items.\n' +
    'Type ' + count + ' to confirm:'
  );
  if (input !== null && parseInt(input, 10) === count) {
    document.getElementById('remove-all-confirm-count').value = count;
    htmx.trigger(document.getElementById('remove-all-form'), 'submit');
  }
}

function dismissScanBanner(jobId) {
  try { sessionStorage.setItem('dismissed_banner_' + jobId, '1'); } catch (_) {}
  var el = document.getElementById('scan-banner-' + jobId);
  if (el) el.remove();
}

// Delegated change: data-evidence-group-select handles "+ New group…" sentinel.
// Selecting __new__ prompts for a name, posts via fetch, then reloads so the
// new group appears in every dropdown on the page.
document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!sel.matches || !sel.matches('select[data-evidence-group-select]')) return;
    if (sel.value !== '__new__') return;
    var name = window.prompt('New group name:');
    if (!name || !name.trim()) {
        // User cancelled — just revert the select; no PATCH needed since the
        // pinned group never actually changed.
        sel.value = '';
        return;
    }
    var fileId = sel.dataset.evidenceGroupSelect;
    var claimId = sel.dataset.claimId;
    var fd = new FormData();
    fd.append('new_item_group_name', name.trim());
    fetch('/api/claims/' + claimId + '/evidence/' + fileId + '/item-group', {
        method: 'PATCH',
        body: fd,
        credentials: 'same-origin',
    }).then(function (r) {
        if (r.ok) {
            window.location.reload();
        } else {
            sel.value = '';
            alert('Could not create group.');
        }
    });
});

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-job-id]').forEach(function (el) {
    var jobId = el.dataset.jobId;
    try {
      if (sessionStorage.getItem('dismissed_banner_' + jobId)) el.remove();
    } catch (_) {}
  });
});

// Feedback widget: open/close popover
document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-feedback-toggle]');
    if (toggle) {
        var pop = toggle.parentElement.querySelector('[data-feedback-popover]');
        if (pop) pop.classList.toggle('hidden');
        return;
    }
    var closeBtn = e.target.closest('[data-feedback-close]');
    if (closeBtn) {
        var p = closeBtn.closest('[data-feedback-popover]');
        if (p) p.classList.add('hidden');
        return;
    }
    var openRow = e.target.closest('[data-feedback-open]');
    if (openRow) {
        var id = openRow.dataset.feedbackOpen;
        htmx.ajax('GET', '/feedback/' + encodeURIComponent(id), {
            target: openRow,
            swap: 'outerHTML',
        });
        return;
    }
    var delFb = e.target.closest('[data-feedback-delete]');
    if (delFb) {
        if (!confirm('Delete this feedback?')) return;
        var fid = delFb.dataset.feedbackDelete;
        htmx.ajax('POST', '/feedback/' + encodeURIComponent(fid) + '/delete', {
            target: 'body',
            swap: 'none',
        }).then(function () { location.reload(); });
        return;
    }
    var delC = e.target.closest('[data-feedback-delete-comment]');
    if (delC) {
        if (!confirm('Delete this comment?')) return;
        var cid = delC.dataset.feedbackDeleteComment;
        htmx.ajax('POST', '/feedback/comments/' + encodeURIComponent(cid) + '/delete', {
            target: 'body',
            swap: 'none',
        }).then(function () { location.reload(); });
    }
});

// Feedback widget: populate the hidden page_url field whenever a feedback form is rendered
document.addEventListener('htmx:afterSwap', function (e) {
    var inputs = e.detail.elt && e.detail.elt.querySelectorAll
        ? e.detail.elt.querySelectorAll('[data-feedback-page-url]')
        : [];
    inputs.forEach(function (input) {
        input.value = window.location.pathname + window.location.search;
    });
});

// Also populate immediately on initial render of any panel content already in the DOM
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-feedback-page-url]').forEach(function (input) {
        input.value = window.location.pathname + window.location.search;
    });
});

// Admin feedback list: row click navigates to detail
document.addEventListener('click', function (e) {
    var row = e.target.closest('[data-feedback-admin-row]');
    if (row) {
        window.location.href = '/admin/system/feedback/' + encodeURIComponent(row.dataset.feedbackAdminRow);
    }
});

// Delegated change: data-item-group-select handles "+ New group…" by prompting
// and stashing the name in the sibling hidden input named new_item_group_name.
// On submit, the items router calls find_or_create(claim_id, new_item_group_name)
// before assigning item.item_group_id.
document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!sel.matches || !sel.matches('select[data-item-group-select]')) return;
    var itemId = sel.dataset.itemGroupSelect;
    var hidden = document.querySelector('input[data-new-item-group-name="' + itemId + '"]');
    if (sel.value === '__new__') {
        var name = window.prompt('New group name:');
        if (name && name.trim()) {
            if (hidden) hidden.value = name.trim();
            // Visually reset the select to (none); the hidden input drives the
            // create on submit.
            sel.value = '';
        } else {
            sel.value = '';
            if (hidden) hidden.value = '';
        }
    } else {
        if (hidden) hidden.value = '';
    }
});

// ---- Live items list: surface scan / region-rescan results -------------
// Both the full-scan HTMX poll and the region-scan JSON poll converge on a
// single document event: claimos:items-added {detail:{claimId, jobId, count}}.
(function () {
  var handledScanJobs = new Set();
  var newItemsCount = 0;

  // Detect full-scan completion from the swapped scan-progress fragment.
  document.addEventListener('htmx:afterSwap', function (e) {
    var root = e.target;
    if (!root || !root.querySelector) return;
    var el = (root.matches && root.matches('[data-scan-state]'))
      ? root
      : root.querySelector('[data-scan-state]');
    if (!el) return;
    var state = el.dataset.scanState;
    if (state !== 'done' && state !== 'error') return;
    var jobId = el.dataset.jobId;
    if (!jobId || handledScanJobs.has(jobId)) return;
    handledScanJobs.add(jobId);
    var count = parseInt(el.dataset.itemsCreated, 10) || 0;
    if (count <= 0) return;
    document.dispatchEvent(new CustomEvent('claimos:items-added', {
      detail: { claimId: el.dataset.claimId, jobId: jobId, count: count }
    }));
  });

  // Accumulate count + reveal the banner.
  document.addEventListener('claimos:items-added', function (e) {
    var detail = e.detail || {};
    newItemsCount += (detail.count || 0);
    var banner = document.getElementById('items-new-banner');
    if (!banner) return;
    if (detail.claimId) banner.dataset.claimId = detail.claimId;
    var label = banner.querySelector('[data-new-items-label]');
    if (label) {
      label.textContent =
        newItemsCount + ' new item' + (newItemsCount === 1 ? '' : 's') + ' added';
    }
    banner.classList.remove('hidden');
  });

  // "View them": dedup-safe page-1 refresh + totals refresh + scroll to bottom.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-view-new-items]');
    if (!btn || !window.htmx) return;
    var banner = document.getElementById('items-new-banner');
    var claimId = banner ? banner.dataset.claimId : null;
    if (!claimId) return;

    htmx.ajax('GET', '/api/claims/' + claimId + '/items-rows',
      { target: '#items-tbody', swap: 'innerHTML' });
    htmx.ajax('GET', '/api/claims/' + claimId + '/items-summary',
      { target: '#items-summary', swap: 'outerHTML' });

    newItemsCount = 0;
    if (banner) banner.classList.add('hidden');

    var onSettle = function (ev) {
      if (ev.detail && ev.detail.target && ev.detail.target.id === 'items-tbody') {
        document.removeEventListener('htmx:afterSettle', onSettle);
        var tbody = document.getElementById('items-tbody');
        if (tbody) tbody.scrollIntoView({ block: 'end', behavior: 'smooth' });
      }
    };
    document.addEventListener('htmx:afterSettle', onSettle);
  });
})();

// Theme toggle: System / Light / Dark. Persisted in the `theme` cookie; the
// <html> class is set server-side on load, and flipped live here. color-scheme
// (in app.css) does the actual light/dark selection.
(function () {
  function applyTheme(mode) {
    const root = document.documentElement;
    root.classList.remove('light', 'dark');
    if (mode === 'light' || mode === 'dark') {
      root.classList.add(mode);
      document.cookie = 'theme=' + mode + '; path=/; max-age=31536000; samesite=lax';
    } else {
      document.cookie = 'theme=; path=/; max-age=0; samesite=lax'; // system => clear
    }
    syncActive(mode);
  }
  function currentMode() {
    if (document.documentElement.classList.contains('dark')) return 'dark';
    if (document.documentElement.classList.contains('light')) return 'light';
    return 'system';
  }
  function syncActive(mode) {
    document.querySelectorAll('[data-theme-set]').forEach(function (b) {
      const on = b.dataset.themeSet === mode;
      b.classList.toggle('bg-neutral-100', on);
      b.classList.toggle('text-neutral-900', on);
    });
  }
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-theme-set]');
    if (btn) applyTheme(btn.dataset.themeSet);
  });
  syncActive(currentMode());
})();
