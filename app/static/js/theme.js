function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const icon = document.getElementById('theme-icon');
    if (icon) {
        icon.className = next === 'dark' ? 'bi bi-sun' : 'bi bi-moon';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    const icon = document.getElementById('theme-icon');
    if (icon) {
        icon.className = saved === 'dark' ? 'bi bi-sun' : 'bi bi-moon';
    }
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
        bar.className = 'd-flex gap-2 mb-3 flex-wrap';
        FILTERS.forEach(function(f) {
            if (f.key !== 'all' && !counts[f.key]) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm btn-outline-' + f.cls;
            btn.textContent = f.label + (f.key === 'all' ? '' : ' (' + counts[f.key] + ')');
            btn.dataset.filter = f.key;
            btn.addEventListener('click', function() {
                bar.querySelectorAll('button').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                rows.forEach(function(tr) {
                    tr.style.display = (f.key === 'all' || tr.className.indexOf('row-' + f.key) !== -1) ? '' : 'none';
                });
            });
            bar.appendChild(btn);
        });
        // insere la barre juste avant la carte contenant le tableau
        const card = table.closest('.data-card') || table;
        card.parentNode.insertBefore(bar, card);
    });
}
