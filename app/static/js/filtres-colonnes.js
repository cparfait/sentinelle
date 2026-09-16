// Filtre « à la Excel » par colonne, sur TOUS les tableaux de l'application.
//
// L'inventaire seul en disposait : un entonnoir dans chaque en-tête, qui ouvre
// la liste des valeurs présentes et un champ « contient ». Les onze autres
// listes — comptes, certificats, marchés, logiciels… — et les tableaux des
// fiches obligeaient à lire toutes les lignes, ou à passer par la recherche
// plein texte qui ne sait pas dire « seulement ceux-là ».
//
// Le filtre agit sur les lignes AFFICHÉES, pas sur la base : sur une liste
// paginée, il ne voit que la page ouverte (choisir « Tous » dans le sélecteur
// de lignes pour filtrer l'ensemble). C'est le prix d'un filtre qui marche
// partout sans qu'aucune route ait à le prévoir.
//
// Un tableau s'en dispense avec `data-sans-filtre` — celui dont les lignes sont
// un formulaire, ou qui en compte trop peu pour qu'on ait à les trier.
(function () {
    var MINIMUM_LIGNES = 3;   // en dessous, l'entonnoir encombre plus qu'il ne sert

    function equiper(table) {
        if (!table.tHead || !table.tHead.rows.length || !table.tBodies.length) return;
        var ths = Array.prototype.slice.call(table.tHead.rows[0].cells);
        var filters = {};            // index colonne -> {text:'', values:Set|null}
        var panel = null;

        function rows() {
            return Array.prototype.filter.call(table.tBodies[0].rows, function (r) {
                // La ligne « aucun élément » s'étend sur toute la largeur : elle
                // n'a pas de valeur a filtrer, et la masquer effacerait le seul
                // message que porte un tableau vide.
                return !r.querySelector('td[colspan]');
            });
        }
        function cellText(tr, ci) {
            var c = tr.cells[ci];
            return c ? c.textContent.trim() : '';
        }
        function isActive(f) { return f && (f.text || f.values); }
        function cleanup(ci) { if (filters[ci] && !filters[ci].text && !filters[ci].values) delete filters[ci]; }
        function apply() {
            rows().forEach(function (tr) {
                var show = true;
                for (var ci in filters) {
                    var f = filters[ci];
                    if (!f) continue;
                    var v = cellText(tr, ci);
                    if (f.text && v.toLowerCase().indexOf(f.text.toLowerCase()) === -1) { show = false; break; }
                    if (f.values && !f.values.has(v)) { show = false; break; }
                }
                tr.style.display = show ? '' : 'none';
            });
            ths.forEach(function (th, ci) {
                var b = th.querySelector('.colfiltre-btn');
                if (b) b.classList.toggle('active', isActive(filters[ci]));
            });
        }
        function closePanel() { if (panel) { panel.remove(); panel = null; } }

        function openPanel(ci, btn) {
            closePanel();
            var f = filters[ci] || {text: '', values: null};
            var present = {};
            rows().forEach(function (tr) { present[cellText(tr, ci)] = true; });
            var keys = Object.keys(present).sort(function (a, b) { return a.localeCompare(b, 'fr', {numeric: true}); });
            panel = document.createElement('div');
            panel.className = 'colfiltre-panel';
            panel.dataset.ci = ci;
            var h = '<input type="text" class="form-control form-control-sm mb-2 cf-search" placeholder="Contient...">';
            h += '<div class="cf-list">';
            keys.forEach(function (k) {
                var checked = (!f.values || f.values.has(k)) ? 'checked' : '';
                var lbl = (k === '' ? '(vide)' : k).replace(/&/g, '&amp;').replace(/</g, '&lt;');
                h += '<label class="cf-item d-flex align-items-center gap-2"><input type="checkbox" class="form-check-input mt-0 cf-cb" ' + checked + ' data-v="' + encodeURIComponent(k) + '"><span>' + lbl + '</span></label>';
            });
            h += '</div><div class="d-flex justify-content-between align-items-center mt-2">';
            h += '<button type="button" class="btn btn-sm btn-link p-0 cf-all">Tout</button>';
            h += '<button type="button" class="btn btn-sm btn-link p-0 cf-none">Aucun</button>';
            h += '<button type="button" class="btn btn-sm btn-primary py-0 px-2 cf-ok">OK</button></div>';
            h += '<button type="button" class="btn btn-sm btn-link p-0 mt-1 text-danger cf-clear" style="font-size:.75rem;">Effacer le filtre</button>';
            panel.innerHTML = h;
            document.body.appendChild(panel);
            var r = btn.getBoundingClientRect();
            panel.style.top = (window.scrollY + r.bottom + 4) + 'px';
            panel.style.left = (window.scrollX + Math.min(r.left, document.documentElement.clientWidth - 245)) + 'px';
            panel.addEventListener('click', function (e) { e.stopPropagation(); });

            var search = panel.querySelector('.cf-search');
            search.value = f.text || '';
            // Saisie = filtre « contient » applique en direct aux lignes (et a la liste).
            search.addEventListener('input', function () {
                var q = this.value;
                var ql = q.toLowerCase();
                panel.querySelectorAll('.cf-item').forEach(function (it) {
                    it.style.display = it.textContent.toLowerCase().indexOf(ql) === -1 ? 'none' : '';
                });
                filters[ci] = filters[ci] || {text: '', values: null};
                filters[ci].text = q;
                cleanup(ci);
                apply();
            });
            function visibleCbs() {
                return Array.prototype.filter.call(panel.querySelectorAll('.cf-cb'), function (c) {
                    return c.closest('.cf-item').style.display !== 'none';
                });
            }
            panel.querySelector('.cf-all').addEventListener('click', function () { visibleCbs().forEach(function (c) { c.checked = true; }); });
            panel.querySelector('.cf-none').addEventListener('click', function () { visibleCbs().forEach(function (c) { c.checked = false; }); });
            panel.querySelector('.cf-ok').addEventListener('click', function () {
                var sel = new Set(), all = true;
                panel.querySelectorAll('.cf-cb').forEach(function (c) {
                    if (c.checked) sel.add(decodeURIComponent(c.dataset.v)); else all = false;
                });
                filters[ci] = filters[ci] || {text: '', values: null};
                filters[ci].values = all ? null : sel;
                cleanup(ci);
                apply();
                closePanel();
            });
            panel.querySelector('.cf-clear').addEventListener('click', function () {
                delete filters[ci];
                apply();
                closePanel();
            });
        }

        ths.forEach(function (th, ci) {
            // Un en-tete VIDE est une colonne d'actions (boutons, cases a cocher) :
            // il n'y a rien a y filtrer. Le critere vaut mieux que « la derniere
            // colonne » : certaines listes en portent deux, d'autres aucune.
            var intitule = th.textContent.trim();
            if (!intitule) return;
            // « Actions » nomme la colonne des boutons sur certaines listes :
            // elle ne porte pas de valeur, seulement le crayon et la corbeille.
            if (/^actions?$/i.test(intitule)) return;
            if (th.hasAttribute('data-sans-filtre')) return;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'colfiltre-btn';
            btn.title = 'Filtrer cette colonne';
            btn.setAttribute('aria-label', 'Filtrer cette colonne');
            btn.innerHTML = '<i class="bi bi-funnel-fill"></i>';
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                e.preventDefault();
                var open = panel && panel.dataset.ci == ci;
                closePanel();
                if (!open) openPanel(ci, btn);
            });
            th.appendChild(btn);
        });
        document.addEventListener('click', closePanel);
    }

    document.querySelectorAll('table.table').forEach(function (table) {
        if (table.hasAttribute('data-sans-filtre')) return;
        if (!table.tBodies.length) return;
        var utiles = Array.prototype.filter.call(table.tBodies[0].rows, function (r) {
            return !r.querySelector('td[colspan]');
        });
        if (utiles.length < MINIMUM_LIGNES) return;
        equiper(table);
    });
})();
