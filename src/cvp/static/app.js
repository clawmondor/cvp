// Tab switching — reads URL hash, shows matching panel, updates nav styles.
function initTabs() {
    const links = document.querySelectorAll('[data-tab]');
    const panels = document.querySelectorAll('[data-panel]');
    if (!links.length) return;

    function activate(name) {
        links.forEach(link => {
            const active = link.dataset.tab === name;
            link.classList.toggle('border-indigo-600', active);
            link.classList.toggle('text-indigo-600', active);
            link.classList.toggle('border-transparent', !active);
            link.classList.toggle('text-gray-500', !active);
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
    el.classList.remove('border-violet-500');
    el.classList.add('border-transparent');
  });
  const target = document.getElementById('crop-panel-' + cropId);
  if (target) target.classList.remove('hidden');
  const tab = document.getElementById('crop-tab-' + cropId);
  if (tab) {
    tab.classList.remove('border-transparent');
    tab.classList.add('border-violet-500');
  }
}

// ── Edit-form crop selector (Google Lens section) ────────────────────────
function showEditCrop(itemId, cropId) {
  document.querySelectorAll('[id^="edit-crop-panel-"]').forEach(function(el) {
    el.classList.add('hidden');
  });
  document.querySelectorAll('[id^="edit-crop-tab-"]').forEach(function(el) {
    el.classList.remove('border-violet-500');
    el.classList.add('border-transparent');
  });
  var panel = document.getElementById('edit-crop-panel-' + cropId);
  if (panel) panel.classList.remove('hidden');
  var tab = document.getElementById('edit-crop-tab-' + cropId);
  if (tab) {
    tab.classList.remove('border-transparent');
    tab.classList.add('border-violet-500');
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

    var matterId = zone.dataset.matterId;
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
        if (state === 'done') return 'text-green-600';
        if (state === 'failed') return 'text-red-600 cursor-pointer underline';
        if (state === 'uploading') return 'text-blue-600';
        return 'text-gray-400';
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
            htmx.ajax('GET', '/api/matters/' + matterId + '/evidence-grid', '#evidence-grid');
        }
    }

    function startJob(job) {
        inFlight += 1;
        setRowState(job.row, 'uploading', 'Uploading…');
        var form = new FormData();
        form.append('file', job.file, job.file.name);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/matters/' + matterId + '/evidence');
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
        zone.classList.add('border-indigo-500', 'bg-indigo-50');
    });
    zone.addEventListener('dragleave', function () {
        zone.classList.remove('border-indigo-500', 'bg-indigo-50');
    });
    zone.addEventListener('drop', function (e) {
        e.preventDefault();
        zone.classList.remove('border-indigo-500', 'bg-indigo-50');
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
    input.className = 'rounded border border-indigo-400 px-2 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500 flex-1';

    var save = document.createElement('button');
    save.type = 'submit';
    save.textContent = 'Save';
    save.className = 'rounded px-2 py-0.5 text-xs bg-indigo-600 text-white hover:bg-indigo-500';

    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = 'Cancel';
    cancel.className = 'rounded px-2 py-0.5 text-xs text-gray-500 hover:bg-gray-100';
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

// Delegated click: click anywhere on an item row (except an interactive control)
// opens that item's inline editor. Interactive controls — the crop "Edit crop"
// button, retailer search links, Comments, confirm toggle, Del — keep their own behavior.
document.addEventListener('click', function (e) {
    if (e.target.closest('a, button, input, select, textarea, label, summary')) return;
    var row = e.target.closest('tr[data-item-edit-url]');
    if (!row) return;
    htmx.ajax('GET', row.dataset.itemEditUrl, { target: '#' + row.id, swap: 'outerHTML' });
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

// Delegated hover: [data-crop-preview] → float an enlarged copy of the crop.
// pointer-events:none guarantees it never intercepts the "Edit crop" click.
(function () {
  var GAP = 12;
  var MAX = 400;
  var preview = null;

  function ensurePreview() {
    if (preview) return preview;
    preview = document.createElement('img');
    preview.id = 'crop-hover-preview';
    preview.style.cssText =
      'position:fixed;display:none;pointer-events:none;z-index:60;' +
      'max-width:' + MAX + 'px;max-height:' + MAX + 'px;object-fit:contain;' +
      'background:#fff;border:1px solid #d1d5db;border-radius:6px;' +
      'box-shadow:0 10px 25px rgba(0,0,0,0.25);padding:2px;';
    document.body.appendChild(preview);
    return preview;
  }

  function position(rect) {
    var p = preview;
    // Measure natural render size (bounded by MAX) after the image loads/paints.
    var w = Math.min(p.offsetWidth || MAX, MAX);
    var h = Math.min(p.offsetHeight || MAX, MAX);
    var left = rect.right + GAP;
    if (left + w > window.innerWidth) {
      left = rect.left - GAP - w; // flip to the left of the thumbnail
    }
    if (left < 0) left = GAP;
    var top = rect.top + rect.height / 2 - h / 2;
    if (top < GAP) top = GAP;
    if (top + h > window.innerHeight - GAP) top = window.innerHeight - GAP - h;
    if (top < GAP) top = GAP;
    p.style.left = left + 'px';
    p.style.top = top + 'px';
  }

  document.addEventListener('mouseover', function (e) {
    var thumb = e.target.closest('[data-crop-preview]');
    if (!thumb) return;
    var p = ensurePreview();
    var rect = thumb.getBoundingClientRect();
    if (p.getAttribute('src') !== thumb.dataset.cropPreview) {
      p.setAttribute('src', thumb.dataset.cropPreview);
      p.setAttribute('alt', thumb.dataset.cropPreviewAlt || '');
      p.onload = function () { position(rect); };
    }
    p.style.display = 'block';
    position(rect);
  });

  document.addEventListener('mouseout', function (e) {
    if (!e.target.closest('[data-crop-preview]')) return;
    if (preview) preview.style.display = 'none';
  });
})();

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
    btn.classList.remove('bg-violet-600', 'hover:bg-violet-700', 'transition');
    btn.classList.add('bg-gray-400', 'cursor-not-allowed');
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
    var matterId = sel.dataset.matterId;
    var fd = new FormData();
    fd.append('new_item_group_name', name.trim());
    fetch('/api/matters/' + matterId + '/evidence/' + fileId + '/item-group', {
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
// On submit, the items router calls find_or_create(matter_id, new_item_group_name)
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
// single document event: cvp:items-added {detail:{matterId, jobId, count}}.
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
    document.dispatchEvent(new CustomEvent('cvp:items-added', {
      detail: { matterId: el.dataset.matterId, jobId: jobId, count: count }
    }));
  });

  // Accumulate count + reveal the banner.
  document.addEventListener('cvp:items-added', function (e) {
    var detail = e.detail || {};
    newItemsCount += (detail.count || 0);
    var banner = document.getElementById('items-new-banner');
    if (!banner) return;
    if (detail.matterId) banner.dataset.matterId = detail.matterId;
    var label = banner.querySelector('[data-new-items-label]');
    if (label) {
      label.textContent =
        newItemsCount + ' new item' + (newItemsCount === 1 ? '' : 's') + ' added';
    }
    banner.classList.remove('hidden');
  });

  // Serialize the active items filters (from #items-controls) + sort state
  // (from #items-region data-*) into a querystring, omitting defaults.
  function currentItemsQuery() {
    var region = document.getElementById('items-region');
    var form = document.getElementById('items-controls');
    var params = new URLSearchParams();
    if (form) {
      new FormData(form).forEach(function (v, k) {
        if (k === 'sort' || k === 'dir') return;
        if (v === '' || (k === 'status' && v === 'all')) return;
        params.set(k, v);
      });
    }
    if (region) {
      var sort = region.dataset.sort || 'line';
      var dir = region.dataset.dir || 'asc';
      if (sort !== 'line' || dir !== 'asc') {
        params.set('sort', sort);
        params.set('dir', dir);
      }
    }
    var s = params.toString();
    return s ? '?' + s : '';
  }

  // "View them": refresh the region honoring the active sort/filter, refresh
  // totals, and scroll the region into view.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-view-new-items]');
    if (!btn || !window.htmx) return;
    var banner = document.getElementById('items-new-banner');
    var matterId = banner ? banner.dataset.matterId : null;
    if (!matterId) return;

    htmx.ajax('GET', '/api/matters/' + matterId + '/items-region' + currentItemsQuery(),
      { target: '#items-region', swap: 'outerHTML' });
    htmx.ajax('GET', '/api/matters/' + matterId + '/items-summary',
      { target: '#items-summary', swap: 'outerHTML' });

    newItemsCount = 0;
    if (banner) banner.classList.add('hidden');

    var onSettle = function (ev) {
      if (ev.detail && ev.detail.target && ev.detail.target.id === 'items-region') {
        document.removeEventListener('htmx:afterSettle', onSettle);
        var region = document.getElementById('items-region');
        if (region) region.scrollIntoView({ block: 'end', behavior: 'smooth' });
      }
    };
    document.addEventListener('htmx:afterSettle', onSettle);
  });
})();

// ---- Last-edited item: capture on edit-open, render a jump link ----
(function () {
  function LAST_EDITED_KEY(matterId) { return 'claimos:lastEdited:' + matterId; }

  function getMatterId() {
    var banner = document.getElementById('items-new-banner');
    return banner ? banner.dataset.matterId : null;
  }

  function readLastEdited() {
    var matterId = getMatterId();
    if (!matterId) return null;
    try {
      var raw = localStorage.getItem(LAST_EDITED_KEY(matterId));
      if (!raw) return null;
      var val = JSON.parse(raw);
      if (val && val.id) return val;
    } catch (_) {}
    return null;
  }

  function writeLastEdited(id, description) {
    var matterId = getMatterId();
    if (!matterId) return;
    try {
      localStorage.setItem(
        LAST_EDITED_KEY(matterId),
        JSON.stringify({ id: id, description: description || '' })
      );
    } catch (_) {}
  }

  function renderLastEditedLink() {
    var container = document.getElementById('last-edited-link');
    if (!container) return;
    var entry = readLastEdited();
    var descEl = container.querySelector('[data-last-edited-desc]');
    if (!entry) {
      container.classList.add('hidden');
      container.classList.remove('flex');
      return;
    }
    if (descEl) descEl.textContent = entry.description;
    container.classList.remove('hidden');
    container.classList.add('flex');
  }

  function clearLastEditedNote() {
    var container = document.getElementById('last-edited-link');
    var noteEl = container ? container.querySelector('[data-last-edited-note]') : null;
    if (noteEl) { noteEl.textContent = ''; noteEl.classList.add('hidden'); }
  }

  // Capture: piggyback on the row-click that opens the inline editor.
  document.addEventListener('click', function (e) {
    if (e.target.closest('a, button, input, select, textarea, label, summary')) return;
    var row = e.target.closest('tr[data-item-edit-url]');
    if (!row) return;
    var id = row.id.replace(/^item-row-/, '');
    writeLastEdited(id, row.dataset.itemDescription || '');
    renderLastEditedLink();
    clearLastEditedNote();
  });

  // Render on full load and whenever htmx swaps the items tab back in.
  document.addEventListener('DOMContentLoaded', renderLastEditedLink);
  document.addEventListener('htmx:afterSettle', function () {
    if (document.getElementById('last-edited-link')) renderLastEditedLink();
  });

  function flashRow(row) {
    var classes = ['ring-2', 'ring-indigo-400', 'bg-indigo-50'];
    row.classList.add.apply(row.classList, classes);
    setTimeout(function () {
      row.classList.remove.apply(row.classList, classes);
    }, 1500);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-jump-last-edited]');
    if (!btn) return;
    e.preventDefault();
    var container = document.getElementById('last-edited-link');
    var noteEl = container ? container.querySelector('[data-last-edited-note]') : null;
    var entry = readLastEdited();
    if (!entry) return;

    function showNote(text) {
      if (!noteEl) return;
      noteEl.textContent = text;
      noteEl.classList.remove('hidden');
    }
    function clearNote() {
      if (!noteEl) return;
      noteEl.textContent = '';
      noteEl.classList.add('hidden');
    }
    function jumpTo(row) {
      clearNote();
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      flashRow(row);
    }

    var existing = document.getElementById('item-row-' + entry.id);
    if (existing) { jumpTo(existing); return; }

    // Row not loaded yet: drive the existing infinite-scroll pagination
    // (the "Loading…" sentinel) until the row appears or pages run out.
    if (!window.htmx) { showNote('not in the current view'); return; }
    if (btn.dataset.jumpLoading) return; // guard re-entry while paging
    btn.dataset.jumpLoading = '1';
    showNote('loading…');

    var MAX_PAGES = 200; // safety cap vs. runaway loop
    var pages = 0;

    function step() {
      var row = document.getElementById('item-row-' + entry.id);
      if (row) { delete btn.dataset.jumpLoading; jumpTo(row); return; }
      var sentinel = document.querySelector('#items-tbody tr[hx-get*="/items-rows"]');
      if (!sentinel || pages >= MAX_PAGES) {
        delete btn.dataset.jumpLoading;
        showNote('not in the current view');
        return;
      }
      pages++;
      var url = sentinel.getAttribute('hx-get');
      htmx.ajax('GET', url, { target: sentinel, swap: 'outerHTML' })
        .then(step)
        .catch(function () {
          delete btn.dataset.jumpLoading;
          showNote('not in the current view');
        });
    }
    step();
  });
})();

// ---- Custom export template builder ----
(function () {
  function colList() { return document.getElementById('col-list'); }

  function serialize() {
    var list = colList();
    var json = document.getElementById('columns-json');
    if (!list || !json) return;
    var cols = [];
    list.querySelectorAll('.col-row').forEach(function (row) {
      var fieldKey = row.dataset.fieldKey || null;
      var header = (row.querySelector('.col-header') || {}).value || '';
      var staticInput = row.querySelector('.col-static');
      cols.push({
        field_key: fieldKey,
        header_label: header || null,
        static_value: fieldKey ? null : ((staticInput && staticInput.value) || ''),
      });
    });
    json.value = JSON.stringify(cols);
  }

  function makeRow(fieldKey, defaultHeader, isStatic) {
    var tpl = document.getElementById('col-row-template');
    var row = tpl.content.firstElementChild.cloneNode(true);
    var label = row.querySelector('.col-label');
    if (isStatic) {
      row.dataset.fieldKey = '';
      label.innerHTML = '<span class="font-semibold text-gray-500">Static:</span> '
        + '<input type="text" class="col-static ml-1 rounded border px-1 text-xs" placeholder="fixed value">';
      row.querySelector('.col-header').placeholder = 'header (required)';
    } else {
      row.dataset.fieldKey = fieldKey;
      label.innerHTML = '<span class="font-mono text-gray-700"></span>';
      label.firstChild.textContent = fieldKey;
      row.querySelector('.col-header').placeholder = defaultHeader || 'header';
    }
    return row;
  }

  document.addEventListener('click', function (e) {
    var addBtn = e.target.closest('[data-action="add-col"]');
    if (addBtn) {
      colList().appendChild(makeRow(addBtn.dataset.fieldKey, addBtn.dataset.defaultHeader, false));
      serialize();
      return;
    }
    if (e.target.closest('[data-action="add-static"]')) {
      colList().appendChild(makeRow(null, '', true));
      serialize();
      return;
    }
    var load = e.target.closest('[data-action="load-xactimate"]');
    if (load) {
      var keys = JSON.parse(load.dataset.keys || '[]');
      colList().innerHTML = '';
      keys.forEach(function (k) {
        var src = document.querySelector('[data-action="add-col"][data-field-key="' + k + '"]');
        colList().appendChild(makeRow(k, src ? src.dataset.defaultHeader : '', false));
      });
      serialize();
      return;
    }
    var up = e.target.closest('[data-action="move-col-up"]');
    if (up) {
      var r = up.closest('.col-row');
      if (r.previousElementSibling) r.parentNode.insertBefore(r, r.previousElementSibling);
      serialize();
      return;
    }
    var down = e.target.closest('[data-action="move-col-down"]');
    if (down) {
      var rd = down.closest('.col-row');
      if (rd.nextElementSibling) rd.parentNode.insertBefore(rd.nextElementSibling, rd);
      serialize();
      return;
    }
    var rm = e.target.closest('[data-action="remove-col"]');
    if (rm) { rm.closest('.col-row').remove(); serialize(); return; }
  });

  // keep hidden JSON in sync when header/static text changes
  document.addEventListener('input', function (e) {
    if (e.target.closest('.col-header, .col-static')) serialize();
  });
})();

// Back-to-top button: reveal once the page is scrolled, smooth-scroll to top on click.
(function () {
    var SHOW_AFTER = 300; // px scrolled before the button fades in

    function syncVisibility() {
        var btn = document.querySelector('[data-back-to-top]');
        if (!btn) return;
        if (window.scrollY > SHOW_AFTER) {
            btn.classList.remove('opacity-0', 'pointer-events-none');
            btn.classList.add('opacity-100');
        } else {
            btn.classList.add('opacity-0', 'pointer-events-none');
            btn.classList.remove('opacity-100');
        }
    }

    window.addEventListener('scroll', syncVisibility, { passive: true });
    document.addEventListener('DOMContentLoaded', syncVisibility);

    document.addEventListener('click', function (e) {
        if (e.target.closest('[data-back-to-top]')) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });
})();
