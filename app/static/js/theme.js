function applyThemeIcons(theme) {
    const cls = theme === 'dark' ? 'bi bi-sun js-theme-icon' : 'bi bi-moon js-theme-icon';
    document.querySelectorAll('.js-theme-icon').forEach(function(icon) {
        icon.className = cls;
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
    const saved = (function() { try { return localStorage.getItem('theme'); } catch (e) { return null; } })() || 'light';
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
    // Permettre Échap pour fermer le menu
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeSidebar();
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
});

// Filtres interactifs par statut sur les tableaux marques .js-filterable
function initStatusFilters() {
    const FILTERS = [
        {key: 'all', label: 'Tous', cls: 'secondary'},
        {key: 'danger', label: 'Critique', cls: 'danger'},
        {key: 'warning', label: 'Attention', cls: 'warning'},
        {key: 'info', label: 'À surveiller', cls: 'info'},
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
        // insere la barre juste avant la carte contenant le tableau
        const card = table.closest('.data-card') || table;
        card.parentNode.insertBefore(bar, card);
    });
}
