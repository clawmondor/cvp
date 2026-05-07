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
