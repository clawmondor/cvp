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
document.addEventListener('DOMContentLoaded', function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var csrf = meta ? meta.content : '';
    if (!csrf) return;

    // HTMX requests pick up X-CSRF-Token from hx-headers on <body>
    document.body.setAttribute('hx-headers', JSON.stringify({'X-CSRF-Token': csrf}));

    // Plain method="post" forms get a hidden _csrf field so the server can validate
    document.querySelectorAll('form').forEach(function (form) {
        if ((form.getAttribute('method') || '').toUpperCase() === 'POST') {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = '_csrf';
            input.value = csrf;
            form.appendChild(input);
        }
    });
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
function toggleCropEditor(fileId) {
  const existing = document.getElementById('crop-editor-' + fileId);
  if (existing) {
    existing.remove();
    return;
  }
  const grid = document.getElementById('evidence-grid');
  htmx.ajax('GET', '/api/evidence/' + fileId + '/crop-editor', {
    target: grid,
    swap: 'afterend',
  });
}

// ── Crop-edit deep-link auto-init ────────────────────────────────────────────
// When the page is opened via the "Edit crop" thumbnail link (?file=&crop=#evidence),
// auto-open the crop editor for the evidence file and pre-select the item's crop.
document.addEventListener('DOMContentLoaded', function () {
  var params = new URLSearchParams(window.location.search);
  var fileId = params.get('file');
  var cropId = params.get('crop');
  if (!fileId) return;

  // The hash is already #evidence; initTabs (also on DOMContentLoaded) activates the panel.
  toggleCropEditor(fileId);

  if (cropId) {
    var settled = false;
    // The handler stays attached until ceSelect_* exists (crop editor IIFE has run).
    // removeEventListener is intentionally inside the if-block so unrelated HTMX
    // settle events (before the editor loads) don't remove the listener prematurely.
    function handler() {
      var fnName = 'ceSelect_' + fileId.replace(/-/g, '_');
      if (window[fnName]) {
        settled = true;
        window[fnName](cropId);
        document.removeEventListener('htmx:afterSettle', handler);
      }
    }
    document.addEventListener('htmx:afterSettle', handler);
    // Failsafe: remove listener if the crop editor never loads (e.g. network error).
    setTimeout(function () {
      if (!settled) document.removeEventListener('htmx:afterSettle', handler);
    }, 10000);
  }
});

// ── Evidence drag-drop upload ─────────────────────────────────────────────
function initEvidenceUpload() {
    var zone = document.getElementById('drop-zone');
    var input = document.getElementById('evidence-input');
    var form = document.getElementById('evidence-form');
    if (!zone) return;

    function submitFiles(fileList) {
        if (!fileList || fileList.length === 0) return;
        var dt = new DataTransfer();
        Array.from(fileList).forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
        htmx.trigger(form, 'submit');
    }

    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () { submitFiles(input.files); });
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
        submitFiles(e.dataTransfer.files);
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

// Delegated click: data-toggle-crop-editor → toggleCropEditor(fileId)
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-toggle-crop-editor]');
    if (btn) toggleCropEditor(btn.dataset.toggleCropEditor);
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

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-job-id]').forEach(function (el) {
    var jobId = el.dataset.jobId;
    try {
      if (sessionStorage.getItem('dismissed_banner_' + jobId)) el.remove();
    } catch (_) {}
  });
});
