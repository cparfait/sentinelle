/* Un formulaire dans une modale, sans quitter la page.

   Un lien [data-modale-formulaire] ouvre son adresse (?modal=1) dans une
   modale : le serveur rend le formulaire seul (_fragment.html), la modale le
   montre et l'envoie elle-meme. Une reponse REDIRIGEE dit que l'enregistrement
   a reussi : la page se recharge, sur son onglet ; une reponse qui rend le
   formulaire (nom manquant...) remplace le contenu de la modale.

   Les modales que le fragment apporte (choix des elements couverts, ajout
   rapide) sortent dans <body> : une modale ne se dessine pas dans une autre.
   Elles repartent avec la modale, pour ne pas se dedoubler a l'ouverture
   suivante. */
(function () {
    'use strict';

    var conteneur = null;

    function boite() {
        if (conteneur) return conteneur;
        conteneur = document.createElement('div');
        conteneur.className = 'modal fade';
        conteneur.id = 'modaleFormulaire';
        conteneur.tabIndex = -1;
        conteneur.setAttribute('aria-hidden', 'true');
        conteneur.innerHTML = '<div class="modal-dialog modal-xl modal-dialog-scrollable"><div class="modal-content"></div></div>';
        document.body.appendChild(conteneur);
        conteneur.addEventListener('hidden.bs.modal', function () {
            // Les modales importees (choix, ajout rapide) partent avec le formulaire.
            document.querySelectorAll('.modal[data-modale-importee]').forEach(function (m) {
                var inst = window.bootstrap && bootstrap.Modal.getInstance(m);
                if (inst) inst.dispose();
                m.remove();
            });
            conteneur.querySelector('.modal-content').innerHTML = '';
        });
        return conteneur;
    }

    function avecModal(url) {
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'modal=1';
    }

    function installer(html) {
        var contenu = boite().querySelector('.modal-content');
        contenu.innerHTML = html;
        // Les modales du fragment sortent dans <body>.
        contenu.querySelectorAll('.modal').forEach(function (m) {
            m.setAttribute('data-modale-importee', '');
            document.body.appendChild(m);
        });
        var form = contenu.querySelector('form');
        if (!form) return;
        // L'adresse d'envoi, posee sur le formulaire : onglets.js, qui fait
        // voyager l'onglet ouvert, renvoie sinon un formulaire sans action
        // vers la page courante -- qui n'accepte pas de POST.
        if (!form.getAttribute('action')) form.setAttribute('action', adresse);
        if (window.Formulaire) window.Formulaire.init(form, document);
        form.addEventListener('submit', envoyer);
    }

    function erreur(message) {
        var contenu = boite().querySelector('.modal-content');
        var p = contenu.querySelector('.modale-formulaire-erreur');
        if (!p) {
            p = document.createElement('div');
            p.className = 'alert alert-danger m-3 modale-formulaire-erreur';
            contenu.insertBefore(p, contenu.firstChild);
        }
        p.textContent = message;
    }

    var adresse = '';

    function envoyer(e) {
        e.preventDefault();
        var form = e.target;
        var action = form.getAttribute('action') || adresse;
        action = action.replace(/#.*$/, '');
        form.querySelectorAll('button[type=submit]').forEach(function (b) { b.disabled = true; });
        fetch(action, { method: 'POST', body: new FormData(form), credentials: 'same-origin', redirect: 'follow' })
            .then(function (r) {
                if (r.redirected || (r.ok && r.url.indexOf('modal=1') === -1)) {
                    // Enregistre : la page se recharge sur son onglet.
                    location.reload();
                    return null;
                }
                return r.text();
            })
            .then(function (html) { if (html !== null && html !== undefined) installer(html); })
            .catch(function () { erreur('Erreur reseau : le formulaire n\'a pas pu etre envoye.'); });
    }

    function ouvrir(url) {
        // L'adresse d'envoi : celle du fragment, pour que le serveur rende
        // encore un fragment en cas d'erreur.
        adresse = avecModal(url);
        var b = boite();
        var contenu = b.querySelector('.modal-content');
        contenu.innerHTML = '<div class="modal-body text-muted">Chargement…</div>';
        var inst = bootstrap.Modal.getOrCreateInstance(b);
        inst.show();
        fetch(avecModal(url), { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(installer)
            .catch(function () { erreur('Le formulaire n\'a pas pu etre charge.'); });
    }

    document.addEventListener('click', function (e) {
        var lien = e.target.closest('a[data-modale-formulaire]');
        if (!lien || !window.bootstrap) return;
        e.preventDefault();
        ouvrir(lien.getAttribute('href'));
    });
})();
