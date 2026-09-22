// Onglets de fiche : l'ancre de l'URL dit lequel est ouvert.
//
// Sans cela, un lien vers une fiche ramene toujours au premier onglet, et
// « regarde les pieces jointes de ce marche » oblige a expliquer ou cliquer.
// Avec l'ancre, l'adresse se colle dans un mail et ouvre le bon volet.
//
// L'ancre sert AUSSI de memoire au rechargement : deposer une piece jointe
// renvoie sur la fiche, et sans ancre on retombait sur le detail, sans voir le
// fichier qu'on venait d'ajouter.
//
// Mais un formulaire perd l'ancre : il envoie son action (sans ancre), le
// serveur redirige vers la fiche (sans ancre non plus), et l'on retombe sur le
// premier onglet. Meme chose en passant par la page « Modifier » : Annuler ou
// Enregistrer ramenait au premier onglet, apres qu'on avait ouvert le
// cinquieme. D'ou le second role de ce script : FAIRE VOYAGER l'ancre.
//
//   - sur une fiche, chaque formulaire envoye et le bouton Modifier emportent
//     l'onglet ouvert dans l'ancre de leur adresse ;
//   - sur un formulaire arrive avec une ancre, Annuler et l'envoi la rendent a
//     la fiche.
//
// Le serveur n'y touche pas : un navigateur qui suit une redirection sans
// ancre conserve celle de l'adresse demandee (RFC 7231, § 7.1.2). L'ancre
// passe donc d'elle-meme de « /logiciels/3/flux/ajouter#liaisons » a
// « /logiciels/3#liaisons », sans qu'aucune route n'ait a la connaitre.
(function () {
    var ancre = (location.hash || '').replace(/^#(vol-)?/, '');

    function avecAncre(url, cible) {
        return url.replace(/#.*$/, '') + '#' + cible;
    }

    // L'attribut, et non form.action : un champ nomme « action » (il y en a
    // dans Preferences) prend la place de la propriete et renvoie l'element.
    function emporter(form, cible) {
        var action = form.getAttribute('action') || location.pathname + location.search;
        form.setAttribute('action', avecAncre(action, cible));
    }

    var barre = document.querySelector('[data-onglets]');

    // ── Un formulaire (pas d'onglets) arrive avec une ancre : on la rend. ──
    if (!barre) {
        if (!ancre) return;
        document.querySelectorAll('a.js-retour').forEach(function (lien) {
            lien.href = avecAncre(lien.getAttribute('href'), ancre);
        });
        var principal = document.getElementById('form-principal');
        if (principal) {
            principal.addEventListener('submit', function () {
                emporter(principal, ancre);
            });
        }
        return;
    }

    // ── Une fiche a onglets. ──
    if (!window.bootstrap) return;

    function ouvrir(cible) {
        var bouton = barre.querySelector('[data-bs-target="#vol-' + cible + '"]');
        if (bouton) bootstrap.Tab.getOrCreateInstance(bouton).show();
    }

    function courant() {
        var actif = barre.querySelector('.nav-link.active');
        return actif ? (actif.getAttribute('data-bs-target') || '').replace('#vol-', '') : '';
    }

    // #documents dans l'URL -> l'onglet « documents ». On accepte aussi la
    // forme complete #vol-documents, celle que Bootstrap manipule.
    if (ancre) ouvrir(ancre);
    // ... et de meme quand l'ancre change sans rechargement (lien interne,
    // adresse retouchee a la main).
    window.addEventListener('hashchange', function () {
        var cible = (location.hash || '').replace(/^#(vol-)?/, '');
        if (cible) ouvrir(cible);
    });

    barre.addEventListener('shown.bs.tab', function (e) {
        var cible = (e.target.getAttribute('data-bs-target') || '').replace('#vol-', '');
        if (!cible) return;
        // replaceState et non l'ecriture directe de location.hash : celle-ci
        // empile une entree d'historique par clic, et le bouton Retour du
        // navigateur ne ramenait plus a la page precedente mais a l'onglet
        // precedent — dix fois de suite.
        history.replaceState(null, '', '#' + cible);
    });

    // Tout formulaire envoye depuis la fiche emporte l'onglet ouvert : ajout
    // d'un flux, d'un partage, d'un devis, depot ou suppression d'une piece...
    // L'ecoute se fait sur le document (phase de capture) pour attraper aussi
    // les formulaires que le premier onglet n'affiche pas encore.
    document.addEventListener('submit', function (e) {
        var form = e.target;
        var cible = courant();
        if (!form || !cible || form.hasAttribute('data-sans-onglet')) return;
        emporter(form, cible);
    }, true);

    // Le bouton Modifier emporte l'onglet, que la page de modification rendra.
    document.querySelectorAll('a.js-modifier').forEach(function (lien) {
        lien.addEventListener('click', function () {
            var cible = courant();
            if (cible) lien.href = avecAncre(lien.getAttribute('href'), cible);
        });
    });
})();
