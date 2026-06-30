/* Pre-remplissage d'un formulaire depuis une lecture en direct (certificat TLS
 * ou RDAP de domaine). Factorise le script jusqu'ici duplique entre les fiches
 * certificat et domaine.
 *
 * opts : { btnId, msgId, inputId, url, secondField, loadingText, successPrefix }
 *  - secondField : nom du 2e champ a pre-remplir ('issuer' ou 'registrar') ;
 *    la cle correspondante est lue dans la reponse JSON.
 */
function initLookupFill(opts) {
    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.getElementById(opts.btnId);
        if (!btn) return;
        btn.addEventListener('click', function () {
            var domain = document.getElementById(opts.inputId).value.trim();
            var msg = document.getElementById(opts.msgId);
            if (!domain) {
                msg.className = 'd-block mt-1 text-danger';
                msg.textContent = "Renseignez d'abord le domaine.";
                return;
            }
            msg.className = 'd-block mt-1 text-muted';
            msg.textContent = opts.loadingText;
            btn.disabled = true;
            var sep = opts.url.indexOf('?') >= 0 ? '&' : '?';
            fetch(opts.url + sep + 'domain=' + encodeURIComponent(domain))
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d.ok) {
                        if (d.expiry_date) {
                            var exp = document.querySelector('input[name=expiry_date]');
                            if (exp) exp.value = d.expiry_date;
                        }
                        var sec = document.querySelector('input[name=' + opts.secondField + ']');
                        if (sec && d[opts.secondField] && !sec.value) sec.value = d[opts.secondField];
                        msg.className = 'd-block mt-1 text-success';
                        msg.textContent = opts.successPrefix + ' ' + (d.expiry_date || '?')
                            + (d[opts.secondField] ? ' (' + d[opts.secondField] + ')' : '');
                    } else {
                        msg.className = 'd-block mt-1 text-danger';
                        msg.textContent = 'Échec : ' + d.error;
                    }
                })
                .catch(function (e) {
                    msg.className = 'd-block mt-1 text-danger';
                    msg.textContent = 'Erreur : ' + e;
                })
                .finally(function () { btn.disabled = false; });
        });
    });
}
