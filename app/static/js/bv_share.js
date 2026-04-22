(function () {
    'use strict';

    var modalEl = null;
    var modal = null;
    var currentType = null;
    var currentId = null;
    var usersQueryToken = 0;
    var searchTimer = null;

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? (meta.getAttribute('content') || '') : '';
    }

    function api(path, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        opts.headers['Accept'] = 'application/json';
        var token = getCsrfToken();
        if (token) {
            opts.headers['X-CSRFToken'] = token;
            opts.headers['X-CSRF-Token'] = token;
        }
        return fetch(path, opts);
    }

    function escapeHtml(s) {
        var div = document.createElement('div');
        div.textContent = s == null ? '' : String(s);
        return div.innerHTML;
    }

    function pathUsers() {
        return '/billeteras-virtuales/api/share/users';
    }

    function pathShares() {
        if (!currentType || !currentId) return null;
        if (currentType === 'carga') return '/billeteras-virtuales/api/share/carga/' + currentId;
        if (currentType === 'caso' || currentType === 'sujeto') return '/sabana-llamadas/api/share/' + currentType + '/' + currentId;
        return null;
    }

    function renderCurrentShares(items) {
        var box = document.getElementById('bv-share-current');
        if (!box) return;
        var arr = Array.isArray(items) ? items : [];
        if (!arr.length) {
            box.innerHTML = '<div class="text-muted small">Sin compartidos.</div>';
            return;
        }
        box.innerHTML = arr.map(function (u) {
            var label = (u.username || ('Usuario ' + u.id)) + (u.email ? (' (' + u.email + ')') : '');
            return (
                '<div class="d-flex justify-content-between align-items-center border rounded px-2 py-1 mb-1">' +
                '<div class="small">' + escapeHtml(label) + '</div>' +
                '<button type="button" class="btn btn-sm btn-outline-danger" data-remove-user="' + u.id + '">Quitar</button>' +
                '</div>'
            );
        }).join('');
        box.querySelectorAll('[data-remove-user]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var uid = parseInt(this.getAttribute('data-remove-user'), 10);
                if (!uid) return;
                removeShare(uid);
            });
        });
    }

    function renderUserResults(items) {
        var box = document.getElementById('bv-share-results');
        if (!box) return;
        var arr = Array.isArray(items) ? items : [];
        if (!arr.length) {
            box.innerHTML = '<div class="text-muted small">Sin resultados.</div>';
            return;
        }
        box.innerHTML = arr.map(function (u) {
            var label = (u.username || ('Usuario ' + u.id)) + (u.email ? (' (' + u.email + ')') : '');
            return (
                '<div class="d-flex justify-content-between align-items-center border rounded px-2 py-1 mb-1">' +
                '<div class="small">' + escapeHtml(label) + '</div>' +
                '<button type="button" class="btn btn-sm btn-primary" data-add-user="' + u.id + '">Agregar</button>' +
                '</div>'
            );
        }).join('');
        box.querySelectorAll('[data-add-user]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var uid = parseInt(this.getAttribute('data-add-user'), 10);
                if (!uid) return;
                addShare(uid);
            });
        });
    }

    function loadShares() {
        var p = pathShares();
        if (!p) return;
        api(p, { method: 'GET' })
            .then(function (r) { return r.json(); })
            .then(function (items) { renderCurrentShares(items); })
            .catch(function () { renderCurrentShares([]); });
    }

    function addShare(userId) {
        var p = pathShares();
        if (!p) return;
        api(p, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        }).then(function () { loadShares(); });
    }

    function removeShare(userId) {
        var p = pathShares();
        if (!p) return;
        api(p + '?user_id=' + encodeURIComponent(String(userId)), { method: 'DELETE' })
            .then(function () { loadShares(); });
    }

    function searchUsers(q) {
        var tok = ++usersQueryToken;
        api(pathUsers() + '?q=' + encodeURIComponent(q || ''), { method: 'GET' })
            .then(function (r) { return r.json(); })
            .then(function (items) {
                if (tok !== usersQueryToken) return;
                renderUserResults(items);
            })
            .catch(function () {
                if (tok !== usersQueryToken) return;
                renderUserResults([]);
            });
    }

    function openShareModal(type, id, title) {
        currentType = type;
        currentId = id;
        var t = document.getElementById('bv-share-title');
        if (t) t.textContent = title || 'Compartir';
        var inp = document.getElementById('bv-share-search');
        if (inp) inp.value = '';
        renderCurrentShares([]);
        renderUserResults([]);
        loadShares();
        if (modal) modal.show();
    }

    function init() {
        modalEl = document.getElementById('bvShareModal');
        if (!modalEl) return;
        modal = bootstrap.Modal.getOrCreateInstance(modalEl);

        document.querySelectorAll('[data-bv-share]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var type = this.getAttribute('data-share-type');
                var id = parseInt(this.getAttribute('data-share-id'), 10);
                var title = this.getAttribute('data-share-title') || '';
                if (!type || !id) return;
                openShareModal(type, id, title);
            });
        });

        var inp = document.getElementById('bv-share-search');
        if (inp) {
            inp.addEventListener('input', function () {
                var q = (this.value || '').trim();
                if (searchTimer) clearTimeout(searchTimer);
                searchTimer = setTimeout(function () { searchUsers(q); }, 250);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
