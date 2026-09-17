/* Le gabarit de formulaire (voir _formulaire.html) : sommaire des rubriques,
   aide repliée derrière un « ? », puces pour les listes à choix multiples. */
(function () {
    'use strict';

    // ---- Sommaire : une entrée par rubrique, qui suit le défilement ----
    function initSommaire(form) {
        var nav = document.querySelector('.form-sommaire');
        var titres = form.querySelectorAll('.form-section-titre');
        if (!nav || !titres.length) { if (nav) nav.remove(); return; }
        var liens = [];
        titres.forEach(function (t, i) {
            var section = t.closest('.form-section');
            if (!section) return;
            if (!section.id) section.id = 'rubrique-' + (i + 1);
            var a = document.createElement('a');
            a.href = '#' + section.id;
            a.className = 'form-sommaire-lien';
            a.innerHTML = '<span class="form-sommaire-n">' + (i + 1) + '</span><span>' + t.textContent.trim() + '</span>';
            a.addEventListener('click', function (e) {
                e.preventDefault();
                section.scrollIntoView({ behavior: 'smooth', block: 'start' });
                history.replaceState(null, '', '#' + section.id);
            });
            nav.appendChild(a);
            liens.push({ a: a, section: section });
        });
        // Rubrique courante : la première visible dans le tiers haut de l'écran.
        function actualiser() {
            var courant = liens[0];
            liens.forEach(function (l) {
                if (l.section.getBoundingClientRect().top <= 160) courant = l;
            });
            liens.forEach(function (l) { l.a.classList.toggle('active', l === courant); });
        }
        window.addEventListener('scroll', actualiser, { passive: true });
        actualiser();
        // Une rubrique masquée (natures d'équipement) sort du sommaire.
        var obs = new MutationObserver(function () {
            liens.forEach(function (l) {
                l.a.style.display = (l.section.offsetParent === null) ? 'none' : '';
            });
        });
        liens.forEach(function (l) { obs.observe(l.section, { attributes: true, attributeFilter: ['style', 'class', 'hidden'] }); });
        liens.forEach(function (l) { l.a.style.display = (l.section.offsetParent === null) ? 'none' : ''; });
    }

    // ---- Aide repliée : le texte gris sous un champ passe derrière un « ? » ----
    function initAide(form) {
        form.querySelectorAll('.form-text').forEach(function (aide) {
            if (aide.closest('.form-section-aide') || aide.dataset.visible !== undefined) return;
            if (aide.textContent.trim().length < 40) return;  // une mention courte reste en place
            var champ = aide.parentElement;
            var label = champ ? champ.querySelector('.form-label, label') : null;
            if (!label) return;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'help-toggle';
            btn.setAttribute('aria-expanded', 'false');
            btn.setAttribute('aria-label', 'Aide');
            btn.title = aide.textContent.trim();
            btn.textContent = '?';
            aide.classList.add('form-text--repliee');
            btn.addEventListener('click', function () {
                var ouvert = aide.classList.toggle('est-ouverte');
                btn.setAttribute('aria-expanded', ouvert ? 'true' : 'false');
            });
            label.appendChild(btn);
        });
    }

    // ---- Puces : une liste à choix multiples devient des puces + une recherche ----
    function initPuces(form) {
        form.querySelectorAll('select[multiple]').forEach(function (select) {
            if (select.dataset.sansPuces !== undefined) return;
            select.classList.add('puces-source');
            var boite = document.createElement('div');
            boite.className = 'puces';
            var liste = document.createElement('div');
            liste.className = 'puces-liste';
            var champ = document.createElement('input');
            champ.type = 'search';
            champ.className = 'puces-champ';
            champ.placeholder = 'Ajouter…';
            champ.setAttribute('aria-label', 'Rechercher un élément à ajouter');
            champ.autocomplete = 'off';
            var menu = document.createElement('div');
            menu.className = 'puces-menu';
            menu.hidden = true;
            boite.appendChild(liste);
            boite.appendChild(champ);
            boite.appendChild(menu);
            select.insertAdjacentElement('afterend', boite);

            function options() { return Array.prototype.slice.call(select.options); }

            function rendreListe() {
                liste.innerHTML = '';
                options().filter(function (o) { return o.selected; }).forEach(function (o) {
                    var puce = document.createElement('span');
                    puce.className = 'puce';
                    puce.innerHTML = '<span></span><button type="button" aria-label="Retirer">&times;</button>';
                    puce.firstChild.textContent = o.text;
                    puce.lastChild.addEventListener('click', function () {
                        o.selected = false;
                        select.dispatchEvent(new Event('change', { bubbles: true }));
                        rendreListe();
                        rendreMenu();
                    });
                    liste.appendChild(puce);
                });
                if (!liste.children.length) {
                    var vide = document.createElement('span');
                    vide.className = 'puces-vide';
                    vide.textContent = 'Aucun';
                    liste.appendChild(vide);
                }
            }

            function rendreMenu() {
                var q = champ.value.trim().toLowerCase();
                menu.innerHTML = '';
                var candidats = options().filter(function (o) {
                    return !o.selected && o.value !== '' && (!q || o.text.toLowerCase().indexOf(q) !== -1);
                }).slice(0, 12);
                if (!candidats.length) {
                    var rien = document.createElement('div');
                    rien.className = 'puces-rien';
                    rien.textContent = q ? 'Aucun résultat' : 'Tout est déjà sélectionné';
                    menu.appendChild(rien);
                    return;
                }
                candidats.forEach(function (o, i) {
                    var b = document.createElement('button');
                    b.type = 'button';
                    b.className = 'puces-option' + (i === 0 ? ' est-cible' : '');
                    b.textContent = o.text;
                    b.addEventListener('mousedown', function (e) { e.preventDefault(); });
                    b.addEventListener('click', function () { choisir(o); });
                    menu.appendChild(b);
                });
            }

            function choisir(o) {
                o.selected = true;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                champ.value = '';
                rendreListe();
                rendreMenu();
                champ.focus();
            }

            champ.addEventListener('focus', function () { rendreMenu(); menu.hidden = false; });
            champ.addEventListener('input', rendreMenu);
            champ.addEventListener('blur', function () { setTimeout(function () { menu.hidden = true; }, 120); });
            champ.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    var cible = menu.querySelector('.puces-option.est-cible');
                    if (cible) cible.click();
                } else if (e.key === 'Escape') {
                    menu.hidden = true;
                    champ.blur();
                } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    var opts = Array.prototype.slice.call(menu.querySelectorAll('.puces-option'));
                    if (!opts.length) return;
                    var idx = opts.findIndex(function (o) { return o.classList.contains('est-cible'); });
                    idx = (idx + (e.key === 'ArrowDown' ? 1 : -1) + opts.length) % opts.length;
                    opts.forEach(function (o, i) { o.classList.toggle('est-cible', i === idx); });
                }
            });
            // Le select peut être rempli ou modifié par ailleurs (ajout rapide) :
            // on suit ses changements plutôt que de les deviner.
            select.addEventListener('change', function () { rendreListe(); if (!menu.hidden) rendreMenu(); });
            new MutationObserver(function () { rendreListe(); if (!menu.hidden) rendreMenu(); })
                .observe(select, { childList: true, subtree: true, attributes: true });
            rendreListe();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('form-principal');
        if (!form) return;
        initSommaire(form);
        initAide(form);
        initPuces(form);
    });
})();
