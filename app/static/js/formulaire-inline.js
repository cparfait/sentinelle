/* Un formulaire dans une liste, sans quitter la page.

   Un lien [data-formulaire-inline] charge son adresse (?inline=1) : le serveur
   rend le formulaire seul (_fragment.html), et il s'affiche
     - A LA PLACE du bloc [data-cible="#id"] (modification : le marche
       s'efface, le formulaire prend sa place, Annuler le rend) ;
     - EN TETE du conteneur [data-avant="#id"] (creation).
   Le formulaire s'envoie lui-meme. Une reponse REDIRIGEE dit que
   l'enregistrement a reussi : la page se recharge, sur son onglet ; une
   reponse qui rend le formulaire (nom manquant...) le remplace sur place.

   Les modales que le fragment apporte (choix des elements couverts, ajout
   rapide) sortent dans <body> et repartent avec le formulaire. Un seul
   formulaire ouvert a la fois : en ouvrir un ferme le precedent. */
(function () {
    'use strict';

    var ouvert = null;   // { boite, cache, adresse }

    function avecInline(url) {
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'inline=1';
    }

    function fermer() {
        if (!ouvert) return;
        document.querySelectorAll('.modal[data-modale-importee]').forEach(function (m) {
            var inst = window.bootstrap && bootstrap.Modal.getInstance(m);
            if (inst) inst.dispose();
            m.remove();
        });
        ouvert.boite.remove();
        if (ouvert.cache) ouvert.cache.classList.remove('d-none');
        ouvert = null;
    }

    function installer(html) {
        if (!ouvert) return;
        var boite = ouvert.boite;
        boite.innerHTML = html;
        // Les modales du fragment sortent dans <body>.
        boite.querySelectorAll('.modal').forEach(function (m) {
            m.setAttribute('data-modale-importee', '');
            document.body.appendChild(m);
        });
        var form = boite.querySelector('form');
        if (!form) return;
        // L'adresse d'envoi, posee sur le formulaire : onglets.js, qui fait
        // voyager l'onglet ouvert, renvoie sinon un formulaire sans action
        // vers la page courante -- qui n'accepte pas de POST.
        if (!form.getAttribute('action')) form.setAttribute('action', ouvert.adresse);
        if (window.Formulaire) window.Formulaire.init(form, document);
        form.addEventListener('submit', envoyer);
        boite.querySelectorAll('[data-formulaire-fermer]').forEach(function (b) {
            b.addEventListener('click', fermer);
        });
        var premier = form.querySelector('input[type=text], select');
        if (premier) premier.focus();
    }

    function erreur(message) {
        if (!ouvert) return;
        var p = document.createElement('div');
        p.className = 'alert alert-danger py-2 small';
        p.textContent = message;
        ouvert.boite.insertBefore(p, ouvert.boite.firstChild);
    }

    function envoyer(e) {
        e.preventDefault();
        var form = e.target;
        var action = (form.getAttribute('action') || ouvert.adresse).replace(/#.*$/, '');
        form.querySelectorAll('button[type=submit]').forEach(function (b) { b.disabled = true; });
        fetch(action, { method: 'POST', body: new FormData(form), credentials: 'same-origin', redirect: 'follow' })
            .then(function (r) {
                if (r.redirected || (r.ok && r.url.indexOf('inline=1') === -1)) {
                    location.reload();
                    return null;
                }
                return r.text();
            })
            .then(function (html) { if (html !== null && html !== undefined) installer(html); })
            .catch(function () { erreur('Erreur reseau : le formulaire n\'a pas pu etre envoye.'); });
    }

    function ouvrir(lien) {
        fermer();
        var url = lien.getAttribute('href');
        var cible = lien.getAttribute('data-cible') ? document.querySelector(lien.getAttribute('data-cible')) : null;
        var avant = lien.getAttribute('data-avant') ? document.querySelector(lien.getAttribute('data-avant')) : null;
        if (!cible && !avant) { location.href = url; return; }
        var boite = document.createElement('div');
        boite.className = 'formulaire-inline p-3 border-bottom';
        boite.innerHTML = '<div class="text-muted small">Chargement…</div>';
        if (cible) {
            cible.insertAdjacentElement('afterend', boite);
            cible.classList.add('d-none');
        } else {
            avant.insertAdjacentElement('afterbegin', boite);
        }
        ouvert = { boite: boite, cache: cible, adresse: avecInline(url) };
        fetch(avecInline(url), { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(installer)
            .catch(function () { erreur('Le formulaire n\'a pas pu etre charge.'); });
    }

    document.addEventListener('click', function (e) {
        var lien = e.target.closest('a[data-formulaire-inline]');
        if (!lien) return;
        e.preventDefault();
        ouvrir(lien);
    });
})();
