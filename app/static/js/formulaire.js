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
            // [data-sans-recherche] : les puces seules, sans champ ni menu --
            // quand autre chose alimente la liste (les modales de choix des
            // elements couverts d'un marche).
            var sansRecherche = select.dataset.sansRecherche !== undefined;
            if (!sansRecherche) {
                boite.appendChild(champ);
                boite.appendChild(menu);
            }
            select.insertAdjacentElement('afterend', boite);

            function options() { return Array.prototype.slice.call(select.options); }
            // Le groupe d'une option (<optgroup label>) : la famille de l'élément,
            // quand la liste en mêle plusieurs (logiciels et matériel couverts).
            function groupe(o) { return o.parentElement && o.parentElement.tagName === 'OPTGROUP' ? o.parentElement.label : ''; }
            // Le sprite Lucide de la page, pour dessiner l'icône d'un groupe
            // (<optgroup data-icone>) : la même que partout, même version.
            var sprite = (function () {
                var u = document.querySelector('use[href*="lucide.svg"]');
                return u ? u.getAttribute('href').split('#')[0] : '';
            })();
            function libelle(cible, o) {
                cible.textContent = '';
                var g = o.parentElement && o.parentElement.tagName === 'OPTGROUP' ? o.parentElement : null;
                // L'icone de l'option (le type d'un materiel) prime sur celle du groupe.
                var icone = o.dataset.icone || (g && g.dataset.icone);
                if (icone && sprite) {
                    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.setAttribute('class', 'lucide puce-icone');
                    svg.setAttribute('width', '14');
                    svg.setAttribute('height', '14');
                    svg.setAttribute('aria-hidden', 'true');
                    var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
                    use.setAttribute('href', sprite + '#' + icone);
                    svg.appendChild(use);
                    cible.appendChild(svg);
                    cible.title = o.title || (g ? g.label : '');
                } else if (g) {
                    var tag = document.createElement('span');
                    tag.className = 'puce-groupe';
                    tag.textContent = g.label;
                    cible.appendChild(tag);
                }
                cible.appendChild(document.createTextNode(o.text));
            }

            function rendreListe() {
                liste.innerHTML = '';
                options().filter(function (o) { return o.selected; }).forEach(function (o) {
                    var puce = document.createElement('span');
                    puce.className = 'puce';
                    puce.innerHTML = '<span></span><button type="button" aria-label="Retirer">&times;</button>';
                    libelle(puce.firstChild, o);
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
                    libelle(b, o);
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

    // ---- Montants : affichés et saisis à la française ----
    // Un champ [data-montant] montre « 9 999 999,99 » (espaces insécables,
    // virgule, deux décimales) ; on y tape ce qu'on veut — « 18500 », « 18 500,5 »,
    // « 18500.50 » — et il se remet en forme en le quittant. Le serveur lit la
    // même chose (parse_float).
    function formaterMontant(valeur) {
        var brut = String(valeur || '').replace(/[\s\u00a0\u202f€]/g, '');
        if (brut.indexOf(',') !== -1) brut = brut.replace(/\./g, '').replace(',', '.');
        if (brut === '') return '';
        var n = Number(brut);
        if (!isFinite(n)) return valeur;
        return n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function initMontants(form) {
        form.querySelectorAll('input[data-montant]').forEach(function (champ) {
            champ.value = formaterMontant(champ.value);
            champ.addEventListener('blur', function () { champ.value = formaterMontant(champ.value); });
        });
    }

    // ---- Accord du mot qui suit un nombre : « 1 an », « 2 ans », « 0 jour » ----
    // Le champ porte ses deux formes dans data-accord="an|ans" ; l'élément qui
    // le suit prend la bonne. En français, le pluriel commence à deux ; un
    // champ vide garde le pluriel, qui se lit comme l'unité du champ.
    function initAccords(form) {
        form.querySelectorAll('input[data-accord]').forEach(function (champ) {
            var formes = champ.getAttribute('data-accord').split('|');
            var mot = champ.nextElementSibling;
            if (!mot || formes.length !== 2) return;
            function accorder() {
                var n = Math.abs(Number(champ.value));
                mot.textContent = (champ.value === '' || !isFinite(n) || n >= 2) ? formes[1] : formes[0];
            }
            champ.addEventListener('input', accorder);
            accorder();
        });
    }

    // ---- Modale de choix : une famille d'un select à puces, à cocher ----
    // [data-choix-select] désigne le select, [data-choix-groupe] l'<optgroup>
    // dont on propose les options pas encore choisies ; « Ajouter » les coche
    // dans le select, dont les puces suivent.
    function initModalesChoix(racine) {
        (racine || document).querySelectorAll('[data-choix-select]').forEach(function (modal) {
            var select = document.getElementById(modal.getAttribute('data-choix-select'));
            var groupe = modal.getAttribute('data-choix-groupe');
            var liste = modal.querySelector('[data-choix-liste]');
            var recherche = modal.querySelector('[data-choix-recherche]');
            if (!select || !liste) return;

            function candidats() {
                return Array.prototype.slice.call(select.options).filter(function (o) {
                    return !o.selected && o.value !== '' && o.parentElement && o.parentElement.label === groupe;
                });
            }
            function rendre() {
                var q = (recherche ? recherche.value : '').trim().toLowerCase();
                var coches = {};
                liste.querySelectorAll('input:checked').forEach(function (c) { coches[c.value] = true; });
                liste.innerHTML = '';
                var lignes = candidats().filter(function (o) { return !q || o.text.toLowerCase().indexOf(q) !== -1; });
                if (!lignes.length) {
                    var rien = document.createElement('div');
                    rien.className = 'text-muted small py-2';
                    rien.textContent = q ? 'Aucun résultat' : 'Tout est déjà rattaché';
                    liste.appendChild(rien);
                    return;
                }
                lignes.forEach(function (o, i) {
                    var id = modal.id + '-' + i;
                    var ligne = document.createElement('label');
                    ligne.className = 'choix-ligne';
                    ligne.setAttribute('for', id);
                    var case_ = document.createElement('input');
                    case_.type = 'checkbox';
                    case_.className = 'form-check-input';
                    case_.id = id;
                    case_.value = o.value;
                    case_.checked = !!coches[o.value];
                    ligne.appendChild(case_);
                    ligne.appendChild(document.createTextNode(o.text));
                    liste.appendChild(ligne);
                });
            }
            modal.addEventListener('show.bs.modal', function () {
                if (recherche) recherche.value = '';
                rendre();
            });
            modal.addEventListener('shown.bs.modal', function () { if (recherche) recherche.focus(); });
            if (recherche) recherche.addEventListener('input', rendre);
            var valider = modal.querySelector('[data-choix-valider]');
            if (valider) valider.addEventListener('click', function () {
                var choisis = {};
                liste.querySelectorAll('input:checked').forEach(function (c) { choisis[c.value] = true; });
                Array.prototype.forEach.call(select.options, function (o) { if (choisis[o.value]) o.selected = true; });
                select.dispatchEvent(new Event('change', { bubbles: true }));
                var inst = window.bootstrap && bootstrap.Modal.getInstance(modal);
                if (inst) inst.hide();
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('form-principal');
        if (!form) return;
        initSommaire(form);
        initAide(form);
        initPuces(form);
        initMontants(form);
        initAccords(form);
        initModalesChoix();
    });

    // Un formulaire chargé après coup (modale-formulaire.js) s'initialise de
    // la même façon : aide repliée, puces, modales de choix — sans sommaire.
    window.Formulaire = {
        init: function (form, racine) {
            initAide(form);
            initPuces(form);
            initMontants(form);
            initAccords(form);
            initModalesChoix(racine || form);
        }
    };
})();
