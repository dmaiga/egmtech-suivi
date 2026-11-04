(function () {
    function toggle(el, visible) {
        if (el) el.classList.toggle('hidden', !visible);
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('visit-form');
        if (!form) return;
        var steps = Array.from(form.querySelectorAll('.js-collapsible-section'));
        var progress = document.getElementById('wizard-progress');
        var label = document.getElementById('wizard-label');
        var quit = document.getElementById('wizard-quit');
        var previous = document.getElementById('wizard-prev');
        var next = document.getElementById('wizard-next');
        var submit = document.getElementById('btn-submit-visit');
        var loading = document.getElementById('wizard-loading');

        // Écran de chargement pendant l'envoi : les photos peuvent être lourdes.
        form.addEventListener('submit', function (event) {
            if (event.defaultPrevented) return;
            toggle(loading, true);
            // Empêche un double envoi, après que le navigateur a lu le bouton cliqué.
            setTimeout(function () {
                form.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = true; });
            }, 0);
        });
        // Retour arrière du navigateur (page restaurée depuis le cache) : retirer le chargement.
        window.addEventListener('pageshow', function () {
            toggle(loading, false);
            form.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = false; });
        });

        if (!steps.length) return;
        var index = Math.max(0, Math.min(parseInt(form.dataset.step, 10) || 0, steps.length - 1));
        var isFirst = index === 0;
        var isLast = index === steps.length - 1;
        document.getElementById('wizard-current-step').value = String(index);
        steps.forEach(function (step, i) { step.hidden = i !== index; });

        // Une seule rangée : [Quitter | Précédent] + [Enregistrer et continuer | Soumettre la visite]
        toggle(quit, isFirst);
        toggle(previous, !isFirst);
        toggle(next, !isLast);
        toggle(submit, isLast);
        previous.value = String(index - 1);
        next.value = String(index + 1);

        quit.addEventListener('click', function () {
            if (window.confirm(quit.dataset.confirm)) {
                window.location.href = quit.dataset.href;
            }
        });

        label.textContent = 'Étape ' + (index + 1) + ' sur ' + steps.length + ' : ' + steps[index].querySelector('h2').textContent.trim();
        progress.classList.remove('hidden');
    });
})();
