(function () {
    var MAX_DIMENSION = 1600;
    var JPEG_QUALITY = 0.7;

    function compressFile(file) {
        return new Promise(function (resolve) {
            if (!file.type || !file.type.startsWith('image/')) {
                resolve(file);
                return;
            }
            var img = new Image();
            var reader = new FileReader();
            reader.onload = function (e) {
                img.onload = function () {
                    var ratio = Math.min(1, MAX_DIMENSION / Math.max(img.width, img.height));
                    var canvas = document.createElement('canvas');
                    canvas.width = Math.round(img.width * ratio);
                    canvas.height = Math.round(img.height * ratio);
                    var ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    canvas.toBlob(function (blob) {
                        if (!blob) {
                            resolve(file);
                            return;
                        }
                        var newName = file.name.replace(/\.[^.]+$/, '') + '.jpg';
                        resolve(new File([blob], newName, {type: 'image/jpeg'}));
                    }, 'image/jpeg', JPEG_QUALITY);
                };
                img.onerror = function () {
                    resolve(file);
                };
                img.src = e.target.result;
            };
            reader.onerror = function () {
                resolve(file);
            };
            reader.readAsDataURL(file);
        });
    }

    function handleChange(input) {
        var files = Array.prototype.slice.call(input.files || []);
        if (files.length === 0) return;

        Promise.all(files.map(compressFile)).then(function (compressed) {
            if (typeof DataTransfer === 'undefined') return;
            var dataTransfer = new DataTransfer();
            compressed.forEach(function (file) {
                dataTransfer.items.add(file);
            });
            input.files = dataTransfer.files;
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.body.addEventListener('change', function (event) {
            if (event.target.classList && event.target.classList.contains('js-photo-compress')) {
                handleChange(event.target);
            }
        });
    });
})();
