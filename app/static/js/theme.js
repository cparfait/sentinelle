// La lune en clair, le soleil en sombre : le bouton montre le mode ou l'on
// PEUT aller, comme dans CultuResa.
function applyThemeIcons(theme) {
    const glyphe = theme === 'dark' ? '☀️' : '🌙';
    document.querySelectorAll('.js-theme-icon').forEach(function(icon) {
        icon.textContent = glyphe;
    });
}

function toggleTheme() {
    const html = document.documentElement;
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
    applyThemeIcons(next);
}

/* ---- Menu latéral mobile (off-canvas) ---- */
function openSidebar() {
    document.querySelector('.sidebar')?.classList.add('open');
    document.querySelector('.sidebar-backdrop')?.classList.add('show');
}
function closeSidebar() {
    document.querySelector('.sidebar')?.classList.remove('open');
    document.querySelector('.sidebar-backdrop')?.classList.remove('show');
}
function toggleSidebar() {
    document.querySelector('.sidebar')?.classList.contains('open') ? closeSidebar() : openSidebar();
}

document.addEventListener('DOMContentLoaded', function() {
    // ?theme=dark|light : theme force pour une capture ou un essai, sans etre memorise
    const forced = new URLSearchParams(location.search).get('theme');
    const saved = forced || (function() { try { return localStorage.getItem('theme'); } catch (e) { return null; } })() || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    applyThemeIcons(saved);

    // Fermer le menu mobile après un clic sur un lien de navigation
    document.querySelectorAll('.sidebar-link').forEach(function(link) {
        link.addEventListener('click', closeSidebar);
    });
    // Revenir en mode bureau : réinitialiser l'état mobile
    window.addEventListener('resize', function() {
        if (window.innerWidth > 991) closeSidebar();
    });
    // Permettre Échap pour fermer le menu ; Ctrl K (ou Cmd K) : la recherche.
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeSidebar();
        if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
            const champ = document.getElementById('recherche-globale');
            if (champ) {
                e.preventDefault();
                if (window.innerWidth <= 991) openSidebar();
                champ.focus();
                champ.select();
            }
        }
    });

    // Sections repliables du menu (Administration) : l'etat se memorise, sauf
    // quand la page courante est dedans (alors la section est forcee ouverte).
    document.querySelectorAll('details.sidebar-section--repliable').forEach(function(d) {
        const cle = 'nav-open-' + (d.dataset.section || 'x');
        if (!d.hasAttribute('data-forced-open')) {
            try { if (localStorage.getItem(cle) === '1') d.open = true; } catch (e) {}
        }
        d.addEventListener('toggle', function() {
            try { localStorage.setItem(cle, d.open ? '1' : '0'); } catch (e) {}
        });
    });

    // Auto-fermeture des messages flash de succès/info après 6 s
    document.querySelectorAll('.alert.js-autodismiss').forEach(function(el) {
        if (/alert-(success|info)/.test(el.className)) {
            setTimeout(function() {
                if (window.bootstrap && bootstrap.Alert) {
                    bootstrap.Alert.getOrCreateInstance(el).close();
                } else {
                    el.classList.remove('show');
                }
            }, 6000);
        }
    });

    initStatusFilters();

    // Un lien « #renouveler » (depuis le tableau de bord) ouvre directement la
    // fenetre d'action de la fiche, sans avoir a retrouver le bouton.
    (function () {
        var id = (location.hash || '').slice(1);
        if (!id || !window.bootstrap || !bootstrap.Modal) return;
        var modal = document.getElementById(id);
        if (modal && modal.classList.contains('modal')) {
            bootstrap.Modal.getOrCreateInstance(modal).show();
            history.replaceState(null, '', location.pathname + location.search);
        }
    })();

    // Menu utilisateur (pied de la barre laterale) : se replie quand on clique ailleurs
    document.addEventListener('click', function(e) {
        document.querySelectorAll('details.sidebar-user[open]').forEach(function(d) {
            if (!d.contains(e.target)) d.removeAttribute('open');
        });
    });

    // Filtres persistants
    (function () {
        var STORE_KEY = 'sentinelle_search_' + location.pathname;
        var input = document.querySelector('input[name="q"]');
        if (!input) return;
        var params = new URLSearchParams(location.search);
        if (params.has('q')) {
            try { localStorage.setItem(STORE_KEY, params.get('q')); } catch (e) {}
        } else {
            var saved;
            try { saved = localStorage.getItem(STORE_KEY); } catch (e) {}
            if (saved) { input.value = saved; }
        }
        var form = input.closest('form');
        if (form) {
            form.addEventListener('submit', function () {
                if (!input.value.trim()) {
                    try { localStorage.removeItem(STORE_KEY); } catch (e) {}
                }
            });
        }
    })();
});

// Filtres interactifs par statut sur les tableaux marques .js-filterable
function initStatusFilters() {
    const FILTERS = [
        {key: 'all', label: 'Tous', cls: 'secondary'},
        // Memes mots que app/libelles.py : un vocabulaire, pas un par ecran.
        {key: 'danger', label: 'Critique', cls: 'danger'},
        {key: 'warning', label: 'Urgent', cls: 'warning'},
        {key: 'info', label: 'À prévoir', cls: 'info'},
        {key: 'success', label: 'OK', cls: 'success'},
    ];
    document.querySelectorAll('table.js-filterable').forEach(function(table) {
        const rows = Array.from(table.querySelectorAll('tbody tr')).filter(function(tr) {
            return /\brow-(danger|warning|info|success)\b/.test(tr.className);
        });
        if (rows.length < 2) return;
        const counts = {danger: 0, warning: 0, info: 0, success: 0};
        rows.forEach(function(tr) {
            const m = tr.className.match(/row-(danger|warning|info|success)/);
            if (m) counts[m[1]]++;
        });
        const bar = document.createElement('div');
        bar.className = 'status-filter-bar d-flex gap-2 mb-3 flex-wrap';
        let allBtn = null;
        FILTERS.forEach(function(f) {
            if (f.key !== 'all' && !counts[f.key]) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'status-filter status-filter-' + f.cls;
            btn.innerHTML = '<span class="status-filter-label">' + f.label + '</span>' +
                (f.key === 'all' ? '' : '<span class="status-filter-count">' + counts[f.key] + '</span>');
            btn.dataset.filter = f.key;
            if (f.key === 'all') allBtn = btn;
            btn.addEventListener('click', function() {
                bar.querySelectorAll('button').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                rows.forEach(function(tr) {
                    tr.style.display = (f.key === 'all' || tr.className.indexOf('row-' + f.key) !== -1) ? '' : 'none';
                });
            });
            bar.appendChild(btn);
        });
        // « Tous » actif par defaut (toutes les lignes visibles).
        if (allBtn) allBtn.classList.add('active');
        // Dans la barre d'outils de la liste quand elle existe (_liste.html),
        // sinon juste avant la carte contenant le tableau.
        const slot = document.querySelector('.list-toolbar [data-pills]');
        if (slot) {
            slot.appendChild(bar);
        } else {
            const card = table.closest('.data-card') || table;
            card.parentNode.insertBefore(bar, card);
        }
    });
}
