(function () {
    function debounce(fn, delay) {
        var timer = null;
        return function () {
            clearTimeout(timer);
            var args = arguments;
            timer = setTimeout(function () { fn.apply(null, args); }, delay);
        };
    }

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('visit-form');
        if (!form) return;
        var key = form.dataset.draftKey;

        function serialize() {
            var data = {};
            form.querySelectorAll('input, select, textarea').forEach(function (el) {
                if (!el.name || el.type === 'file' || el.name === 'csrfmiddlewaretoken') return;
                if (el.type === 'checkbox') {
                    if (!data[el.name]) data[el.name] = [];
                    if (el.checked) data[el.name].push(el.value || 'on');
                } else if (el.type === 'radio') {
                    if (el.checked) data[el.name] = el.value;
                } else {
                    data[el.name] = el.value;
                }
            });
            return data;
        }

        function restore() {
            var raw;
            try {
                raw = localStorage.getItem(key);
            } catch (e) {
                return;
            }
            if (!raw) return;

            var data;
            try {
                data = JSON.parse(raw);
            } catch (e) {
                return;
            }

            Object.keys(data).forEach(function (name) {
                var value = data[name];
                var elements = form.querySelectorAll('[name="' + name.replace(/"/g, '\\"') + '"]');
                elements.forEach(function (el) {
                    if (el.type === 'file') return;
                    if (el.type === 'checkbox') {
                        var values = Array.isArray(value) ? value : [value];
                        el.checked = values.indexOf(el.value) !== -1 || (el.value === '' && values.indexOf('on') !== -1);
                    } else if (el.type === 'radio') {
                        el.checked = el.value === value;
                    } else {
                        el.value = value;
                    }
                });
            });
        }

        var save = debounce(function () {
            try {
                localStorage.setItem(key, JSON.stringify(serialize()));
            } catch (e) {
                // Stockage indisponible (navigation privée, quota dépassé) : pas bloquant.
            }
        }, 500);

        var params = new URLSearchParams(window.location.search);
        if (params.has('saved')) {
            try { localStorage.removeItem(key); } catch (e) {}
            params.delete('saved');
            var query = params.toString();
            history.replaceState(null, '', window.location.pathname + (query ? '?' + query : '') + window.location.hash);
        } else {
            restore();
        }
        form.addEventListener('input', save);
        form.addEventListener('change', save);

        form.addEventListener('submit', function () {
            try { localStorage.setItem(key, JSON.stringify(serialize())); } catch (e) {}
        });
    });
})();
