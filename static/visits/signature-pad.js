(function () {
    function initPad(canvas) {
        if (canvas.dataset.initialized) return;
        canvas.dataset.initialized = 'true';

        var ctx = canvas.getContext('2d');
        var targetId = canvas.dataset.target;
        var drawing = false;
        var last = null;

        function pos(evt) {
            var rect = canvas.getBoundingClientRect();
            var point = evt.touches ? evt.touches[0] : evt;
            return {
                x: (point.clientX - rect.left) * (canvas.width / rect.width),
                y: (point.clientY - rect.top) * (canvas.height / rect.height)
            };
        }

        function start(evt) {
            drawing = true;
            last = pos(evt);
            evt.preventDefault();
        }

        function move(evt) {
            if (!drawing) return;
            var p = pos(evt);
            ctx.strokeStyle = '#111827';
            ctx.lineWidth = 2;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(last.x, last.y);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
            last = p;
            evt.preventDefault();
        }

        function end() {
            if (!drawing) return;
            drawing = false;
            var input = document.getElementById(targetId);
            if (input) input.value = canvas.toDataURL('image/png');
        }

        canvas.addEventListener('mousedown', start);
        canvas.addEventListener('mousemove', move);
        canvas.addEventListener('mouseup', end);
        canvas.addEventListener('mouseleave', end);
        canvas.addEventListener('touchstart', start, {passive: false});
        canvas.addEventListener('touchmove', move, {passive: false});
        canvas.addEventListener('touchend', end);
    }

    function clearPad(canvas) {
        var ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        var input = document.getElementById(canvas.dataset.target);
        if (input) input.value = '';
    }

    function initAll() {
        document.querySelectorAll('.js-signature-canvas').forEach(initPad);
    }

    document.addEventListener('DOMContentLoaded', initAll);
    document.body.addEventListener('htmx:afterSwap', initAll);

    document.addEventListener('DOMContentLoaded', function () {
        document.body.addEventListener('click', function (event) {
            var button = event.target.closest('.js-signature-clear');
            if (!button) return;
            var canvas = document.querySelector('canvas[data-target="' + button.dataset.target + '"]');
            if (canvas) clearPad(canvas);
        });
    });
})();
