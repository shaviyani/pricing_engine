var API_BASE = window.RATE_LOOKUP_CFG.apiBase;
var rateData = window.RATE_LOOKUP_CFG.rateCardJson;
var currency = window.RATE_LOOKUP_CFG.currency;

function fmt(n) {
    return currency + parseFloat(n).toFixed(0);
}

function formatDate(iso) {
    var d = new Date(iso + 'T00:00:00');
    var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return days[d.getDay()] + ', ' + months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
}

function seasonClass(type) {
    if (type === 'peak') return 'season-peak';
    if (type === 'high') return 'season-high';
    if (type === 'low') return 'season-low';
    return 'season-shoulder';
}

function dpClass(mult) {
    if (mult > 1.02) return 'dp-up';
    if (mult < 0.98) return 'dp-down';
    return 'dp-neutral';
}

function renderRateCard(data) {
    // Header
    document.getElementById('headerDate').textContent = formatDate(data.target_date);

    if (data.season) {
        document.getElementById('headerSeason').innerHTML =
            '<span class="season-badge ' + seasonClass(data.season.type) + '">' +
            data.season.name + ' (' + data.season.date_range_display + ')</span>';
    } else {
        document.getElementById('headerSeason').innerHTML =
            '<span class="season-badge season-shoulder">No season defined</span>';
    }

    // Occupancy
    var occ = data.occupancy;
    document.getElementById('headerOcc').textContent = occ.booked + '/' + occ.total + ' (' + occ.pct + '%)';
    var bar = document.getElementById('headerOccBar');
    bar.style.width = Math.min(occ.pct, 100) + '%';
    bar.style.background = occ.pct >= 85 ? '#dc2626' : occ.pct >= 60 ? '#d97706' : '#16a34a';

    // Dynamic pricing
    var dp = data.dynamic_pricing;
    var dpMult = dp.combined_multiplier;
    var dpEl = document.getElementById('headerDP');
    dpEl.innerHTML = '<span>Dynamic Pricing:</span> <span class="dp-badge ' + dpClass(dpMult) + '">' +
        dpMult.toFixed(2) + 'x</span>';

    var evEl = document.getElementById('headerEvent');
    if (dp.event_name) {
        evEl.style.display = 'flex';
        evEl.innerHTML = '<span class="meta-value">' + dp.event_name + '</span> <span class="dp-badge dp-up">+' +
            ((dp.event_multiplier - 1) * 100).toFixed(0) + '%</span>';
    } else {
        evEl.style.display = 'none';
    }

    // Date picker
    document.getElementById('datePicker').value = data.target_date;

    // Table header
    var channels = data.channels;
    var headHtml = '<tr><th style="min-width:180px;">Room Type / Plan</th>';
    for (var i = 0; i < channels.length; i++) {
        headHtml += '<th style="text-align:right;">' + channels[i].name + '</th>';
    }
    headHtml += '</tr>';
    document.getElementById('rateHead').innerHTML = headHtml;

    // Table body
    var rooms = data.room_types;
    var ratePlans = data.rate_plans;
    var bodyHtml = '';

    for (var r = 0; r < rooms.length; r++) {
        var room = rooms[r];

        // Room header row
        bodyHtml += '<tr class="room-header"><td colspan="' + (channels.length + 1) + '">' +
            room.room_type_name +
            '<span class="room-meta">' + room.number_of_rooms + ' rooms | Base: ' + fmt(room.base_rate) +
            ' | Seasonal: ' + fmt(room.seasonal_rate) + ' | DP: ' + fmt(room.dp_rate) + '</span>' +
            '</td></tr>';

        // Rate plan rows
        for (var p = 0; p < ratePlans.length; p++) {
            var rp = ratePlans[p];
            bodyHtml += '<tr>';
            bodyHtml += '<td class="plan-label">' + rp.name;
            if (rp.meal_supplement > 0) {
                bodyHtml += ' <span style="color:#94a3b8;font-size:11px;">(+' + fmt(rp.meal_supplement) + '/pp)</span>';
            }
            bodyHtml += '</td>';

            for (var c = 0; c < channels.length; c++) {
                var ch = room.channels[c];
                var rpData = ch.rate_plans[p];
                var warn = rpData.warnings && rpData.warnings.length > 0;
                bodyHtml += '<td class="rate-cell' + (warn ? ' has-warning' : '') + '">' +
                    fmt(rpData.final_rate) + '</td>';
            }
            bodyHtml += '</tr>';
        }
    }

    document.getElementById('rateBody').innerHTML = bodyHtml;

    // Footer
    document.getElementById('footerTax').textContent =
        'All rates include ' + data.service_charge_percent + '% service charge + ' + data.tax_percent + '% GST';
    document.getElementById('footerGenerated').textContent =
        'Generated: ' + new Date().toLocaleString();
}

function loadRateCard(dateStr) {
    document.getElementById('loadingOverlay').style.display = 'flex';
    fetch(API_BASE + '/api/rate-card/?date=' + dateStr)
    .then(function(r) { return r.json(); })
    .then(function(d) {
        document.getElementById('loadingOverlay').style.display = 'none';
        if (d.success) {
            rateData = d.data;
            renderRateCard(d.data);
        }
    })
    .catch(function(err) {
        document.getElementById('loadingOverlay').style.display = 'none';
        console.error('Rate card error:', err);
    });
}

function shiftDate(days) {
    var current = document.getElementById('datePicker').value;
    var d = new Date(current + 'T00:00:00');
    d.setDate(d.getDate() + days);
    var iso = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    loadRateCard(iso);
}

function goToday() {
    var d = new Date();
    var iso = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    loadRateCard(iso);
}

// Initial render from server-provided data
renderRateCard(rateData);

// ── Itinerary Builder ──

function openItinerary() {
    populateItineraryForm();
    document.getElementById('itinOverlay').classList.add('open');
}

function closeItinerary() {
    document.getElementById('itinOverlay').classList.remove('open');
}

function populateItineraryForm() {
    // Room types
    var roomSel = document.getElementById('itinRoom');
    roomSel.innerHTML = '';
    for (var i = 0; i < rateData.room_types.length; i++) {
        var rt = rateData.room_types[i];
        var opt = document.createElement('option');
        opt.value = rt.room_type_id;
        opt.textContent = rt.room_type_name;
        roomSel.appendChild(opt);
    }

    // Channels
    var chSel = document.getElementById('itinChannel');
    chSel.innerHTML = '';
    for (var i = 0; i < rateData.channels.length; i++) {
        var ch = rateData.channels[i];
        var opt = document.createElement('option');
        opt.value = ch.id;
        opt.textContent = ch.name;
        chSel.appendChild(opt);
    }

    // Rate plans
    var rpSel = document.getElementById('itinPlan');
    rpSel.innerHTML = '';
    for (var i = 0; i < rateData.rate_plans.length; i++) {
        var rp = rateData.rate_plans[i];
        var opt = document.createElement('option');
        opt.value = rp.id;
        opt.textContent = rp.name;
        rpSel.appendChild(opt);
    }

    // Default dates: check-in = current rate card date, check-out = +1
    var ci = document.getElementById('itinCheckin');
    var co = document.getElementById('itinCheckout');
    ci.value = rateData.target_date;
    var nextDay = new Date(rateData.target_date + 'T00:00:00');
    nextDay.setDate(nextDay.getDate() + 1);
    var nextDayIso = nextDay.getFullYear() + '-' + String(nextDay.getMonth() + 1).padStart(2, '0') + '-' + String(nextDay.getDate()).padStart(2, '0');
    co.value = nextDayIso;
    co.min = nextDayIso;
}

function updateCheckoutMin() {
    var ci = document.getElementById('itinCheckin').value;
    if (!ci) return;
    var d = new Date(ci + 'T00:00:00');
    d.setDate(d.getDate() + 1);
    var minCo = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    var co = document.getElementById('itinCheckout');
    co.min = minCo;
    if (co.value && co.value <= ci) {
        co.value = minCo;
    }
}

function buildItinerary() {
    var checkin = document.getElementById('itinCheckin').value;
    var checkout = document.getElementById('itinCheckout').value;
    var roomType = document.getElementById('itinRoom').value;
    var channel = document.getElementById('itinChannel').value;
    var ratePlan = document.getElementById('itinPlan').value;
    var pax = document.getElementById('itinPax').value;

    var errEl = document.getElementById('itinError');
    var resEl = document.getElementById('itinResult');
    errEl.style.display = 'none';
    resEl.innerHTML = '';

    if (!checkin || !checkout) {
        errEl.textContent = 'Please select check-in and check-out dates.';
        errEl.style.display = 'block';
        return;
    }

    document.getElementById('loadingOverlay').style.display = 'flex';

    var url = API_BASE + '/api/itinerary-quote/?checkin=' + checkin +
        '&checkout=' + checkout + '&room_type=' + roomType +
        '&channel=' + channel + '&rate_plan=' + ratePlan + '&pax=' + pax;

    fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(d) {
        document.getElementById('loadingOverlay').style.display = 'none';
        if (d.error) {
            errEl.textContent = d.error;
            errEl.style.display = 'block';
            return;
        }
        if (d.success) {
            renderItinerary(d.data);
        }
    })
    .catch(function(err) {
        document.getElementById('loadingOverlay').style.display = 'none';
        errEl.textContent = 'Failed to fetch quote. Please try again.';
        errEl.style.display = 'block';
        console.error('Itinerary error:', err);
    });
}

var lastQuoteData = null;

function renderItinerary(data) {
    lastQuoteData = data;
    var cur = data.currency;
    var fmtD = function(n) { return cur + parseFloat(n).toFixed(0); };
    var fmtC = function(n) { return cur + parseFloat(n).toFixed(2); };

    var html = '<table class="itin-table">';
    html += '<thead><tr>';
    html += '<th>Night</th><th>Season</th>';
    html += '<th>Room Rate</th><th>Meal</th><th>Service Chg</th><th>Tax</th><th>Total</th>';
    html += '</tr></thead><tbody>';

    for (var i = 0; i < data.nights.length; i++) {
        var n = data.nights[i];
        html += '<tr>';
        html += '<td>' + n.date_display + '</td>';
        html += '<td style="text-align:left;">' + n.season + '</td>';
        html += '<td>' + fmtD(n.room_rate) + '</td>';
        html += '<td>' + fmtD(n.meal) + '</td>';
        html += '<td>' + fmtD(n.service_charge) + '</td>';
        html += '<td>' + fmtD(n.tax) + '</td>';
        html += '<td style="font-weight:700;">' + fmtD(n.final_rate) + '</td>';
        html += '</tr>';
    }

    // Totals row
    var t = data.totals;
    html += '<tr class="itin-total">';
    html += '<td colspan="2">Total (' + t.nights + ' night' + (t.nights > 1 ? 's' : '') + ')</td>';
    html += '<td>' + fmtC(t.room_total) + '</td>';
    html += '<td>' + fmtC(t.meal_total) + '</td>';
    html += '<td>' + fmtC(t.sc_total) + '</td>';
    html += '<td>' + fmtC(t.tax_total) + '</td>';
    html += '<td>' + fmtC(t.grand_total) + '</td>';
    html += '</tr>';
    html += '</tbody></table>';

    // Summary banner
    html += '<div class="itin-summary">';
    html += '<div>';
    html += '<div class="itin-details">' + data.room_type_name + ' &middot; ' +
        data.rate_plan_name + ' &middot; ' + data.channel_name + ' &middot; ' +
        data.pax + ' guest' + (data.pax > 1 ? 's' : '') + '</div>';
    html += '<div class="itin-details" style="margin-top:4px;">' +
        formatDate(data.checkin) + ' &rarr; ' + formatDate(data.checkout) +
        ' (' + t.nights + ' night' + (t.nights > 1 ? 's' : '') + ')</div>';
    html += '</div>';
    html += '<div class="itin-grand">' + fmtC(t.grand_total) + '</div>';
    html += '</div>';

    html += '<div class="itin-actions">';
    html += '<button class="dl-btn" onclick="downloadQuote()">&#x2913; Download Quote</button>';
    html += '</div>';

    document.getElementById('itinResult').innerHTML = html;
}

function downloadQuote() {
    if (!lastQuoteData) return;
    var data = lastQuoteData;
    var t = data.totals;
    var cur = data.currency;
    var fmtD = function(n) { return cur + parseFloat(n).toFixed(0); };
    var fmtC = function(n) { return cur + parseFloat(n).toFixed(2); };
    var propName = window.RATE_LOOKUP_CFG.propName;
    var propLocation = window.RATE_LOOKUP_CFG.propLocation;
    var scPct = window.RATE_LOOKUP_CFG.serviceChargePercent;
    var taxPct = window.RATE_LOOKUP_CFG.taxPercent;

    var rows = '';
    for (var i = 0; i < data.nights.length; i++) {
        var n = data.nights[i];
        rows += '<tr>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;">' + n.date_display + '</td>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;">' + n.season + '</td>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmtD(n.room_rate) + '</td>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmtD(n.meal) + '</td>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmtD(n.service_charge) + '</td>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmtD(n.tax) + '</td>' +
            '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:700;">' + fmtD(n.final_rate) + '</td>' +
            '</tr>';
    }

    var doc = '<!DOCTYPE html><html><head><meta charset="utf-8">' +
        '<title>Quotation - ' + propName + '</title>' +
        '<style>' +
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:40px;color:#1e293b;font-size:14px;}' +
        '.header{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:28px 32px;border-radius:12px;margin-bottom:24px;}' +
        '.header h1{margin:0;font-size:22px;font-weight:800;}' +
        '.header .sub{font-size:13px;opacity:0.8;margin-top:4px;}' +
        '.header .title{font-size:18px;font-weight:800;text-align:right;}' +
        '.guest-info{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:20px;padding:16px 20px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;}' +
        '.guest-info .gi{font-size:13px;color:#64748b;}' +
        '.guest-info .gi strong{color:#1e293b;}' +
        'table{width:100%;border-collapse:collapse;margin-bottom:20px;}' +
        'th{background:#f8fafc;padding:10px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;border-bottom:2px solid #e2e8f0;text-align:right;}' +
        'th:first-child,th:nth-child(2){text-align:left;}' +
        '.total-row td{font-weight:700;font-size:14px;background:#f0f9ff;border-top:2px solid #bfdbfe;color:#1e40af;padding:10px 12px;text-align:right;}' +
        '.total-row td:first-child{text-align:left;}' +
        '.grand{margin-top:4px;padding:20px;background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);border-radius:10px;color:#fff;display:flex;justify-content:space-between;align-items:center;}' +
        '.grand .amount{font-size:28px;font-weight:800;}' +
        '.grand .details{font-size:13px;opacity:0.9;}' +
        '.notes{margin-top:24px;padding:16px 20px;border:1px solid #e2e8f0;border-radius:8px;font-size:12px;color:#64748b;}' +
        '.notes h3{margin:0 0 8px;font-size:13px;color:#1e293b;}' +
        '.footer{margin-top:24px;text-align:center;font-size:11px;color:#94a3b8;}' +
        '@media print{body{padding:20px;}.header{-webkit-print-color-adjust:exact;print-color-adjust:exact;}.grand{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}' +
        '</style></head><body>' +
        '<div class="header"><div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
        '<div><h1>' + propName + '</h1><p class="sub">' + propLocation + '</p></div>' +
        '<div class="title">Quotation</div></div></div>' +
        '<div class="guest-info">' +
        '<div class="gi"><strong>Room:</strong> ' + data.room_type_name + '</div>' +
        '<div class="gi"><strong>Plan:</strong> ' + data.rate_plan_name + '</div>' +
        '<div class="gi"><strong>Channel:</strong> ' + data.channel_name + '</div>' +
        '<div class="gi"><strong>Guests:</strong> ' + data.pax + '</div>' +
        '<div class="gi"><strong>Check-in:</strong> ' + formatDate(data.checkin) + '</div>' +
        '<div class="gi"><strong>Check-out:</strong> ' + formatDate(data.checkout) + '</div>' +
        '<div class="gi"><strong>Nights:</strong> ' + t.nights + '</div>' +
        '</div>' +
        '<table><thead><tr>' +
        '<th>Night</th><th>Season</th><th>Room Rate</th><th>Meal</th><th>Service Chg</th><th>Tax</th><th>Total</th>' +
        '</tr></thead><tbody>' + rows +
        '<tr class="total-row">' +
        '<td colspan="2">Total (' + t.nights + ' night' + (t.nights > 1 ? 's' : '') + ')</td>' +
        '<td>' + fmtC(t.room_total) + '</td><td>' + fmtC(t.meal_total) + '</td>' +
        '<td>' + fmtC(t.sc_total) + '</td><td>' + fmtC(t.tax_total) + '</td>' +
        '<td>' + fmtC(t.grand_total) + '</td>' +
        '</tr></tbody></table>' +
        '<div class="grand"><div>' +
        '<div class="details">' + data.room_type_name + ' &middot; ' + data.rate_plan_name + ' &middot; ' + data.pax + ' guest' + (data.pax > 1 ? 's' : '') + '</div>' +
        '<div class="details" style="margin-top:4px;">' + formatDate(data.checkin) + ' &rarr; ' + formatDate(data.checkout) + '</div>' +
        '</div><div class="amount">' + fmtC(t.grand_total) + '</div></div>' +
        '<div class="notes"><h3>Notes</h3>' +
        '<p>All rates include ' + scPct + '% service charge and ' + taxPct + '% GST. Subject to availability at the time of booking.</p>' +
        '<p>All guests on tourist visa will be required to pay $6 Green Tax per person per night.</p>' +
        '</div>' +
        '<div class="footer">Generated on ' + new Date().toLocaleString() + ' | ' + propName + '</div>' +
        '</body></html>';

    var w = window.open('', '_blank');
    w.document.write(doc);
    w.document.close();
    w.onload = function() { w.print(); };
}
