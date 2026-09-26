/* Ajout rapide (+) : cree une entite liee (fournisseur, contrat, equipement...)
   sans quitter le formulaire courant.

   - Un bouton [data-qa-open="<idModal>"] [data-qa-target="<idSelect>"] ouvre le
     modal et memorise le <select> a completer.
   - Le modal porte data-qa-endpoint (URL de creation rapide) et contient :
       * un champ cache [data-qa-csrf] (jeton CSRF) ;
       * des champs [data-qa-field="<nom>"] (marques [data-qa-required] si obligatoires) ;
       * une zone [data-qa-error] pour les messages ;
       * un bouton [data-qa-save].
   - A la reussite, l'API renvoie {ok:true, id, name, label?} ; on injecte une
     <option> selectionnee dans le select cible. Cf. suppliers/inventory/contracts. */
(function () {
    'use strict';

    function fields(modal) {
        return Array.prototype.slice.call(modal.querySelectorAll('[data-qa-field]'));
    }
    function setError(modal, msg) {
        var box = modal.querySelector('[data-qa-error]');
        if (box) { box.textContent = msg || ''; box.classList.toggle('d-none', !msg); }
    }

    // Ouverture : retenir le select cible sur le modal concerne.
    document.addEventListener('click', function (e) {
        if (!e.target || !e.target.closest) return;
        var opener = e.target.closest('[data-qa-open]');
        if (!opener) return;
        var modal = document.getElementById(opener.getAttribute('data-qa-open'));
        if (!modal) return;
        modal.dataset.qaTarget = opener.getAttribute('data-qa-target') || '';
        setError(modal, '');
    });

    // Enregistrement.
    document.addEventListener('click', function (e) {
        if (!e.target || !e.target.closest) return;
        var btn = e.target.closest('[data-qa-save]');
        if (!btn) return;
        var modal = btn.closest('.modal');
        if (!modal) return;
        setError(modal, '');

        var csrfEl = modal.querySelector('[data-qa-csrf]');
        var token = csrfEl ? csrfEl.value : '';
        var data = new FormData();
        if (token) data.append('csrf_token', token);

        var missing = false;
        fields(modal).forEach(function (inp) {
            var v = (inp.value || '').trim();
            if (inp.hasAttribute('data-qa-required') && !v) missing = true;
            data.append(inp.getAttribute('data-qa-field'), v);
        });
        if (missing) { setError(modal, 'Veuillez remplir les champs obligatoires.'); return; }

        btn.disabled = true;
        fetch(modal.getAttribute('data-qa-endpoint'), {
            method: 'POST', body: data, headers: {'X-CSRFToken': token}
        }).then(function (r) {
            return r.json().catch(function () { return {ok: false}; });
        }).then(function (j) {
            btn.disabled = false;
            if (!j || !j.ok) { setError(modal, (j && j.error) || 'Échec de la création.'); return; }
            var sel = document.getElementById(modal.dataset.qaTarget || '');
            if (sel) {
                var opt = document.createElement('option');
                // Certains selects stockent le nom (ex. revue de droits) plutot que l'id.
                var valField = sel.getAttribute('data-qa-value-field');
                opt.value = (valField && j[valField] != null) ? j[valField] : j.id;
                opt.textContent = j.label || j.name;
                opt.selected = true;
                sel.appendChild(opt);
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
            var inst = window.bootstrap && bootstrap.Modal.getInstance(modal);
            if (inst) inst.hide();
            fields(modal).forEach(function (inp) { inp.value = ''; });
        }).catch(function () {
            btn.disabled = false; setError(modal, 'Erreur réseau.');
        });
    });
})();
