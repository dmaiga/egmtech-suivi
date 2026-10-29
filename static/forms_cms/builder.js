(function () {
    'use strict';
    var form = document.getElementById('builder-form');
    if (!form) return;
    var schema = JSON.parse(document.getElementById('builder-schema').textContent);
    var types = JSON.parse(document.getElementById('builder-types').textContent);
    if (!Array.isArray(schema.sections)) schema.sections = [];
    var output = document.getElementById('schema-json');
    var sections = document.getElementById('builder-sections');
    var palette = document.getElementById('builder-palette');
    var dialog = document.getElementById('field-dialog');
    var editor = document.getElementById('field-editor-body');
    var editorForm = document.getElementById('field-editor');
    var activeSection = 0;
    var dirty = form.dataset.dirty === 'true';
    var editing = null;
    function element(tag, text, classes) {
        var el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        if (classes) el.className = classes;
        return el;
    }
    function button(label, callback) {
        var el = element('button', label, 'px-2 py-1 text-sm text-indigo-700 hover:underline');
        el.type = 'button'; el.addEventListener('click', callback); return el;
    }
    function allKeys() {
        var keys = [];
        schema.sections.forEach(function (section) { (section.fields || []).forEach(function (field) {
            keys.push(field.key); (field.fields || []).forEach(function (sub) { keys.push(sub.key); });
        }); });
        return keys;
    }
    function uniqueKey(label) {
        var root = (label || 'champ').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40) || 'champ';
        var candidate = root, index = 2, keys = allKeys();
        while (keys.indexOf(candidate) !== -1) candidate = root + '_' + index++;
        return candidate;
    }
    function sync(changed) { output.value = JSON.stringify(schema); if (changed) dirty = true; }
    function newField(type) {
        var field = {key: uniqueKey(types[type]), label: types[type], type: type, required: false};
        if (type === 'choice' || type === 'multichoice') field.options = [];
        if (type === 'photo') { field.min_photos = 1; field.max_photos = 150; }
        if (type === 'repeat') field.fields = [];
        return field;
    }
    function move(list, from, to) {
        if (to < 0 || to >= list.length) return;
        list.splice(to, 0, list.splice(from, 1)[0]); sync(true); render();
    }
    function addField(type, index) {
        if (!schema.sections.length) schema.sections.push({title: 'Nouvelle section', fields: []});
        index = Math.max(0, Math.min(index, schema.sections.length - 1));
        activeSection = index;
        var field = newField(type); schema.sections[index].fields.push(field); sync(true); render();
        openEditor(index, schema.sections[index].fields.length - 1);
    }
    function input(label, value, onChange, type) {
        var wrap = element('label', undefined, 'block text-sm font-semibold text-gray-700');
        wrap.appendChild(document.createTextNode(label));
        var el = type === 'textarea' ? element('textarea') : element('input');
        if (type !== 'textarea') el.type = type || 'text';
        el.value = value === undefined || value === null ? '' : value;
        el.className = 'block w-full mt-1 border rounded-lg px-3 py-2 text-sm';
        el.addEventListener('input', function () { onChange(el.value); });
        wrap.appendChild(el); return wrap;
    }
    function checkbox(label, checked, onChange) {
        var wrap = element('label', undefined, 'flex items-center gap-2 text-sm');
        var el = element('input'); el.type = 'checkbox'; el.checked = !!checked;
        el.addEventListener('change', function () { onChange(el.checked); });
        wrap.append(el, document.createTextNode(label)); return wrap;
    }
    function settingsFields(container, field) {
        container.appendChild(input('Libellé', field.label, function (v) { field.label = v; }));
        container.appendChild(checkbox('Champ obligatoire', field.required, function (v) { field.required = v; }));
        if (field.type === 'choice' || field.type === 'multichoice') container.appendChild(input('Options, une par ligne', (field.options || []).join('\n'), function (v) { field.options = v.split('\n').map(function (s) { return s.trim(); }).filter(Boolean); }, 'textarea'));
        if (field.type === 'photo') {
            container.appendChild(input('Nombre minimum de photos', field.min_photos || 1, function (v) { field.min_photos = Number(v); }, 'number'));
            container.appendChild(input('Nombre maximum de photos', field.max_photos || 150, function (v) { field.max_photos = Number(v); }, 'number'));
        }
    }
    function renderSubfields(field, container) {
        container.replaceChildren();
        (field.fields || []).forEach(function (sub, index) {
            var box = element('div', undefined, 'border rounded-lg p-3 space-y-2');
            var heading = element('div', types[sub.type] || sub.type, 'font-semibold text-sm');
            heading.append(button('↑', function () { if (index > 0) { var a = field.fields[index - 1]; field.fields[index - 1] = sub; field.fields[index] = a; renderSubfields(field, container); } }), button('↓', function () { if (index < field.fields.length - 1) { var a = field.fields[index + 1]; field.fields[index + 1] = sub; field.fields[index] = a; renderSubfields(field, container); } }), button('Supprimer', function () { field.fields.splice(index, 1); renderSubfields(field, container); }));
            box.appendChild(heading); settingsFields(box, sub); container.appendChild(box);
        });
        var choose = element('select', undefined, 'border rounded-lg p-2 text-sm');
        Object.keys(types).filter(function (type) { return type !== 'repeat'; }).forEach(function (type) { var option = element('option', types[type]); option.value = type; choose.appendChild(option); });
        container.append(choose, button('+ Ajouter un sous-champ', function () { var sub = newField(choose.value); var keys = allKeys().concat(field.fields.map(function (f) { return f.key; })); var base = sub.key, n = 2; while (keys.indexOf(sub.key) !== -1) sub.key = base + '_' + n++; field.fields.push(sub); renderSubfields(field, container); }));
    }
    function openEditor(sectionIndex, fieldIndex) {
        var original = schema.sections[sectionIndex].fields[fieldIndex];
        editing = {section: sectionIndex, index: fieldIndex, field: JSON.parse(JSON.stringify(original))};
        editor.replaceChildren();
        editor.appendChild(element('p', types[original.type] || original.type, 'text-sm text-gray-500'));
        settingsFields(editor, editing.field);
        if (original.type === 'repeat') { var sub = element('div', undefined, 'space-y-3'); editor.appendChild(sub); renderSubfields(editing.field, sub); }
        dialog.showModal();
    }
    editorForm.addEventListener('submit', function (event) {
        if (event.submitter && event.submitter.value === 'cancel') return;
        event.preventDefault();
        if (!editing.field.label.trim()) { alert('Renseignez le libellé du champ.'); return; }
        schema.sections[editing.section].fields[editing.index] = editing.field;
        sync(true); render(); dialog.close();
    });
    function render() {
        sections.replaceChildren();
        activeSection = Math.max(0, Math.min(activeSection, schema.sections.length - 1));
        document.getElementById('selected-section').textContent = schema.sections.length ? 'Section choisie : ' + (schema.sections[activeSection].title || 'Sans titre') : 'Une section sera créée si nécessaire.';
        schema.sections.forEach(function (section, si) {
            if (!Array.isArray(section.fields)) section.fields = [];
            var box = element('div', undefined, 'border rounded-lg overflow-hidden');
            var header = element('div', undefined, 'bg-slate-600 text-white p-3 flex gap-2 items-center');
            var title = element('input'); title.type = 'text'; title.value = section.title || ''; title.placeholder = 'Titre de la section'; title.className = 'flex-1 rounded p-2 text-gray-900 text-sm';
            title.addEventListener('input', function () { section.title = title.value; sync(true); });
            header.append(title, button('↑', function () { move(schema.sections, si, si - 1); }), button('↓', function () { move(schema.sections, si, si + 1); }), button('Supprimer', function () { if (confirm('Supprimer cette section et ses champs ?')) { schema.sections.splice(si, 1); sync(true); render(); } }));
            box.appendChild(header);
            var list = element('div', undefined, 'min-h-12 p-2 space-y-1');
            list.addEventListener('dragover', function (e) { e.preventDefault(); });
            list.addEventListener('drop', function (e) { e.preventDefault(); var data; try { data = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (_) { return; } if (data.type && types[data.type]) addField(data.type, si); else if (Number.isInteger(data.section) && Number.isInteger(data.index)) { var moved = schema.sections[data.section].fields.splice(data.index, 1)[0]; if (moved) schema.sections[si].fields.push(moved); sync(true); render(); } });
            section.fields.forEach(function (field, fi) {
                var row = element('div', undefined, 'flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 text-sm'); row.draggable = true;
                row.addEventListener('dragstart', function (e) { e.stopPropagation(); e.dataTransfer.setData('text/plain', JSON.stringify({section: si, index: fi})); });
                row.addEventListener('dragover', function (e) { e.preventDefault(); });
                row.addEventListener('drop', function (e) {
                    var data; try { data = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (_) { return; }
                    if (!Number.isInteger(data.section) || !Number.isInteger(data.index) || !schema.sections[data.section]) return;
                    e.preventDefault(); e.stopPropagation();
                    var moved = schema.sections[data.section].fields.splice(data.index, 1)[0];
                    if (!moved) return;
                    var target = fi - (data.section === si && data.index < fi ? 1 : 0);
                    section.fields.splice(target, 0, moved); sync(true); render();
                });
                var name = element('button', (types[field.type] || field.type) + ' · ' + (field.label || 'Sans libellé') + (field.required ? ' *' : ''), 'flex-1 text-left font-medium text-gray-800'); name.type = 'button'; name.addEventListener('click', function () { activeSection = si; openEditor(si, fi); });
                row.append(name, button('↑', function () { move(section.fields, fi, fi - 1); }), button('↓', function () { move(section.fields, fi, fi + 1); }), button('Modifier', function () { openEditor(si, fi); }), button('Supprimer', function () { if (confirm('Supprimer ce champ ?')) { section.fields.splice(fi, 1); sync(true); render(); } }));
                list.appendChild(row);
            });
            list.appendChild(button('+ Ajouter ici', function () { activeSection = si; render(); palette.scrollIntoView({behavior: 'smooth'}); }));
            box.appendChild(list); sections.appendChild(box);
        });
        sync(false);
    }
    Object.keys(types).forEach(function (type) {
        var tile = button(types[type], function () { addField(type, activeSection); }); tile.className = 'bg-gray-100 hover:bg-indigo-50 rounded-lg p-3 text-left text-sm font-semibold text-gray-800'; tile.draggable = true;
        tile.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/plain', JSON.stringify({type: type})); }); palette.appendChild(tile);
    });
    document.getElementById('add-section').addEventListener('click', function () { schema.sections.push({title: 'Nouvelle section', fields: []}); activeSection = schema.sections.length - 1; sync(true); render(); });
    form.addEventListener('input', function () { dirty = true; });
    form.addEventListener('submit', function () { sync(false); dirty = false; });
    window.addEventListener('beforeunload', function (event) { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
    render();
})();
