# CSP Inline Script Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all inline `<script>` blocks and inline event handlers (`onclick`, `hx-on`) out of templates and into external static JS files so the existing `Content-Security-Policy` header stops blocking them.

**Architecture:** Tier 1 (evidence drag-drop, room rename) moves verbatim into `app.js` with delegated event listeners replacing `onclick` attributes. Tier 2 (crop editor) extracts the canvas logic into a new `crop-editor.js`, passing server-rendered data via `data-*` attributes and a `<script type="application/json">` tag (non-executable, not subject to CSP). No Python or middleware changes.

**Tech Stack:** Vanilla JS, HTMX 1.9, Jinja2 templates, FastAPI static file serving.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/cvp/static/app.js` | Modify | Add `initEvidenceUpload()`, `startRename()`, delegated click for rename buttons, `htmx:afterRequest` listener for add-room form |
| `src/cvp/static/crop-editor.js` | **Create** | Full crop editor canvas logic; reads data attrs + JSON tag; activates on `htmx:afterSettle` |
| `src/cvp/templates/_tab_evidence.html` | Modify | Remove `<script>` block; remove `onclick` from drop-zone div |
| `src/cvp/templates/_tab_rooms.html` | Modify | Remove `<script>` block; add `id="add-room-form"` to form; remove `hx-on::after-request` |
| `src/cvp/templates/_room_li.html` | Modify | Replace `onclick="startRename(...)"` with `data-rename-room-id="{{ room.id }}"` |
| `src/cvp/templates/_crop_editor.html` | Modify | Remove `<script>` block; add `data-*` attrs and JSON script tag; replace close button `onclick` |
| `src/cvp/templates/base.html` | Modify | Add `<script src="/static/crop-editor.js" defer>` |

---

## Task 1: Evidence drag-drop — move to app.js

**Files:**
- Modify: `src/cvp/static/app.js`
- Modify: `src/cvp/templates/_tab_evidence.html`

- [ ] **Step 1: Add `initEvidenceUpload()` to app.js**

Append this to `src/cvp/static/app.js` (after the existing crop-edit deep-link block):

```javascript
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
```

- [ ] **Step 2: Remove inline script and onclick from `_tab_evidence.html`**

In `src/cvp/templates/_tab_evidence.html`:

Remove the entire `<script>` block at the bottom (lines 27–57):
```html
<script>
(function () {
  ...
})();
</script>
```

Also remove the `onclick` attribute from the drop-zone div. Change:
```html
<div id="drop-zone"
     class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white px-6 py-10 text-center transition-colors hover:border-indigo-400 cursor-pointer"
     onclick="document.getElementById('evidence-input').click()">
```
To:
```html
<div id="drop-zone"
     class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white px-6 py-10 text-center transition-colors hover:border-indigo-400 cursor-pointer">
```

- [ ] **Step 3: Verify manually**

Run: `uv run dev`

Navigate to a matter detail page, click the Evidence tab. Confirm:
- Clicking the drop zone opens the file picker
- Dragging a file onto the zone highlights it and triggers upload on drop
- No CSP errors in the browser console

- [ ] **Step 4: Commit**

```bash
git add src/cvp/static/app.js src/cvp/templates/_tab_evidence.html
git commit -m "feat: move evidence drag-drop from inline script to app.js"
```

---

## Task 2: Room rename and add-room form — move to app.js

**Files:**
- Modify: `src/cvp/static/app.js`
- Modify: `src/cvp/templates/_tab_rooms.html`
- Modify: `src/cvp/templates/_room_li.html`

- [ ] **Step 1: Add room JS to app.js**

Append to `src/cvp/static/app.js`:

```javascript
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
    var roomId = e.target.dataset.renameRoomId;
    if (roomId) startRename(roomId);
});

// Replace hx-on::after-request on add-room form (HTMX uses new Function() for hx-on, blocked by CSP)
document.addEventListener('htmx:afterRequest', function (e) {
    if (e.detail.elt && e.detail.elt.id === 'add-room-form' && e.detail.successful) {
        e.detail.elt.reset();
        var empty = document.getElementById('rooms-empty');
        if (empty) empty.remove();
    }
});
```

- [ ] **Step 2: Update `_tab_rooms.html`**

Add `id="add-room-form"` to the form and remove `hx-on::after-request`. Change:
```html
<form hx-post="/api/matters/{{ matter.id }}/rooms"
      hx-target="#rooms-list"
      hx-swap="beforeend"
      hx-on::after-request="if(event.detail.successful){ this.reset(); const e=document.getElementById('rooms-empty'); if(e) e.remove(); }"
      class="flex items-center gap-2">
```
To:
```html
<form id="add-room-form"
      hx-post="/api/matters/{{ matter.id }}/rooms"
      hx-target="#rooms-list"
      hx-swap="beforeend"
      class="flex items-center gap-2">
```

Remove the entire `<script>` block at the bottom of the file (the `function startRename(roomId) { ... }` block including its `<script>` tags).

- [ ] **Step 3: Update `_room_li.html`**

Replace the `onclick` on the Rename button. Change:
```html
<button
  onclick="startRename('{{ room.id }}')"
  class="hidden rounded px-2 py-0.5 text-xs text-gray-500 hover:bg-gray-100 group-hover:inline-flex">
  Rename
</button>
```
To:
```html
<button
  data-rename-room-id="{{ room.id }}"
  class="hidden rounded px-2 py-0.5 text-xs text-gray-500 hover:bg-gray-100 group-hover:inline-flex">
  Rename
</button>
```

- [ ] **Step 4: Verify manually**

Run: `uv run dev`

Navigate to a matter detail page, click the Rooms tab. Confirm:
- Adding a room via the form clears the input after success and removes the "No rooms yet" placeholder
- Hovering a room reveals the Rename button; clicking it shows the inline rename form
- Saving a rename updates the room name
- No CSP errors in the browser console

- [ ] **Step 5: Commit**

```bash
git add src/cvp/static/app.js src/cvp/templates/_tab_rooms.html src/cvp/templates/_room_li.html
git commit -m "feat: move room rename and add-room reset from inline script to app.js"
```

---

## Task 3: Create crop-editor.js

**Files:**
- Create: `src/cvp/static/crop-editor.js`

This file contains the full canvas editor logic. It activates via `htmx:afterSettle` — when the crop editor HTML is swapped in by HTMX, this listener finds the new container and initialises it.

- [ ] **Step 1: Create `src/cvp/static/crop-editor.js`**

```javascript
(function () {

  // Close button: data-crop-editor-close="<ef-id>" removes the editor container
  document.addEventListener('click', function (e) {
    var efId = e.target.dataset.cropEditorClose;
    if (!efId) return;
    var container = document.getElementById('crop-editor-' + efId);
    if (container) container.remove();
  });

  // Activate any crop editor containers swapped in by HTMX
  document.addEventListener('htmx:afterSettle', function () {
    document.querySelectorAll('[data-init="crop-editor"]:not([data-ready])').forEach(function (container) {
      container.dataset.ready = '1';
      initCropEditor(container);
    });
  });

  function initCropEditor(container) {
    var EF_ID = container.dataset.efId;
    var IMG_W = parseInt(container.dataset.imgW, 10);
    var IMG_H = parseInt(container.dataset.imgH, 10);
    var IMG_SRC = container.dataset.imgSrc;

    var cropsEl = document.getElementById('crop-data-' + EF_ID);
    var CROPS = cropsEl ? JSON.parse(cropsEl.textContent) : [];

    var canvas = document.getElementById('ce-canvas-' + EF_ID);
    var ctx = canvas.getContext('2d');
    var sidebar = document.getElementById('ce-sidebar-' + EF_ID);
    var recropBtn = document.getElementById('ce-recrop-btn-' + EF_ID);
    var statusEl = document.getElementById('ce-status-' + EF_ID);

    var MAX_W = 600;
    var scale = Math.min(1, MAX_W / IMG_W);
    canvas.width = Math.round(IMG_W * scale);
    canvas.height = Math.round(IMG_H * scale);

    var bgImg = new Image();
    bgImg.src = IMG_SRC;
    bgImg.onload = draw;

    var HANDLE_SIZE = 8;
    var MIN_SIZE = 10;

    var boxes = CROPS.map(function (c) {
      return {
        id: c.id,
        description: c.description,
        left: c.bbox[0], upper: c.bbox[1], right: c.bbox[2], lower: c.bbox[3],
        claudeLeft: c.claude_bbox[0], claudeUpper: c.claude_bbox[1],
        claudeRight: c.claude_bbox[2], claudeLower: c.claude_bbox[3],
        adjusted: c.adjusted,
      };
    });

    var selectedIdx = null;
    var drag = null;

    function tc(px) { return Math.round(px * scale); }
    function fc(cx) { return Math.round(cx / scale); }

    function getHandles(box) {
      var l = tc(box.left), u = tc(box.upper), r = tc(box.right), lo = tc(box.lower);
      var mx = Math.round((l + r) / 2), my = Math.round((u + lo) / 2);
      return [
        {x:l,y:u}, {x:mx,y:u}, {x:r,y:u}, {x:r,y:my},
        {x:r,y:lo}, {x:mx,y:lo}, {x:l,y:lo}, {x:l,y:my},
      ];
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (bgImg.complete && bgImg.naturalWidth) ctx.drawImage(bgImg, 0, 0, canvas.width, canvas.height);
      boxes.forEach(function (box, i) {
        var l = tc(box.left), u = tc(box.upper);
        var w = tc(box.right) - l, h = tc(box.lower) - u;
        var isSelected = (i === selectedIdx);

        if (isSelected) {
          ctx.fillStyle = 'rgba(6,182,212,0.18)';
          ctx.fillRect(l, u, w, h);
          ctx.strokeStyle = '#06b6d4';
          ctx.lineWidth = 3;
        } else {
          ctx.strokeStyle = box.adjusted ? '#f59e0b' : '#6366f1';
          ctx.lineWidth = 1.5;
        }
        ctx.strokeRect(l, u, w, h);

        ctx.font = 'bold 10px sans-serif';
        var label = box.description ? box.description.slice(0, 20) : String(i + 1);
        var textW = ctx.measureText(label).width;
        var padX = 3, padY = 2, lineH = 12;
        var bgW = Math.min(w - 2, textW + padX * 2);
        ctx.fillStyle = isSelected ? 'rgba(6,182,212,0.85)' : 'rgba(0,0,0,0.5)';
        ctx.fillRect(l, u, bgW, lineH + padY * 2);
        ctx.fillStyle = '#fff';
        ctx.fillText(label, l + padX, u + lineH);

        if (isSelected) {
          getHandles(box).forEach(function (h) {
            ctx.fillStyle = '#fff';
            ctx.fillRect(h.x - HANDLE_SIZE / 2, h.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
            ctx.strokeStyle = '#06b6d4';
            ctx.lineWidth = 1.5;
            ctx.strokeRect(h.x - HANDLE_SIZE / 2, h.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
          });
        }
      });
    }

    function hitHandle(box, cx, cy) {
      return getHandles(box).findIndex(function (h) {
        return Math.abs(cx - h.x) <= HANDLE_SIZE && Math.abs(cy - h.y) <= HANDLE_SIZE;
      });
    }

    function hitBox(box, cx, cy) {
      return cx >= tc(box.left) && cx <= tc(box.right) &&
             cy >= tc(box.upper) && cy <= tc(box.lower);
    }

    canvas.addEventListener('mousedown', function (e) {
      var rect = canvas.getBoundingClientRect();
      var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      if (selectedIdx !== null) {
        var hi = hitHandle(boxes[selectedIdx], cx, cy);
        if (hi >= 0) {
          drag = {type: 'handle', handleIdx: hi, startX: cx, startY: cy, origBox: Object.assign({}, boxes[selectedIdx])};
          return;
        }
      }
      for (var i = boxes.length - 1; i >= 0; i--) {
        if (hitBox(boxes[i], cx, cy)) {
          selectedIdx = i;
          drag = {type: 'move', startX: cx, startY: cy, origBox: Object.assign({}, boxes[i])};
          draw();
          updateSidebar();
          return;
        }
      }
      selectedIdx = null; drag = null; draw(); updateSidebar();
    });

    canvas.addEventListener('mousemove', function (e) {
      if (!drag) return;
      var rect = canvas.getBoundingClientRect();
      var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      var dx = fc(cx - drag.startX), dy = fc(cy - drag.startY);
      var ob = drag.origBox, box = boxes[selectedIdx];
      if (drag.type === 'move') {
        var w = ob.right - ob.left, h = ob.lower - ob.upper;
        box.left  = Math.max(0, Math.min(IMG_W - w, ob.left + dx));
        box.upper = Math.max(0, Math.min(IMG_H - h, ob.upper + dy));
        box.right = box.left + w;
        box.lower = box.upper + h;
      } else {
        var hi = drag.handleIdx;
        var l = ob.left, u = ob.upper, r = ob.right, lo = ob.lower;
        if ([0, 6, 7].indexOf(hi) >= 0) l  = Math.max(0,     Math.min(r - MIN_SIZE,  ob.left  + dx));
        if ([2, 3, 4].indexOf(hi) >= 0) r  = Math.min(IMG_W, Math.max(l + MIN_SIZE,  ob.right + dx));
        if ([0, 1, 2].indexOf(hi) >= 0) u  = Math.max(0,     Math.min(lo - MIN_SIZE, ob.upper + dy));
        if ([4, 5, 6].indexOf(hi) >= 0) lo = Math.min(IMG_H, Math.max(u + MIN_SIZE,  ob.lower + dy));
        box.left = l; box.upper = u; box.right = r; box.lower = lo;
      }
      updateSidebarInputs(); draw();
    });

    canvas.addEventListener('mouseup', function () {
      if (!drag) return;
      drag = null;
      if (selectedIdx !== null) autosave(selectedIdx);
    });

    function updateSidebar() {
      if (selectedIdx === null) {
        sidebar.innerHTML = '<p class="text-xs text-gray-400">Click a box to select it.</p>';
        return;
      }
      var box = boxes[selectedIdx];
      sidebar.innerHTML = '';

      var title = document.createElement('p');
      title.className = 'text-xs font-semibold text-gray-700 mb-2';
      title.textContent = '#' + (selectedIdx + 1) + ' ' + box.description;
      sidebar.appendChild(title);

      var grid = document.createElement('div');
      grid.className = 'grid grid-cols-2 gap-1 text-xs';
      [['Left', 'left', IMG_W], ['Upper', 'upper', IMG_H], ['Right', 'right', IMG_W], ['Lower', 'lower', IMG_H]].forEach(function (f) {
        var lbl = document.createElement('label');
        lbl.className = 'text-gray-500 self-center';
        lbl.textContent = f[0];
        var inp = document.createElement('input');
        inp.id = 'ce-' + f[1] + '-' + EF_ID;
        inp.type = 'number';
        inp.value = box[f[1]];
        inp.min = '0';
        inp.max = String(f[2]);
        inp.className = 'border rounded px-1 py-0.5 text-right';
        grid.appendChild(lbl);
        grid.appendChild(inp);
      });
      sidebar.appendChild(grid);

      var errEl = document.createElement('p');
      errEl.id = 'ce-err-' + EF_ID;
      errEl.className = 'mt-1 text-xs text-red-500 hidden';
      sidebar.appendChild(errEl);

      var resetBtn = document.createElement('button');
      resetBtn.className = 'mt-2 text-xs text-indigo-500 hover:underline';
      resetBtn.textContent = 'Reset to Claude bbox';
      resetBtn.addEventListener('click', function () {
        window['ceReset_' + EF_ID.replace(/-/g, '_')]();
      });
      sidebar.appendChild(resetBtn);

      ['left', 'upper', 'right', 'lower'].forEach(function (f) {
        var el = document.getElementById('ce-' + f + '-' + EF_ID);
        if (!el) return;
        el.addEventListener('blur', commitInputs);
        el.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') commitInputs(); });
      });
    }

    window['ceReset_' + EF_ID.replace(/-/g, '_')] = function () {
      if (selectedIdx === null) return;
      var box = boxes[selectedIdx];
      fetch('/api/item-crops/' + box.id + '/adjust-bbox', {method: 'DELETE'}).then(function (r) {
        if (!r.ok) return;
        box.left = box.claudeLeft; box.upper = box.claudeUpper;
        box.right = box.claudeRight; box.lower = box.claudeLower;
        box.adjusted = false;
        draw(); updateSidebar(); updateRecropButton();
      });
    };

    window['ceSelect_' + EF_ID.replace(/-/g, '_')] = function (cropId) {
      var idx = boxes.findIndex(function (b) { return b.id === cropId; });
      if (idx >= 0) {
        selectedIdx = idx;
        draw();
        updateSidebar();
        canvas.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      }
    };

    function updateSidebarInputs() {
      if (selectedIdx === null) return;
      var box = boxes[selectedIdx];
      ['left', 'upper', 'right', 'lower'].forEach(function (f) {
        var el = document.getElementById('ce-' + f + '-' + EF_ID);
        if (el) el.value = box[f];
      });
    }

    function commitInputs() {
      if (selectedIdx === null) return;
      var box = boxes[selectedIdx];
      var l  = parseInt(document.getElementById('ce-left-'  + EF_ID).value, 10);
      var u  = parseInt(document.getElementById('ce-upper-' + EF_ID).value, 10);
      var r  = parseInt(document.getElementById('ce-right-' + EF_ID).value, 10);
      var lo = parseInt(document.getElementById('ce-lower-' + EF_ID).value, 10);
      var errEl = document.getElementById('ce-err-' + EF_ID);
      if (l >= r || u >= lo) {
        errEl.textContent = 'left < right and upper < lower required';
        errEl.classList.remove('hidden');
        return;
      }
      errEl.classList.add('hidden');
      box.left = l; box.upper = u; box.right = r; box.lower = lo;
      draw(); autosave(selectedIdx);
    }

    function autosave(idx) {
      var box = boxes[idx];
      fetch('/api/item-crops/' + box.id + '/adjust-bbox', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({left: box.left, upper: box.upper, right: box.right, lower: box.lower}),
      }).then(function (r) {
        if (r.ok) { box.adjusted = true; draw(); updateRecropButton(); }
      });
    }

    function updateRecropButton() {
      var n = boxes.filter(function (b) { return b.adjusted; }).length;
      recropBtn.textContent = 'Re-crop adjusted items (' + n + ')';
      recropBtn.disabled = n === 0;
    }

    recropBtn.addEventListener('click', function () {
      recropBtn.disabled = true;
      statusEl.textContent = 'Re-cropping…';
      fetch('/api/evidence/' + EF_ID + '/recrop', {method: 'POST'})
        .then(function (r) { return r.json(); })
        .then(function (data) {
          statusEl.textContent = 'Done — ' + data.recropped.length + ' crop(s) updated.';
          var ts = Date.now();
          data.recropped.forEach(function (cropId) {
            document.querySelectorAll('img[src*="' + cropId + '"]').forEach(function (img) {
              img.src = img.src.split('?')[0] + '?v=' + ts;
            });
          });
          updateRecropButton();
        })
        .catch(function () {
          statusEl.textContent = 'Error — check console.';
          recropBtn.disabled = false;
        });
    });

    updateRecropButton();
    draw();
  }

})();
```

- [ ] **Step 2: Verify the file was created**

```bash
wc -l src/cvp/static/crop-editor.js
```

Expected: ~200+ lines, no errors from your editor.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/static/crop-editor.js
git commit -m "feat: add crop-editor.js to replace inline canvas script"
```

---

## Task 4: Update `_crop_editor.html` and load crop-editor.js

**Files:**
- Modify: `src/cvp/templates/_crop_editor.html`
- Modify: `src/cvp/templates/base.html`

- [ ] **Step 1: Update the container div in `_crop_editor.html`**

Replace the opening `<div>` tag. Change:
```html
<div id="crop-editor-{{ evidence_file.id }}"
     class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
```
To:
```html
<div id="crop-editor-{{ evidence_file.id }}"
     data-init="crop-editor"
     data-ef-id="{{ evidence_file.id }}"
     data-img-w="{{ img_w }}"
     data-img-h="{{ img_h }}"
     data-img-src="/files/{{ stored_path }}"
     class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
```

- [ ] **Step 2: Replace the close button's onclick**

Change:
```html
<button onclick="document.getElementById('crop-editor-{{ evidence_file.id }}').remove()"
        class="text-xs text-gray-400 hover:text-gray-700">✕ Close</button>
```
To:
```html
<button data-crop-editor-close="{{ evidence_file.id }}"
        class="text-xs text-gray-400 hover:text-gray-700">✕ Close</button>
```

- [ ] **Step 3: Add the crops JSON tag and remove the inline script**

After the closing `</div>` of the entire component, add the JSON data tag. Remove the existing `<script>` block entirely. The end of the file should become:

```html
    </div>
  </div>
</div>

<script type="application/json" id="crop-data-{{ evidence_file.id }}">{{ crops_json | safe }}</script>
```

(The `<script>` block that started with `(function () {` is deleted entirely.)

- [ ] **Step 4: Add crop-editor.js to base.html**

In `src/cvp/templates/base.html`, after the existing `<script src="/static/app.js" defer></script>` line, add:

```html
  <script src="/static/crop-editor.js" defer></script>
```

- [ ] **Step 5: Verify manually**

Run: `uv run dev`

Navigate to a matter detail page that has evidence with crops. Click "Edit crop" on an evidence file. Confirm:
- The crop editor panel opens
- The canvas renders the background image with crop boxes drawn on it
- Clicking a box selects it (cyan highlight + handles)
- Dragging a box or handle moves/resizes it and autosaves
- The coordinate inputs in the sidebar update as you drag
- "Reset to Claude bbox" button appears and works
- "Re-crop adjusted items" button enables when adjustments exist
- The ✕ Close button removes the editor panel
- No CSP errors in the browser console

Also confirm the deep-link auto-init still works: navigate to a matter URL with `?file=<uuid>&crop=<uuid>#evidence` — the editor should open and pre-select the crop.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/templates/_crop_editor.html src/cvp/templates/base.html
git commit -m "feat: move crop editor from inline script to crop-editor.js"
```

---

## Task 5: Run full test suite and lint

- [ ] **Step 1: Run linter**

```bash
uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/ -q
```

Expected: all tests pass (the pre-existing `test_splash_page` failure is unrelated to this work — confirm no new failures).

- [ ] **Step 3: Final commit if any lint fixes were needed**

If ruff made auto-fixes:
```bash
uv run ruff format .
git add -u
git commit -m "chore: ruff format after CSP inline script removal"
```
