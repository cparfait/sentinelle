/* Autocompletion « responsable » depuis l'Active Directory.
 *
 * S'attache a tout <input data-ad-search> : au fur et a mesure de la frappe,
 * interroge /api/directory/search et propose les personnes trouvees (nom + mail).
 * Choisir une proposition remplit le champ nom ET le champ email associe
 * (data-ad-email="<name de l'input email>"), pour eviter les erreurs de saisie.
 *
 * La saisie manuelle reste toujours possible : si l'annuaire est indisponible
 * ou ne renvoie rien, le champ se comporte comme un input texte normal.
 */
(function () {
    'use strict';

    function debounce(fn, ms) {
        var t;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    function attach(input) {
        var form = input.closest('form');
        var emailName = input.getAttribute('data-ad-email');
        var emailInput = emailName && form ? form.querySelector('[name="' + emailName + '"]') : null;

        // Conteneur positionne pour ancrer la liste de suggestions.
        var host = input.parentElement;
        if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
        var box = document.createElement('div');
        box.className = 'ad-suggest d-none';
        box.setAttribute('role', 'listbox');
        host.appendChild(box);

        var items = [];   // resultats courants
        var active = -1;  // index survole/selectionne au clavier

        function place() {
            box.style.left = input.offsetLeft + 'px';
            box.style.top = (input.offsetTop + input.offsetHeight) + 'px';
            box.style.width = input.offsetWidth + 'px';
        }
        function hide() { box.classList.add('d-none'); box.innerHTML = ''; items = []; active = -1; }
        function esc(s) {
            return (s || '').replace(/[&<>"]/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
            });
        }

        function choose(it) {
            input.value = it.display_name || it.username || it.email || '';
            if (emailInput && it.email) emailInput.value = it.email;
            hide();
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        // Message informatif (non cliquable) : annuaire indisponible / aucun
        // resultat. Evite l'impression que « rien ne se passe » quand on tape.
        function note(msg) {
            items = []; active = -1;
            box.innerHTML = '<div class="ad-suggest-note">' + esc(msg) + '</div>';
            place();
            box.classList.remove('d-none');
        }

        function render() {
            if (!items.length) { hide(); return; }
            box.innerHTML = items.map(function (it, i) {
                var mail = it.email ? '<span class="ad-mail">' + esc(it.email) + '</span>' : '<span class="ad-mail text-muted">— pas d\'email —</span>';
                var login = it.username ? '<small class="ad-login">' + esc(it.username) + '</small>' : '';
                return '<button type="button" class="ad-suggest-item' + (i === active ? ' active' : '') +
                    '" data-i="' + i + '"><span class="ad-name">' + esc(it.display_name || it.username) +
                    '</span>' + mail + login + '</button>';
            }).join('');
            place();
            box.classList.remove('d-none');
        }

        var run = debounce(function () {
            var q = input.value.trim();
            if (q.length < 2) { hide(); return; }
            fetch('/api/directory/search?q=' + encodeURIComponent(q), {
                headers: { 'Accept': 'application/json' }, credentials: 'same-origin'
            }).then(function (r) { return r.ok ? r.json() : null; })
              .then(function (data) {
                  if (!data) { hide(); return; }
                  // Si l'utilisateur a continue a taper, la valeur peut avoir change.
                  if (input.value.trim().length < 2) { hide(); return; }
                  if (!data.available) {
                      note("Recherche annuaire indisponible — saisie manuelle possible.");
                      return;
                  }
                  items = data.results || [];
                  active = -1;
                  if (!items.length) { note('Aucun résultat dans l\'annuaire.'); return; }
                  render();
              }).catch(function () { hide(); });
        }, 250);

        input.setAttribute('autocomplete', 'off');
        input.addEventListener('input', run);
        input.addEventListener('focus', function () { if (items.length) render(); });

        input.addEventListener('keydown', function (e) {
            if (box.classList.contains('d-none') || !items.length) return;
            if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, items.length - 1); render(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
            else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); choose(items[active]); }
            else if (e.key === 'Escape') { hide(); }
        });

        box.addEventListener('mousedown', function (e) {
            // mousedown (pas click) pour agir avant le blur du champ.
            var btn = e.target.closest('.ad-suggest-item');
            if (!btn) return;
            e.preventDefault();
            var i = parseInt(btn.getAttribute('data-i'), 10);
            if (items[i]) choose(items[i]);
        });

        input.addEventListener('blur', function () { setTimeout(hide, 120); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        Array.prototype.forEach.call(document.querySelectorAll('input[data-ad-search]'), attach);
    });
})();
