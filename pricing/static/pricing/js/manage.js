/* Management section JS — shared across all manage/ pages */

// CSRF
function getCookie(name) {
    var v = null;
    if (document.cookie) {
        document.cookie.split(';').forEach(function(c) {
            c = c.trim();
            if (c.substring(0, name.length + 1) === (name + '='))
                v = decodeURIComponent(c.substring(name.length + 1));
        });
    }
    return v;
}

// Toast
function showToast(msg, type) {
    type = type || 'success';
    var t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    document.getElementById('toastContainer').appendChild(t);
    setTimeout(function() { t.remove(); }, 3000);
}

// Modals
function openModal(id) { document.getElementById(id).classList.add('active'); document.body.style.overflow = 'hidden'; }
function closeModal(id) {
    document.getElementById(id).classList.remove('active');
    document.body.style.overflow = '';
    var f = document.getElementById(id.replace('Modal', 'Form'));
    if (f) f.reset();
}
function closeModalOnOverlay(e) {
    if (e.target.classList.contains('modal-overlay')) { e.target.classList.remove('active'); document.body.style.overflow = ''; }
}

// Tab switching
document.querySelectorAll('.tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var tabId = this.dataset.tab;
        var nav = this.closest('.tab-nav');
        var container = nav.parentElement;
        nav.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
        container.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
        this.classList.add('active');
        var el = document.getElementById('tab-' + tabId);
        if (el) el.classList.add('active');
    });
});
// Initialize: activate first tab's content on load
document.querySelectorAll('.tab-nav').forEach(function(nav) {
    var activeBtn = nav.querySelector('.tab-btn.active');
    if (activeBtn) {
        var tabId = activeBtn.dataset.tab;
        var el = document.getElementById('tab-' + tabId);
        if (el) el.classList.add('active');
    }
});

// API URL helper
function getApiUrl(type, action, id) {
    var propTypes = ['season', 'room', 'season-override', 'reservation'];
    var base = propTypes.indexOf(type) >= 0 ? API_BASE : SHARED_API_BASE;
    var map = { season:'seasons', room:'room-types', rateplan:'rate-plans', channel:'channels', modifier:'modifiers', 'season-override':'season-overrides', reservation:'reservations' };
    var ep = map[type] || type + 's';
    if (action === 'create') return base + '/api/' + ep + '/create/';
    if (action === 'update' || action === 'delete') return base + '/api/' + ep + '/' + id + '/' + action + '/';
    if (action === 'toggle') return base + '/api/' + ep + '/' + id + '/toggle/';
    return base + '/api/' + ep + '/';
}

// Inline update
function updateField(input) {
    var type = input.dataset.type, id = input.dataset.id, field = input.dataset.field;
    var value = input.type === 'checkbox' ? input.checked : input.value;
    input.classList.add('saving');
    var d = {}; d[field] = value;
    fetch(getApiUrl(type, 'update', id), {
        method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')},
        body:JSON.stringify(d)
    }).then(function(r){return r.json();}).then(function(data){
        input.classList.remove('saving');
        if(data.success){input.classList.add('saved');setTimeout(function(){input.classList.remove('saved');},1000);}
        else{input.classList.add('error');showToast(data.error||'Failed','error');setTimeout(function(){input.classList.remove('error');},2000);}
    }).catch(function(){input.classList.remove('saving');input.classList.add('error');showToast('Network error','error');});
}

// Property update
function updatePropertyField(input) {
    var field = input.dataset.field; input.classList.add('saving');
    var d = {}; d[field] = input.value;
    fetch(API_BASE + '/api/property/update/', {
        method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')},
        body:JSON.stringify(d)
    }).then(function(r){return r.json();}).then(function(data){
        input.classList.remove('saving');
        if(data.success){input.classList.add('saved');showToast('Updated');setTimeout(function(){input.classList.remove('saved');},1000);}
        else{input.classList.add('error');showToast(data.error||'Failed','error');}
    }).catch(function(){input.classList.remove('saving');showToast('Network error','error');});
}

function updatePropertyToggle(field, value) {
    var d = {}; d[field] = value;
    fetch(API_BASE + '/api/property/update/', {
        method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')},
        body:JSON.stringify(d)
    }).then(function(r){return r.json();}).then(function(data){
        if(data.success) showToast('Updated'); else showToast(data.error||'Failed','error');
    });
}

// Submit form (create)
function submitForm(event, type) {
    event.preventDefault();
    var d = {};
    new FormData(event.target).forEach(function(v,k){d[k]=v;});
    fetch(getApiUrl(type,'create'), {
        method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')},
        body:JSON.stringify(d)
    }).then(function(r){return r.json();}).then(function(data){
        if(data.success){showToast(data.message||'Created');closeModal(type+'Modal');setTimeout(function(){location.reload();},500);}
        else showToast(data.error||'Failed','error');
    }).catch(function(){showToast('Network error','error');});
}

// Delete
var deleteType, deleteId;
function deleteItem(type, id, name) {
    deleteType=type; deleteId=id;
    document.getElementById('deleteItemName').textContent=name;
    document.getElementById('confirmDeleteBtn').onclick=confirmDelete;
    openModal('deleteModal');
}
function confirmDelete() {
    fetch(getApiUrl(deleteType,'delete',deleteId), {
        method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')}
    }).then(function(r){return r.json();}).then(function(data){
        if(data.success){showToast(data.message||'Deleted');closeModal('deleteModal');var r=document.querySelector('tr[data-id="'+deleteId+'"]');if(r)r.remove();}
        else showToast(data.error||'Failed','error');
    });
}

// Hotkeys: 0-8 navigate sections
var sectionLinks = document.querySelectorAll('.section-nav .section-btn');
document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(function(m){m.classList.remove('active');});
        document.body.style.overflow = '';
        return;
    }
    var idx = parseInt(e.key);
    if (!isNaN(idx) && idx >= 0 && idx <= 8 && sectionLinks[idx]) {
        sectionLinks[idx].click();
    }
});
