/* Tableau de bord personnalisable (par utilisateur).
 * - Mode edition : bouton « Personnaliser » -> affiche les barres de bloc, le
 *   tiroir des blocs masques, et active le glisser-deposer.
 * - Masquer/afficher : deplace le bloc entre la grille (#dashGrid) et le tiroir
 *   (#dashTrayItems).
 * - Persistance : POST JSON vers data-save-url (CSRF via en-tete X-CSRFToken),
 *   sans rechargement. La disposition est propre a l'utilisateur.
 */
(function () {
    'use strict';
    var grid = document.getElementById('dashGrid');
    if (!grid) return;
    var customizeBtn = document.getElementById('dashCustomizeBtn');
    if (!customizeBtn) return; // fonctionnalite desactivee globalement

    var editControls = document.getElementById('dashEditControls');
    var doneBtn = document.getElementById('dashDoneBtn');
    var resetBtn = document.getElementById('dashResetBtn');
    var tray = document.getElementById('dashTray');
    var trayItems = document.getElementById('dashTrayItems');
    var trayEmpty = document.getElementById('dashTrayEmpty');
    var saveUrl = grid.getAttribute('data-save-url');
    var csrf = grid.getAttribute('data-csrf');

    function post(payload) {
        return fetch(saveUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify(payload)
        });
    }

    function gridKeys() {
        return Array.prototype.map.call(
            grid.querySelectorAll(':scope > .dash-widget'), function (e) { return e.dataset.widget; });
    }
    function hiddenKeys() {
        if (!trayItems) return [];
        return Array.prototype.map.call(
            trayItems.querySelectorAll(':scope > .dash-widget'), function (e) { return e.dataset.widget; });
    }

    // Largeurs (colonnes) courantes des blocs visibles, lues sur --w-span.
    function spansMap() {
        var out = {};
        Array.prototype.forEach.call(grid.querySelectorAll(':scope > .dash-widget'), function (e) {
            var s = parseInt(e.style.getPropertyValue('--w-span'), 10);
            if (s) out[e.dataset.widget] = s;
        });
        return out;
    }

    // Ordre courant des vignettes de synthese (bloc « stats »).
    var statGrid = document.querySelector('.stat-grid');
    function cardsOrder() {
        if (!statGrid) return undefined;
        return Array.prototype.map.call(
            statGrid.querySelectorAll(':scope > .stat-card'),
            function (e) { return e.dataset.card; }).filter(Boolean);
    }

    function persist() {
        post({ order: gridKeys(), hidden: hiddenKeys(), spans: spansMap(), cards: cardsOrder() });
    }

    // Icone du bouton oeil selon l'emplacement (grille = masquer, tiroir = afficher).
    function refreshToggleIcons() {
        Array.prototype.forEach.call(document.querySelectorAll('.dash-widget .dash-toggle'), function (btn) {
            var inTray = trayItems && trayItems.contains(btn);
            var icon = btn.querySelector('i');
            icon.className = 'bi ' + (inTray ? 'bi-eye' : 'bi-eye-slash');
            btn.title = inTray ? 'Afficher ce bloc' : 'Masquer ce bloc';
        });
    }

    function refreshTrayEmpty() {
        if (!trayEmpty) return;
        trayEmpty.classList.toggle('d-none', hiddenKeys().length > 0);
    }

    function setDraggable(on) {
        Array.prototype.forEach.call(grid.querySelectorAll(':scope > .dash-widget'), function (el) {
            if (on) { el.setAttribute('draggable', 'true'); }
            else { el.removeAttribute('draggable'); }
        });
    }

    // ---- Masquer / afficher ----
    function onToggle(e) {
        var btn = e.target.closest('.dash-toggle');
        if (!btn) return;
        e.preventDefault();
        var widget = btn.closest('.dash-widget');
        if (!widget) return;
        if (trayItems && trayItems.contains(widget)) {
            grid.appendChild(widget);            // reafficher : en fin de grille
            widget.setAttribute('draggable', 'true');
        } else if (trayItems) {
            trayItems.insertBefore(widget, trayEmpty); // masquer
            widget.removeAttribute('draggable');
        }
        refreshToggleIcons();
        refreshTrayEmpty();
        persist();
    }
    grid.addEventListener('click', onToggle);
    if (trayItems) trayItems.addEventListener('click', onToggle);

    // ---- Glisser-deposer (reordonnancement dans la grille) ----
    var dragged = null;

    function afterElement(x, y) {
        var els = grid.querySelectorAll(':scope > .dash-widget:not(.dragging)');
        var best = null, bestDist = Infinity;
        Array.prototype.forEach.call(els, function (el) {
            var b = el.getBoundingClientRect();
            var cx = b.left + b.width / 2, cy = b.top + b.height / 2;
            var d = Math.hypot(x - cx, y - cy);
            if (d < bestDist) { bestDist = d; best = { el: el, b: b, cx: cx, cy: cy }; }
        });
        if (!best) return null;
        var sameRow = Math.abs(best.cy - y) < best.b.height / 2;
        var before = sameRow ? (x < best.cx) : (y < best.cy);
        return before ? best.el : best.el.nextElementSibling;
    }

    grid.addEventListener('dragstart', function (e) {
        var w = e.target.closest('.dash-widget');
        if (!w || !w.getAttribute('draggable')) return;
        dragged = w;
        w.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        try { e.dataTransfer.setData('text/plain', w.dataset.widget); } catch (err) { /* IE */ }
    });

    grid.addEventListener('dragover', function (e) {
        if (!dragged) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        var ref = afterElement(e.clientX, e.clientY);
        if (ref == null) { grid.appendChild(dragged); }
        else if (ref !== dragged) { grid.insertBefore(dragged, ref); }
    });

    grid.addEventListener('drop', function (e) { e.preventDefault(); });

    grid.addEventListener('dragend', function () {
        if (!dragged) return;
        dragged.classList.remove('dragging');
        dragged = null;
        persist();
    });

    // ---- Redimensionnement en largeur (colonnes de la grille 12) ----
    var SPAN_MIN = 3, SPAN_MAX = 12;

    function setSpanBadge(widget, span) {
        var name = widget.querySelector('.dash-widget-name');
        if (!name) return;
        var badge = name.querySelector('.dash-span-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'dash-span-badge ms-1';
            name.appendChild(badge);
        }
        badge.textContent = span + '/12';
    }
    function clearSpanBadge(widget) {
        var b = widget.querySelector('.dash-span-badge');
        if (b) b.remove();
    }

    grid.addEventListener('pointerdown', function (e) {
        var handle = e.target.closest('.dash-resize');
        if (!handle) return;
        var widget = handle.closest('.dash-widget');
        if (!widget || !grid.contains(widget)) return;
        e.preventDefault();
        e.stopPropagation();
        // Empeche le glisser-deposer natif de demarrer pendant le redimensionnement.
        widget.removeAttribute('draggable');
        widget.classList.add('resizing');

        var cs = getComputedStyle(grid);
        var gap = parseFloat(cs.columnGap) || 0;
        var colW = (grid.clientWidth - gap * (SPAN_MAX - 1)) / SPAN_MAX;
        var moved = false;

        function onMove(ev) {
            var rect = widget.getBoundingClientRect();
            var width = ev.clientX - rect.left;
            var span = Math.round((width + gap) / (colW + gap));
            span = Math.max(SPAN_MIN, Math.min(SPAN_MAX, span));
            if (String(span) !== widget.style.getPropertyValue('--w-span')) {
                widget.style.setProperty('--w-span', span);
            }
            setSpanBadge(widget, span);
            moved = true;
        }
        function onUp() {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            widget.classList.remove('resizing');
            widget.setAttribute('draggable', 'true');
            clearSpanBadge(widget);
            if (moved) persist();
        }
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
    });

    // ---- Reordonnancement des vignettes de synthese (bloc « stats ») ----
    var draggedCard = null;

    function setCardsDraggable(on) {
        if (!statGrid) return;
        Array.prototype.forEach.call(statGrid.querySelectorAll(':scope > .stat-card'), function (c) {
            if (on) { c.setAttribute('draggable', 'true'); }
            else { c.removeAttribute('draggable'); }
        });
    }

    function cardAfter(x, y) {
        var best = null, bestDist = Infinity;
        Array.prototype.forEach.call(statGrid.querySelectorAll(':scope > .stat-card:not(.dragging)'), function (el) {
            var b = el.getBoundingClientRect();
            var cx = b.left + b.width / 2, cy = b.top + b.height / 2;
            var d = Math.hypot(x - cx, y - cy);
            if (d < bestDist) { bestDist = d; best = { el: el, b: b, cx: cx, cy: cy }; }
        });
        if (!best) return null;
        var sameRow = Math.abs(best.cy - y) < best.b.height / 2;
        var before = sameRow ? (x < best.cx) : (y < best.cy);
        return before ? best.el : best.el.nextElementSibling;
    }

    if (statGrid) {
        statGrid.addEventListener('dragstart', function (e) {
            if (!document.body.classList.contains('dash-editing')) return;
            var card = e.target.closest('.stat-card');
            if (!card) return;
            e.stopPropagation();   // ne pas declencher le glisser-deposer du bloc parent
            draggedCard = card;
            card.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', card.dataset.card || ''); } catch (err) { /* IE */ }
        });

        statGrid.addEventListener('dragover', function (e) {
            if (!draggedCard) return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = 'move';
            var ref = cardAfter(e.clientX, e.clientY);
            if (ref == null) { statGrid.appendChild(draggedCard); }
            else if (ref !== draggedCard) { statGrid.insertBefore(draggedCard, ref); }
        });

        statGrid.addEventListener('drop', function (e) {
            if (draggedCard) { e.preventDefault(); e.stopPropagation(); }
        });

        statGrid.addEventListener('dragend', function (e) {
            if (!draggedCard) return;
            e.stopPropagation();
            draggedCard.classList.remove('dragging');
            draggedCard = null;
            persist();
        });

        // En mode edition, le clic sur une vignette sert au deplacement (pas a la
        // navigation) : on neutralise le lien.
        statGrid.addEventListener('click', function (e) {
            if (document.body.classList.contains('dash-editing') && e.target.closest('.stat-card')) {
                e.preventDefault();
            }
        });
    }

    // ---- Bascule du mode edition ----
    function setEditing(on) {
        document.body.classList.toggle('dash-editing', on);
        customizeBtn.classList.toggle('d-none', on);
        if (editControls) editControls.classList.toggle('d-none', !on);
        if (tray) tray.classList.toggle('d-none', !on);
        setDraggable(on);
        setCardsDraggable(on);
        if (on) { refreshToggleIcons(); refreshTrayEmpty(); }
    }

    customizeBtn.addEventListener('click', function () { setEditing(true); });
    if (doneBtn) doneBtn.addEventListener('click', function () { setEditing(false); });

    if (resetBtn) resetBtn.addEventListener('click', function () {
        if (!window.confirm('Rétablir la disposition par défaut du tableau de bord ?')) return;
        post({ reset: true }).then(function () { window.location.reload(); });
    });
})();
