var currentModalData = null;

document.addEventListener('DOMContentLoaded', function() {
    loadCalendarRates();
});

function loadCalendarRates() {
    var roomId = document.getElementById('calendarRoom').value;
    var channelId = document.getElementById('calendarChannel').value;
    var ratePlanId = document.getElementById('calendarRatePlan').value;
    var loadingEl = document.getElementById('ratesLoading');

    loadingEl.classList.remove('hidden');

    var rateEls = document.querySelectorAll('.day-rate');
    for (var i = 0; i < rateEls.length; i++) {
        rateEls[i].textContent = '—';
        rateEls[i].classList.add('loading');
    }

    var overrideEls = document.querySelectorAll('[id^="override-"]');
    for (var i = 0; i < overrideEls.length; i++) {
        overrideEls[i].innerHTML = '';
    }

    var url = window.CALENDAR_CONFIG.apiBaseUrl + 'api/calendar-rates/' +
        '?year=' + window.CALENDAR_CONFIG.currentYear +
        '&month=' + window.CALENDAR_CONFIG.currentMonth +
        '&channel_id=' + channelId +
        '&rate_plan_id=' + ratePlanId;

    if (roomId) url += '&room_type_id=' + roomId;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            loadingEl.classList.add('hidden');
            updateCalendarRates(data);
        })
        .catch(function(e) {
            console.error(e);
            loadingEl.classList.add('hidden');
        });
}

function updateCalendarRates(data) {
    var rates = data.rates;

    for (var dateStr in rates) {
        var d = rates[dateStr];
        var rateEl = document.getElementById('rate-' + dateStr);
        var overrideEl = document.getElementById('override-' + dateStr);
        var dayEl = document.getElementById('day-' + dateStr);
        var occEl = document.getElementById('occupancy-' + dateStr);

        if (rateEl) {
            rateEl.classList.remove('loading');
            rateEl.textContent = d.rate ? window.CALENDAR_CONFIG.currency + d.rate : '—';
        }

        if (overrideEl && d.has_override) {
            var cls = d.is_increase ? 'increase' : 'decrease';
            overrideEl.innerHTML = '<span class="day-override-badge ' + cls + '">' + d.override_adjustment + '</span>';
        }

        if (dayEl) {
            dayEl.classList.remove('has-override', 'increase', 'decrease');
            if (d.has_override) {
                dayEl.classList.add('has-override', d.is_increase ? 'increase' : 'decrease');
            }
        }

        if (occEl && d.occupancy) {
            var occ = d.occupancy;
            var bar = occEl.querySelector('.occupancy-bar');
            var label = occEl.querySelector('.occupancy-label');

            bar.style.width = occ.percent + '%';
            bar.classList.remove('low', 'medium', 'high', 'full');
            if (occ.percent >= 100) bar.classList.add('full');
            else if (occ.percent >= 80) bar.classList.add('high');
            else if (occ.percent >= 50) bar.classList.add('medium');
            else bar.classList.add('low');

            if (label) label.textContent = occ.percent + '%';

            var tp = occEl.querySelector('.occ-percent');
            var to = occEl.querySelector('.occ-occupied');
            var ta = occEl.querySelector('.occ-available');
            if (tp) tp.textContent = occ.percent + '%';
            if (to) to.textContent = occ.rooms_occupied;
            if (ta) ta.textContent = occ.rooms_available;
        }
    }
}

function showDateRates(dateStr) {
    var modal = document.getElementById('ratesModal');
    var modalTitle = document.getElementById('modalTitle');
    var modalSubtitle = document.getElementById('modalSubtitle');
    var modalBody = document.getElementById('modalBody');

    document.getElementById('filterRoom').value = '';
    document.getElementById('filterChannel').value = '';

    var dateObj = new Date(dateStr + 'T00:00:00');
    var opts = { weekday: 'short', month: 'short', day: 'numeric' };
    modalTitle.textContent = dateObj.toLocaleDateString('en-US', opts);
    modalSubtitle.textContent = 'Loading...';
    modalBody.innerHTML = '<div class="text-center py-12"><div class="spinner"></div></div>';

    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    fetch(window.CALENDAR_CONFIG.apiBaseUrl + 'api/date-rate-detail/?date=' + dateStr)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            currentModalData = data;
            renderModalRates(data, '', '');
        })
        .catch(function(e) {
            console.error(e);
            modalBody.innerHTML = '<div class="no-results">Error loading rates</div>';
        });
}

function applyModalFilters() {
    if (!currentModalData) return;
    renderModalRates(currentModalData,
        document.getElementById('filterRoom').value,
        document.getElementById('filterChannel').value);
}

function renderModalRates(data, roomFilter, channelFilter) {
    var modalSubtitle = document.getElementById('modalSubtitle');
    var modalBody = document.getElementById('modalBody');

    if (data.error) {
        modalBody.innerHTML = '<div class="no-results">' + data.error + '</div>';
        return;
    }

    var season = data.season;
    var override = data.override;
    var rates = data.rates;

    modalSubtitle.textContent = season ? season.name + ' • ' + season.index : 'No Season';

    var html = '';

    if (override) {
        var isInc = override.adjustment_value && parseFloat(override.adjustment_value) >= 0;
        html += '<div class="mb-4 p-3 rounded-lg ' + (isInc ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200') + '">';
        html += '<div class="flex items-center justify-between text-sm">';
        html += '<span class="font-medium">' + override.name + '</span>';
        html += '<span class="font-bold ' + (isInc ? 'text-green-600' : 'text-red-600') + '">' + override.adjustment + '</span>';
        html += '</div></div>';
    }

    if (!rates || !rates.length) {
        html += '<div class="no-results">No rates available</div>';
        modalBody.innerHTML = html;
        return;
    }

    var isInc = override && override.adjustment_value && parseFloat(override.adjustment_value) >= 0;
    var hasResults = false;

    for (var i = 0; i < rates.length; i++) {
        var room = rates[i];
        if (roomFilter && room.room_type_id != roomFilter) continue;

        var filtered = [];
        for (var j = 0; j < room.rates.length; j++) {
            var r = room.rates[j];
            if (!channelFilter || r.channel_id == channelFilter) filtered.push(r);
        }
        if (!filtered.length) continue;

        hasResults = true;
        html += '<div class="rate-section">';
        html += '<div class="rate-section-title">' + room.room_type_name + '</div>';
        html += '<table class="rate-table"><thead><tr>';
        html += '<th>Plan</th><th>Channel</th><th class="text-right">BAR</th><th class="text-right">Rate</th>';
        html += '</tr></thead><tbody>';

        for (var j = 0; j < filtered.length; j++) {
            var r = filtered[j];
            html += '<tr><td>' + r.rate_plan_name + '</td><td>' + r.channel_name + '</td>';
            html += '<td class="bar-value">' + window.CALENDAR_CONFIG.currency + r.bar_rate + '</td>';
            html += '<td class="rate-value">' + window.CALENDAR_CONFIG.currency + r.final_rate;
            if (r.override_applied) html += '<span class="override-dot ' + (isInc ? 'increase' : 'decrease') + '"></span>';
            html += '</td></tr>';
        }
        html += '</tbody></table></div>';
    }

    if (!hasResults) html += '<div class="no-results">No matching rates</div>';
    modalBody.innerHTML = html;
}

function closeModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('ratesModal').classList.remove('active');
    document.body.style.overflow = '';
    currentModalData = null;
}

document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeModal(); });
