// Affichage conditionnel (« visible_si ») : un bloc n'apparaît que si le champ
// de choix visé a la valeur attendue. Les entrées d'un bloc masqué sont
// désactivées : elles ne sont ni envoyées ni exigées.
(function () {
    function refresh(form) {
        form.querySelectorAll('.js-conditional').forEach(function (block) {
            var source = form.querySelector('[name="' + block.dataset.champ + '"]');
            var visible = !!source && source.value === block.dataset.valeur;
            block.classList.toggle('hidden', !visible);
            block.querySelectorAll('input, select, textarea, button').forEach(function (el) {
                el.disabled = !visible;
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('visit-form');
        if (!form || !form.querySelector('.js-conditional')) return;
        form.addEventListener('change', function () { refresh(form); });
        // Lignes ajoutées par HTMX dans un bloc conditionnel.
        document.body.addEventListener('htmx:afterSwap', function () { refresh(form); });
        refresh(form);
    });
})();
