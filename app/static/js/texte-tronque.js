/* Un texte coupé par « … » (text-overflow: ellipsis) se lit en entier au
   survol : l'infobulle native reprend le texte de l'élément tronqué.

   Pas d'attribut à poser dans les gabarits : au survol, on remonte depuis
   l'élément pointé jusqu'au premier qui coupe son texte ET déborde
   réellement. Un title déjà écrit dans le gabarit est respecté ; celui posé
   ici (data-title-auto) s'efface quand le texte retient de nouveau, après un
   agrandissement de la fenêtre par exemple. */
(function () {
    'use strict';

    function tronque(el) {
        return el.scrollWidth > el.clientWidth + 1
            && getComputedStyle(el).textOverflow === 'ellipsis';
    }

    document.addEventListener('mouseover', function (e) {
        for (var el = e.target; el && el !== document.body; el = el.parentElement) {
            if (el.nodeType !== 1) continue;
            var auto = el.hasAttribute('data-title-auto');
            if (el.hasAttribute('title') && !auto) return;
            if (tronque(el)) {
                var texte = (el.textContent || '').replace(/\s+/g, ' ').trim();
                if (texte) {
                    el.setAttribute('title', texte);
                    el.setAttribute('data-title-auto', '');
                }
                return;
            }
            if (auto) {
                el.removeAttribute('title');
                el.removeAttribute('data-title-auto');
            }
        }
    });
})();
