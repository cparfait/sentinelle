// Onglets de fiche : l'ancre de l'URL dit lequel est ouvert.
//
// Sans cela, un lien vers une fiche ramene toujours au premier onglet, et
// « regarde les pieces jointes de ce marche » oblige a expliquer ou cliquer.
// Avec l'ancre, l'adresse se colle dans un mail et ouvre le bon volet.
//
// L'ancre sert AUSSI de memoire au rechargement : deposer une piece jointe
// renvoie sur la fiche, et sans ancre on retombait sur le detail, sans voir le
// fichier qu'on venait d'ajouter.
(function () {
    var barre = document.querySelector('[data-onglets]');
    if (!barre || !window.bootstrap) return;

    function ouvrir(cible) {
        var bouton = barre.querySelector('[data-bs-target="#vol-' + cible + '"]');
        if (bouton) bootstrap.Tab.getOrCreateInstance(bouton).show();
    }

    // #documents dans l'URL -> l'onglet « documents ». On accepte aussi la
    // forme complete #vol-documents, celle que Bootstrap manipule.
    var ancre = (location.hash || '').replace(/^#(vol-)?/, '');
    if (ancre) ouvrir(ancre);

    barre.addEventListener('shown.bs.tab', function (e) {
        var cible = (e.target.getAttribute('data-bs-target') || '').replace('#vol-', '');
        if (!cible) return;
        // replaceState et non l'ecriture directe de location.hash : celle-ci
        // empile une entree d'historique par clic, et le bouton Retour du
        // navigateur ne ramenait plus a la page precedente mais a l'onglet
        // precedent — dix fois de suite.
        history.replaceState(null, '', '#' + cible);
    });
})();
