(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('visit-form');
        if (!form) return;
        var steps = Array.from(form.querySelectorAll('.js-collapsible-section'));
        var progress = document.getElementById('wizard-progress');
        var nav = document.getElementById('wizard-navigation');
        var label = document.getElementById('wizard-label');
        var previous = document.getElementById('wizard-prev');
        var next = document.getElementById('wizard-next');
        var submit = document.getElementById('btn-submit-visit');
        var index = Math.max(0, Math.min(parseInt(form.dataset.step, 10) || 0, steps.length - 1));
        if (!steps.length) return;
        document.getElementById('wizard-current-step').value = String(index);
        steps.forEach(function (step, i) { step.hidden = i !== index; });
        previous.hidden = index === 0;
        next.hidden = index === steps.length - 1;
        previous.value = String(index - 1);
        next.value = String(index + 1);
        submit.hidden = index !== steps.length - 1;
        label.textContent = 'Étape ' + (index + 1) + ' sur ' + steps.length + ' : ' + steps[index].querySelector('h2').textContent.trim();
        progress.classList.remove('hidden');
        nav.classList.remove('hidden');
    });
})();
