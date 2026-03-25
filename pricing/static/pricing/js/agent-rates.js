/**
 * Agent Rates & Rate Card shared JavaScript.
 *
 * Requires these globals set by the template before this script loads:
 *   - window.AGENT_CFG.apiBase     (string)  e.g. '/org/abc/prop1'
 *   - window.AGENT_CFG.channelId   (int)
 *   - window.AGENT_CFG.currency    (string)  e.g. '$'
 *   - window.AGENT_CFG.matrixData  (array)
 *   - window.AGENT_CFG.ratePlans   (array)
 *   - window.AGENT_CFG.pdfUrl      (string)  base URL for PDF download
 *   - window.AGENT_CFG.quoteMeta   (object)  { propName, propLocation, headerLabel, scPct, taxPct }
 */

var CFG = window.AGENT_CFG || {};

function fmt(n) { return CFG.currency + parseFloat(n).toFixed(0); }
function fmtC(n) { return CFG.currency + parseFloat(n).toFixed(2); }

function formatDate(iso) {
    var d = new Date(iso + 'T00:00:00');
    var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return days[d.getDay()] + ', ' + months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
}

// ── Plan Toggles ──

function togglePlan(btn, planId) {
    btn.classList.toggle('active');
    var rows = document.querySelectorAll('tr.plan-row[data-plan-id="' + planId + '"]');
    var show = btn.classList.contains('active');
    for (var i = 0; i < rows.length; i++) {
        rows[i].style.display = show ? '' : 'none';
    }
}

function downloadPDF() {
    var activeBtns = document.querySelectorAll('.plan-toggle.active');
    var ids = [];
    for (var i = 0; i < activeBtns.length; i++) {
        ids.push(activeBtns[i].getAttribute('data-plan-id'));
    }
    var url = CFG.pdfUrl;
    if (ids.length) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'plans=' + ids.join(',');
    window.location.href = url;
}

// ── Tabs ──

var formPopulated = false;

function switchTab(tab) {
    var tabs = document.querySelectorAll('.agent-tabs .tab');
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.remove('active');

    document.getElementById('tabRatecard').classList.remove('active');
    document.getElementById('tabQuote').classList.remove('active');

    if (tab === 'ratecard') {
        tabs[0].classList.add('active');
        document.getElementById('tabRatecard').classList.add('active');
    } else {
        tabs[1].classList.add('active');
        document.getElementById('tabQuote').classList.add('active');
        if (!formPopulated) {
            populateItineraryForm();
            formPopulated = true;
        }
    }
}

// ── Quote Builder ──

var roomLineId = 0;

function populateItineraryForm() {
    var today = new Date();
    var ci = document.getElementById('itinCheckin');
    var co = document.getElementById('itinCheckout');
    var todayIso = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    ci.value = todayIso;
    var nextDay = new Date(today);
    nextDay.setDate(nextDay.getDate() + 1);
    var nextDayIso = nextDay.getFullYear() + '-' + String(nextDay.getMonth() + 1).padStart(2, '0') + '-' + String(nextDay.getDate()).padStart(2, '0');
    co.value = nextDayIso;
    co.min = nextDayIso;
    addRoomLine();
}

function buildRoomOptions() {
    var h = '';
    for (var i = 0; i < CFG.matrixData.length; i++) {
        h += '<option value="' + CFG.matrixData[i].room_type_id + '">' + CFG.matrixData[i].room_type_name + '</option>';
    }
    return h;
}

function buildPlanOptions() {
    var h = '';
    for (var i = 0; i < CFG.ratePlans.length; i++) {
        h += '<option value="' + CFG.ratePlans[i].id + '">' + CFG.ratePlans[i].name + '</option>';
    }
    return h;
}

function addRoomLine() {
    roomLineId++;
    var container = document.getElementById('roomLines');
    var div = document.createElement('div');
    div.className = 'room-line';
    div.id = 'roomLine' + roomLineId;
    div.innerHTML =
        '<div><label>Room Type</label><select data-field="room">' + buildRoomOptions() + '</select></div>' +
        '<div><label>Rate Plan</label><select data-field="plan">' + buildPlanOptions() + '</select></div>' +
        '<div><label>Rooms</label><input type="number" data-field="qty" value="1" min="1" max="20"></div>' +
        '<div><label>Guests</label><input type="number" data-field="pax" value="2" min="1" max="10"></div>' +
        '<div><button type="button" class="rm-btn" onclick="removeRoomLine(' + roomLineId + ')" title="Remove">&times;</button></div>';
    container.appendChild(div);
}

function removeRoomLine(id) {
    var el = document.getElementById('roomLine' + id);
    if (el) el.remove();
    if (document.getElementById('roomLines').children.length === 0) addRoomLine();
}

function updateCheckoutMin() {
    var ci = document.getElementById('itinCheckin').value;
    if (!ci) return;
    var d = new Date(ci + 'T00:00:00');
    d.setDate(d.getDate() + 1);
    var minCo = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    var co = document.getElementById('itinCheckout');
    co.min = minCo;
    if (co.value && co.value <= ci) co.value = minCo;
}

function getRoomLines() {
    var lines = [];
    var els = document.querySelectorAll('#roomLines .room-line');
    for (var i = 0; i < els.length; i++) {
        var el = els[i];
        lines.push({
            room_type: el.querySelector('[data-field="room"]').value,
            rate_plan: el.querySelector('[data-field="plan"]').value,
            qty: parseInt(el.querySelector('[data-field="qty"]').value) || 1,
            pax: parseInt(el.querySelector('[data-field="pax"]').value) || 2,
        });
    }
    return lines;
}

function buildItinerary() {
    var checkin = document.getElementById('itinCheckin').value;
    var checkout = document.getElementById('itinCheckout').value;
    var roomLines = getRoomLines();

    var errEl = document.getElementById('itinError');
    var resEl = document.getElementById('itinResult');
    errEl.style.display = 'none';
    resEl.innerHTML = '<div style="text-align:center;padding:20px;color:#64748b;">Loading...</div>';

    if (!checkin || !checkout) {
        errEl.textContent = 'Please select check-in and check-out dates.';
        errEl.style.display = 'block';
        resEl.innerHTML = '';
        return;
    }
    if (roomLines.length === 0) {
        errEl.textContent = 'Please add at least one room.';
        errEl.style.display = 'block';
        resEl.innerHTML = '';
        return;
    }

    var fetches = [];
    for (var i = 0; i < roomLines.length; i++) {
        var rl = roomLines[i];
        var url = CFG.apiBase + '/api/itinerary-quote/?checkin=' + checkin +
            '&checkout=' + checkout + '&room_type=' + rl.room_type +
            '&channel=' + CFG.channelId + '&rate_plan=' + rl.rate_plan + '&pax=' + rl.pax;
        fetches.push({ url: url, qty: rl.qty, pax: rl.pax });
    }

    var results = [];
    var done = 0;
    var hasError = false;

    for (var i = 0; i < fetches.length; i++) {
        (function(idx) {
            fetch(fetches[idx].url)
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.error) {
                    hasError = true;
                    errEl.textContent = d.error;
                    errEl.style.display = 'block';
                } else if (d.success) {
                    d.data.qty = fetches[idx].qty;
                    results[idx] = d.data;
                }
                done++;
                if (done === fetches.length && !hasError) renderMultiRoomQuote(results);
                if (done === fetches.length && hasError) resEl.innerHTML = '';
            })
            .catch(function() {
                hasError = true;
                errEl.textContent = 'Failed to fetch quote. Please try again.';
                errEl.style.display = 'block';
                done++;
                if (done === fetches.length) resEl.innerHTML = '';
            });
        })(i);
    }
}

var lastQuoteData = null;

function renderMultiRoomQuote(rooms) {
    lastQuoteData = rooms;
    var grandTotals = { room_total: 0, meal_total: 0, sc_total: 0, tax_total: 0, grand_total: 0, nights: 0 };
    var html = '';

    for (var r = 0; r < rooms.length; r++) {
        var data = rooms[r];
        var qty = data.qty || 1;
        var t = data.totals;
        grandTotals.nights = t.nights;

        html += '<div style="margin-top:' + (r > 0 ? '20px' : '0') + ';padding:8px 12px;background:#f0f9ff;border-radius:8px;border:1px solid #bfdbfe;font-size:13px;font-weight:700;color:#1e40af;">';
        html += data.room_type_name + ' &mdash; ' + data.rate_plan_name;
        if (qty > 1) html += ' <span style="color:#64748b;font-weight:400;">(&times;' + qty + ' rooms)</span>';
        html += '</div>';

        html += '<table class="itin-table"><thead><tr>';
        html += '<th>Night</th><th>Season</th>';
        html += '<th>Room Rate</th><th>Meal</th><th>Service Chg</th><th>Tax</th><th>Total</th>';
        html += '</tr></thead><tbody>';

        for (var i = 0; i < data.nights.length; i++) {
            var n = data.nights[i];
            html += '<tr>';
            html += '<td>' + n.date_display + '</td>';
            html += '<td style="text-align:left;">' + n.season + '</td>';
            html += '<td>' + fmt(n.room_rate * qty) + '</td>';
            html += '<td>' + fmt(n.meal * qty) + '</td>';
            html += '<td>' + fmt(n.service_charge * qty) + '</td>';
            html += '<td>' + fmt(n.tax * qty) + '</td>';
            html += '<td style="font-weight:700;">' + fmt(n.final_rate * qty) + '</td>';
            html += '</tr>';
        }

        var lineTotal = t.grand_total * qty;
        html += '<tr class="itin-total">';
        html += '<td colspan="2">Subtotal (' + t.nights + ' night' + (t.nights > 1 ? 's' : '') + (qty > 1 ? ' &times; ' + qty + ' rooms' : '') + ')</td>';
        html += '<td>' + fmtC(t.room_total * qty) + '</td>';
        html += '<td>' + fmtC(t.meal_total * qty) + '</td>';
        html += '<td>' + fmtC(t.sc_total * qty) + '</td>';
        html += '<td>' + fmtC(t.tax_total * qty) + '</td>';
        html += '<td>' + fmtC(lineTotal) + '</td>';
        html += '</tr></tbody></table>';

        grandTotals.room_total += t.room_total * qty;
        grandTotals.meal_total += t.meal_total * qty;
        grandTotals.sc_total += t.sc_total * qty;
        grandTotals.tax_total += t.tax_total * qty;
        grandTotals.grand_total += t.grand_total * qty;
    }

    var totalRooms = 0;
    var details = [];
    for (var r = 0; r < rooms.length; r++) {
        var q = rooms[r].qty || 1;
        totalRooms += q;
        details.push(rooms[r].room_type_name + (q > 1 ? ' &times;' + q : ''));
    }

    html += '<div class="itin-summary"><div>';
    html += '<div class="itin-details">' + details.join(' + ') + ' &middot; ' + rooms[0].channel_name + '</div>';
    html += '<div class="itin-details" style="margin-top:4px;">' +
        formatDate(rooms[0].checkin) + ' &rarr; ' + formatDate(rooms[0].checkout) +
        ' (' + grandTotals.nights + ' night' + (grandTotals.nights > 1 ? 's' : '') +
        ', ' + totalRooms + ' room' + (totalRooms > 1 ? 's' : '') + ')</div>';
    html += '</div>';
    html += '<div class="itin-grand">' + fmtC(grandTotals.grand_total) + '</div></div>';

    html += '<div class="itin-actions">';
    html += '<button class="dl-btn" onclick="downloadQuote()">&#x2913; Download Quote</button>';
    html += '</div>';

    document.getElementById('itinResult').innerHTML = html;
}

function downloadQuote() {
    if (!lastQuoteData || !lastQuoteData.length) return;
    var w = window.open('', '_blank');
    var rooms = lastQuoteData;
    var meta = CFG.quoteMeta;

    var grandTotals = { room_total: 0, meal_total: 0, sc_total: 0, tax_total: 0, grand_total: 0, nights: 0 };
    var totalRooms = 0;
    var roomSections = '';

    for (var r = 0; r < rooms.length; r++) {
        var data = rooms[r];
        var qty = data.qty || 1;
        var t = data.totals;
        totalRooms += qty;
        grandTotals.nights = t.nights;
        grandTotals.room_total += t.room_total * qty;
        grandTotals.meal_total += t.meal_total * qty;
        grandTotals.sc_total += t.sc_total * qty;
        grandTotals.tax_total += t.tax_total * qty;
        grandTotals.grand_total += t.grand_total * qty;

        roomSections += '<div style="margin-top:' + (r > 0 ? '20px' : '0') + ';padding:8px 14px;background:#f0f9ff;border-radius:8px;border:1px solid #bfdbfe;font-size:13px;font-weight:700;color:#1e40af;">' +
            data.room_type_name + ' &mdash; ' + data.rate_plan_name +
            (qty > 1 ? ' <span style="color:#64748b;font-weight:400;">(&times;' + qty + ' rooms)</span>' : '') + '</div>';

        roomSections += '<table><thead><tr>' +
            '<th>Night</th><th>Season</th><th>Room Rate</th><th>Meal</th><th>Service Chg</th><th>Tax</th><th>Total</th>' +
            '</tr></thead><tbody>';

        for (var i = 0; i < data.nights.length; i++) {
            var n = data.nights[i];
            roomSections += '<tr>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;">' + n.date_display + '</td>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;">' + n.season + '</td>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmt(n.room_rate * qty) + '</td>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmt(n.meal * qty) + '</td>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmt(n.service_charge * qty) + '</td>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">' + fmt(n.tax * qty) + '</td>' +
                '<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:700;">' + fmt(n.final_rate * qty) + '</td>' +
                '</tr>';
        }
        roomSections += '<tr class="total-row">' +
            '<td colspan="2">Subtotal (' + t.nights + ' night' + (t.nights > 1 ? 's' : '') + (qty > 1 ? ' &times; ' + qty + ' rooms' : '') + ')</td>' +
            '<td>' + fmtC(t.room_total * qty) + '</td><td>' + fmtC(t.meal_total * qty) + '</td>' +
            '<td>' + fmtC(t.sc_total * qty) + '</td><td>' + fmtC(t.tax_total * qty) + '</td>' +
            '<td>' + fmtC(t.grand_total * qty) + '</td></tr></tbody></table>';
    }

    var details = [];
    for (var r = 0; r < rooms.length; r++) {
        var q = rooms[r].qty || 1;
        details.push(rooms[r].room_type_name + (q > 1 ? ' &times;' + q : ''));
    }

    var guestInfo = '<div class="guest-info">' +
        '<div class="gi"><strong>Rooms:</strong> ' + details.join(', ') + '</div>' +
        (meta.headerLabel ? '<div class="gi"><strong>' + meta.headerLabel + '</strong></div>' : '') +
        '<div class="gi"><strong>Check-in:</strong> ' + formatDate(rooms[0].checkin) + '</div>' +
        '<div class="gi"><strong>Check-out:</strong> ' + formatDate(rooms[0].checkout) + '</div>' +
        '<div class="gi"><strong>Nights:</strong> ' + grandTotals.nights + '</div>' +
        '<div class="gi"><strong>Total Rooms:</strong> ' + totalRooms + '</div>' +
        '</div>';

    var doc = '<!DOCTYPE html><html><head><meta charset="utf-8">' +
        '<title>Quotation - ' + meta.propName + '</title>' +
        '<style>' +
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:40px;color:#1e293b;font-size:14px;}' +
        '.header{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:28px 32px;border-radius:12px;margin-bottom:24px;}' +
        '.header h1{margin:0;font-size:22px;font-weight:800;}' +
        '.header .sub{font-size:13px;opacity:0.8;margin-top:4px;}' +
        '.header .title{font-size:18px;font-weight:800;text-align:right;}' +
        '.guest-info{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:20px;padding:16px 20px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;}' +
        '.guest-info .gi{font-size:13px;color:#64748b;}' +
        '.guest-info .gi strong{color:#1e293b;}' +
        'table{width:100%;border-collapse:collapse;margin-bottom:4px;}' +
        'th{background:#f8fafc;padding:10px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;border-bottom:2px solid #e2e8f0;text-align:right;}' +
        'th:first-child,th:nth-child(2){text-align:left;}' +
        '.total-row td{font-weight:700;font-size:14px;background:#f0f9ff;border-top:2px solid #bfdbfe;color:#1e40af;padding:10px 12px;text-align:right;}' +
        '.total-row td:first-child{text-align:left;}' +
        '.grand{margin-top:16px;padding:20px;background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);border-radius:10px;color:#fff;display:flex;justify-content:space-between;align-items:center;}' +
        '.grand .amount{font-size:28px;font-weight:800;}' +
        '.grand .details{font-size:13px;opacity:0.9;}' +
        '.terms{margin-top:24px;padding:16px 20px;border:1px solid #e2e8f0;border-radius:8px;font-size:12px;color:#64748b;}' +
        '.terms h3{margin:0 0 8px;font-size:13px;color:#1e293b;}' +
        '.terms ul{margin:0;padding-left:18px;line-height:1.8;}' +
        '.footer{margin-top:24px;text-align:center;font-size:11px;color:#94a3b8;}' +
        '@media print{body{padding:20px;}.header{-webkit-print-color-adjust:exact;print-color-adjust:exact;}.grand{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}' +
        '</style></head><body>' +
        '<div class="header"><div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
        '<div><h1>' + meta.propName + '</h1><p class="sub">' + meta.propLocation + '</p></div>' +
        '<div class="title">Quotation</div></div>' +
        (meta.headerLabel ? '<div style="margin-top:10px;font-size:13px;opacity:0.8;">' + meta.headerLabel + '</div>' : '') +
        '</div>' +
        guestInfo + roomSections +
        '<div class="grand"><div>' +
        '<div class="details">' + details.join(' + ') + '</div>' +
        '<div class="details" style="margin-top:4px;">' + formatDate(rooms[0].checkin) + ' &rarr; ' + formatDate(rooms[0].checkout) +
        ' (' + grandTotals.nights + ' night' + (grandTotals.nights > 1 ? 's' : '') + ', ' + totalRooms + ' room' + (totalRooms > 1 ? 's' : '') + ')</div>' +
        '</div><div class="amount">' + fmtC(grandTotals.grand_total) + '</div></div>' +
        '<div class="terms"><h3>Terms & Conditions</h3><ul>' +
        '<li>Rates are net non-commissionable.</li>' +
        '<li>All rates include ' + meta.scPct + '% service charge and ' + meta.taxPct + '% GST.</li>' +
        '<li>Subject to availability at the time of booking.</li>' +
        '<li>Check-in: 14:00 | Check-out: 12:00 (noon).</li>' +
        '<li>Cancellation: Free up to 14 days before arrival. Late cancellations subject to one night\'s charge.</li>' +
        '<li>No-show: Full stay will be charged.</li>' +
        '<li>All guests on tourist visa will be required to pay $6 Green Tax per person per night.</li>' +
        '</ul></div>' +
        '<div class="footer">Generated on ' + new Date().toLocaleString() + ' | ' + meta.propName + '</div>' +
        '</body></html>';

    w.document.write(doc);
    w.document.close();
    setTimeout(function() { w.print(); }, 300);
}
