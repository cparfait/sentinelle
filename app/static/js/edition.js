/* La modification sur place d'une fiche (barre(sur_place=True), _onglets.html).

   Le crayon ne mène plus à la page Modifier : il fait passer la fiche ENTIÈRE
   en modification. <main> prend .en-edition — le CSS rend alors les
   formulaires des onglets (style.css, « Modification sur place ») — et les
   <fieldset data-edition-verrou> se déverrouillent : l'onglet Détails devient
   le formulaire, les services se cochent.

   - Entrer depuis la Synthèse ouvre l'onglet Détails : la Synthèse n'a rien à
     modifier, le formulaire est à côté.
   - Le mode survit aux rechargements (sessionStorage, par fiche) : rattacher un
     serveur ou déposer une pièce renvoie la page, la fiche reste ouverte.
   - Enregistrer le formulaire de l'onglet Détails termine la modification ;
     Annuler (ou le crayon recliqué) aussi, après confirmation s'il y a une
     saisie en cours, qui est alors oubliée. */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var barre = document.querySelector('[data-onglets][data-edition]');
        var bouton = barre && barre.querySelector('.js-edition');
        var main = document.querySelector('main');
        if (!bouton || !main) return;

        var cle = 'edition:' + location.pathname;
        var verrous = document.querySelectorAll('fieldset[data-edition-verrou]');
        var form = document.getElementById('form-principal');
        var etatInitial = null;

        function memoire(valeur) {
            try {
                if (valeur) sessionStorage.setItem(cle, '1');
                else sessionStorage.removeItem(cle);
            } catch (e) { /* stockage indisponible : le mode ne survit pas au rechargement */ }
        }
        function memorise() {
            try { return sessionStorage.getItem(cle) === '1'; } catch (e) { return false; }
        }
        // L'état du formulaire, pour savoir si une saisie serait perdue.
        function etat() {
            if (!form) return '';
            var paires = [];
            new FormData(form).forEach(function (v, k) {
                if (k !== 'csrf_token' && typeof v === 'string') paires.push(k + '=' + v);
            });
            return paires.join('&');
        }
        function saisieEnCours() {
            return etatInitial !== null && etat() !== etatInitial;
        }

        function entrer(depuisClic) {
            main.classList.add('en-edition');
            verrous.forEach(function (f) { f.disabled = false; });
            bouton.setAttribute('aria-pressed', 'true');
            bouton.title = 'Terminer la modification';
            bouton.setAttribute('aria-label', 'Terminer la modification');
            memoire(true);
            etatInitial = etat();
            // Depuis la Synthèse, le formulaire est dans l'onglet voisin.
            var actif = barre.querySelector('.nav-link.active');
            var details = document.getElementById('ong-details');
            if (depuisClic && details && actif && actif.id === 'ong-detail' && window.bootstrap) {
                bootstrap.Tab.getOrCreateInstance(details).show();
            }
        }

        function sortir() {
            if (saisieEnCours() && !confirm('Abandonner les modifications non enregistrées ?')) return;
            memoire(false);
            // Une saisie abandonnée : la page la plus simple à remettre en état
            // est celle que le serveur renvoie.
            if (saisieEnCours()) { location.reload(); return; }
            main.classList.remove('en-edition');
            verrous.forEach(function (f) { f.disabled = true; });
            bouton.setAttribute('aria-pressed', 'false');
            bouton.title = 'Modifier cette fiche';
            bouton.setAttribute('aria-label', 'Modifier cette fiche');
            etatInitial = null;
        }

        bouton.addEventListener('click', function () {
            if (main.classList.contains('en-edition')) sortir();
            else entrer(true);
        });

        if (form && form.closest('fieldset[data-edition-verrou]')) {
            // Enregistrer termine la modification : la fiche revient en lecture.
            form.addEventListener('submit', function () { memoire(false); });
            // Annuler aussi, sur place : pas de navigation vers la même page.
            form.querySelectorAll('a.js-retour').forEach(function (lien) {
                lien.addEventListener('click', function (e) {
                    e.preventDefault();
                    sortir();
                });
            });
        }

        if (memorise()) entrer(false);
    });
})();
