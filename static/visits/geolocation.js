(function () {
    function fillDevicePosition() {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(function (pos) {
            var lat = document.getElementById('gps_device_lat');
            var lng = document.getElementById('gps_device_lng');
            if (lat) lat.value = pos.coords.latitude;
            if (lng) lng.value = pos.coords.longitude;
        }, function () {}, {enableHighAccuracy: true, timeout: 8000});
    }

    document.addEventListener('DOMContentLoaded', function () {
        fillDevicePosition();

        document.querySelectorAll('.js-capture-gps').forEach(function (button) {
            button.addEventListener('click', function () {
                if (!navigator.geolocation) return;
                navigator.geolocation.getCurrentPosition(function (pos) {
                    var latInput = document.getElementById(button.dataset.lat);
                    var lngInput = document.getElementById(button.dataset.lng);
                    var display = document.getElementById(button.dataset.display);
                    if (latInput) latInput.value = pos.coords.latitude;
                    if (lngInput) lngInput.value = pos.coords.longitude;
                    if (display) display.value = pos.coords.latitude + ', ' + pos.coords.longitude;
                }, function () {
                    alert("Impossible d'obtenir la position.");
                }, {enableHighAccuracy: true, timeout: 8000});
            });
        });
    });
})();
