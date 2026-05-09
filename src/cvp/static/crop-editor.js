(function () {

  // Close button: data-crop-editor-close="<ef-id>" removes the editor container
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-crop-editor-close]');
    if (!btn) return;
    var container = document.getElementById('crop-editor-' + btn.dataset.cropEditorClose);
    if (container) container.remove();
  });

  // Activate any crop editor containers swapped in by HTMX
  document.addEventListener('htmx:afterSettle', function () {
    document.querySelectorAll('[data-init="crop-editor"]:not([data-ready])').forEach(function (container) {
      container.dataset.ready = '1';
      initCropEditor(container);
    });
  });

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
  }

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

    // toggleCropEditor() prevents two editors for the same EF_ID from coexisting in the DOM.
    window['ceReset_' + EF_ID.replace(/-/g, '_')] = function () {
      if (selectedIdx === null) return;
      var box = boxes[selectedIdx];
      fetch('/api/item-crops/' + box.id + '/adjust-bbox', {method: 'DELETE', headers: {'X-CSRF-Token': csrfToken()}}).then(function (r) {
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
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
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
      fetch('/api/evidence/' + EF_ID + '/recrop', {method: 'POST', headers: {'X-CSRF-Token': csrfToken()}})
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
