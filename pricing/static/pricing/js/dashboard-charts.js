// ============================================================================
// 12-MONTH SNAPSHOT CHART (with projected occupancy line)
// ============================================================================
function initSnapshotChart(data, stlyOcc, projectedOcc, demandPct, cancelRates) {
    var ctx = document.getElementById('snapshotChart');
    if (!ctx) return;

    var demandSign = demandPct >= 0 ? '+' : '';
    var projLabel = 'Projected (STLY + per-month demand index)';

    var datasets = [
        {
            label: 'Revenue ($)',
            data: data.map(function(m) { return m.revenue; }),
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderRadius: 4,
            yAxisID: 'y',
            order: 4,
        },
        {
            label: 'OTB Occupancy (%)',
            data: data.map(function(m) { return m.occupancy; }),
            type: 'line',
            borderColor: 'rgb(34, 197, 94)',
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            borderWidth: 2,
            pointRadius: 4,
            pointBackgroundColor: 'rgb(34, 197, 94)',
            tension: 0.3,
            fill: false,
            yAxisID: 'y1',
            order: 1,
        },
        {
            label: projLabel,
            data: projectedOcc,
            type: 'line',
            borderColor: 'rgb(249, 115, 22)',
            borderWidth: 2,
            borderDash: [6, 3],
            pointRadius: 3,
            pointBackgroundColor: 'rgb(249, 115, 22)',
            pointStyle: 'triangle',
            tension: 0.3,
            fill: false,
            yAxisID: 'y1',
            order: 2,
        }
    ];

    // Cancel rate line (if data available)
    if (cancelRates && cancelRates.length > 0) {
        datasets.push({
            label: 'Cancel Rate (%)',
            data: cancelRates,
            type: 'line',
            borderColor: 'rgb(239, 68, 68)',
            borderWidth: 2,
            borderDash: [3, 3],
            pointRadius: 3,
            pointBackgroundColor: 'rgb(239, 68, 68)',
            pointStyle: 'rectRot',
            tension: 0.3,
            fill: false,
            yAxisID: 'y1',
            order: 3,
        });
    }

    var chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(function(m) { return m.month_name + ' ' + String(m.year).slice(2); }),
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { usePointStyle: true, padding: 16, font: { size: 11 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(0,0,0,0.8)',
                    padding: 12,
                    callbacks: {
                        label: function(ctx) {
                            var label = ctx.dataset.label || '';
                            var val = ctx.parsed.y;
                            if (label.indexOf('Projected') === 0 && val !== null) {
                                var idx = ctx.dataIndex;
                                var dp = data[idx] ? data[idx].demand_pct : null;
                                var driver = data[idx] ? (data[idx].demand_driver || '') : '';
                                var parts = ['Projected: ' + val.toFixed(1) + '%'];
                                if (dp !== null && dp !== undefined) {
                                    parts.push('Demand: ' + (dp > 0 ? '+' : '') + dp.toFixed(1) + '%');
                                }
                                if (driver) {
                                    parts.push('Driver: ' + driver);
                                }
                                return parts;
                            }
                            if (label === 'Cancel Rate (%)') {
                                return 'Cancel Rate: ' + val.toFixed(1) + '%';
                            }
                            if (ctx.dataset.yAxisID === 'y1') {
                                return label + ': ' + val.toFixed(1) + '%';
                            }
                            return 'Revenue: ' + window.DASHBOARD_CFG.currency + val.toLocaleString('en-US', {maximumFractionDigits: 0});
                        },
                        afterBody: function(tooltipItems) {
                            var idx = tooltipItems[0].dataIndex;
                            var snap = data[idx];
                            var lines = [];
                            if (snap.cancel_rate !== null && snap.cancel_rate !== undefined) {
                                lines.push('Cancel rate: ' + snap.cancel_rate + '%');
                            }
                            if (snap.net_occ !== null && snap.net_occ !== undefined) {
                                lines.push('Net forecast: ~' + snap.net_occ + '%');
                            }
                            if (snap.demand_pct !== null && snap.demand_pct !== undefined) {
                                lines.push('Demand: ' + (snap.demand_pct > 0 ? '+' : '') + snap.demand_pct.toFixed(1) + '%');
                            }
                            return lines;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    position: 'left',
                    ticks: {
                        callback: function(v) {
                            if (v >= 1000) return window.DASHBOARD_CFG.currency + (v / 1000).toFixed(0) + 'k';
                            return window.DASHBOARD_CFG.currency + v;
                        },
                        color: '#6b7280',
                        font: { size: 11 }
                    },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                y1: {
                    beginAtZero: true,
                    max: 100,
                    position: 'right',
                    ticks: {
                        callback: function(v) { return v + '%'; },
                        color: '#22c55e',
                        font: { size: 11 }
                    },
                    grid: { drawOnChartArea: false }
                },
                x: {
                    ticks: { color: '#6b7280', font: { size: 11 } },
                    grid: { display: false }
                }
            }
        }
    });

    // Click a month bar -> navigate to override calendar for that month
    ctx.onclick = function(evt) {
        var points = chart.getElementsAtEventForMode(evt, 'nearest', {intersect: true}, false);
        if (points.length > 0 && window.DASHBOARD_CFG.overrideCalendarUrl) {
            var idx = points[0].index;
            var monthData = data[idx];
            if (monthData && monthData.year && monthData.month) {
                var url = window.DASHBOARD_CFG.overrideCalendarUrl
                    + '?year=' + monthData.year + '&month=' + monthData.month;
                window.location.href = url;
            }
        }
    };

    // Show pointer cursor on hoverable bars
    ctx.onmousemove = function(evt) {
        var points = chart.getElementsAtEventForMode(evt, 'nearest', {intersect: true}, false);
        ctx.style.cursor = points.length > 0 ? 'pointer' : 'default';
    };
}

// ============================================================================
// OCCUPANCY CALENDAR (clickable days)
// ============================================================================
var occCalYear = null;
var occCalMonth = null;
var occCalPrev = null;
var occCalNext = null;

function loadOccupancyCalendar(year, month) {
    var url = window.DASHBOARD_CFG.occCalendarUrl
        + "?year=" + year + "&month=" + month;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                renderOccupancyCalendar(data);
            } else {
                document.getElementById('occ-cal-grid').innerHTML =
                    '<div class="text-center py-8 text-gray-500"><p>' +
                    (data.message || 'Unable to load calendar') + '</p></div>';
            }
        })
        .catch(function(err) {
            console.error('Occupancy calendar error:', err);
            document.getElementById('occ-cal-grid').innerHTML =
                '<div class="text-center py-8 text-gray-500"><p>Unable to load calendar data</p></div>';
        });
}

function renderOccupancyCalendar(data) {
    occCalYear = data.year;
    occCalMonth = data.month;
    occCalPrev = data.prev;
    occCalNext = data.next;

    // Update header
    document.getElementById('occ-cal-month-title').textContent = data.month_name;
    document.getElementById('occ-cal-subtitle').textContent =
        data.total_rooms + ' rooms' +
        (data.forecast_occupancy !== null ? ' \u2022 Forecast: ' + data.forecast_occupancy + '% occupancy' : '');

    var badge = document.getElementById('occ-cal-forecast-badge');
    if (data.forecast_occupancy !== null) {
        badge.textContent = 'Forecast: ' + data.forecast_occupancy + '%';
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }

    var html = '';
    var dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

    // Header row
    html += '<div class="grid grid-cols-7 bg-dash-metric border-b border-dash-divider">';
    for (var i = 0; i < 7; i++) {
        html += '<div class="px-1 py-2 text-center text-dash-xs font-semibold text-dash-hint uppercase">' + dayNames[i] + '</div>';
    }
    html += '</div>';

    // Find weekday of the 1st
    var firstDateStr = data.year + '-' + String(data.month).padStart(2, '0') + '-01';
    var firstDayData = data.days[firstDateStr];
    var startWeekday = firstDayData ? firstDayData.weekday : 0;

    var dateKeys = Object.keys(data.days).sort();

    html += '<div class="grid grid-cols-7 gap-px bg-dash-border">';

    // Empty cells before first day
    for (var i = 0; i < startWeekday; i++) {
        html += '<div class="bg-dash-subtle min-h-dash-day sm:min-h-[72px]"></div>';
    }

    // Day cells — clickable, linking to rate lookup
    var rateLookupBase = window.DASHBOARD_CFG.rateLookupBaseUrl || '';
    for (var d = 0; d < dateKeys.length; d++) {
        var dateStr = dateKeys[d];
        var day = data.days[dateStr];
        var occ = day.occupancy_percent;

        // Color (red=low, green=high)
        var barColor;
        if (occ >= 100) barColor = '#15803d';
        else if (occ >= 80) barColor = '#22c55e';
        else if (occ >= 50) barColor = '#f59e0b';
        else barColor = '#ef4444';

        var cellClass = day.is_today ? 'ring-2 ring-inset ring-blue-500 bg-blue-50' : 'bg-dash-card';
        if (day.is_past) cellClass += ' opacity-60';

        var clickHandler = rateLookupBase ? ' onclick="window.location.href=\'' + rateLookupBase + '?date=' + dateStr + '\'"' : '';

        html += '<div class="' + cellClass + ' min-h-dash-day sm:min-h-[72px] p-0.5 flex flex-col relative group cursor-pointer"' + clickHandler + '>';

        // Day number
        if (day.is_today) {
            html += '<div class="flex items-center justify-center w-5 h-5 rounded-full bg-blue-600 text-white text-dash-xs font-bold mb-0.5">' + day.day + '</div>';
        } else {
            html += '<div class="text-dash-sm font-semibold text-dash-primary mb-0.5">' + day.day + '</div>';
        }

        // Season name (desktop)
        if (day.season_name) {
            html += '<div class="hidden sm:block text-dash-xxs text-dash-hint truncate leading-tight" title="' + day.season_name + '">' + day.season_name + '</div>';
        }

        // Spacer
        html += '<div class="mt-auto">';

        // Rooms fraction
        html += '<div class="text-dash-xs text-dash-hint">' + day.rooms_occupied + '/' + day.total_rooms + '</div>';

        // Occupancy bar (3px, rounded-dash-bar)
        html += '<div class="h-[3px] bg-dash-border rounded-dash-bar mt-0.5 overflow-hidden">';
        html += '<div class="h-full rounded-dash-bar transition-all" style="width:' + Math.min(occ, 100) + '%;background:' + barColor + '"></div>';
        html += '</div>';

        // Percent (desktop)
        html += '<div class="hidden sm:block text-dash-xxs text-dash-hint text-right mt-0.5">' + occ + '%</div>';

        // Group allotment indicator
        if (day.allotments && day.allotments.length > 0) {
            for (var ai = 0; ai < day.allotments.length; ai++) {
                var allot = day.allotments[ai];
                var allotColor = allot.status === 'confirmed' ? 'bg-allotment' : 'bg-allotment/50';
                html += '<div class="hidden sm:flex items-center gap-0.5 mt-0.5">';
                html += '<span class="inline-block w-1.5 h-1.5 rounded-full ' + allotColor + ' flex-shrink-0"></span>';
                html += '<span class="text-dash-xxs text-allotment truncate leading-tight">' + allot.name + '</span>';
                html += '</div>';
            }
        }

        html += '</div>'; // mt-auto

        // Tooltip
        html += '<div class="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-2 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 whitespace-nowrap z-50 pointer-events-none shadow-lg">';
        html += '<div class="font-semibold">' + dateStr + '</div>';
        html += '<div>Rooms: ' + day.rooms_occupied + ' / ' + day.total_rooms + '</div>';
        html += '<div>Occupancy: ' + occ + '%</div>';
        if (day.season_name) html += '<div>Season: ' + day.season_name + '</div>';
        if (day.allotments && day.allotments.length > 0) {
            for (var ai = 0; ai < day.allotments.length; ai++) {
                var allot = day.allotments[ai];
                html += '<div class="text-purple-300">Group: ' + allot.name + ' (' + allot.picked_up + '/' + allot.rooms + ' rooms)</div>';
            }
        }
        html += '<div class="absolute top-full left-1/2 -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900"></div>';
        html += '</div>';

        html += '</div>'; // day cell
    }

    // Trailing empty cells
    var lastDateStr = dateKeys[dateKeys.length - 1];
    var lastWeekday = data.days[lastDateStr].weekday;
    for (var i = lastWeekday + 1; i < 7; i++) {
        html += '<div class="bg-dash-subtle min-h-dash-day sm:min-h-[72px]"></div>';
    }

    html += '</div>';

    document.getElementById('occ-cal-grid').innerHTML = html;
}

function navigateOccCal(direction) {
    var target = direction === 'prev' ? occCalPrev : occCalNext;
    if (target) {
        loadOccupancyCalendar(target.year, target.month);
    }
}

// ============================================================================
// BOOKING HEATMAP (NEW)
// ============================================================================
function loadBookingHeatmap() {
    var url = window.DASHBOARD_CFG.bookingHeatmapUrl;
    if (!url) return;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success || data.booking_months.length === 0) {
                document.getElementById('booking-heatmap-card').style.display = 'none';
                return;
            }
            renderBookingHeatmap(data);
        })
        .catch(function(err) {
            console.error('Booking heatmap error:', err);
            document.getElementById('booking-heatmap-card').style.display = 'none';
        });
}

function renderBookingHeatmap(data) {
    var MONTHS_SHORT = {'01':'Jan','02':'Feb','03':'Mar','04':'Apr','05':'May','06':'Jun',
                        '07':'Jul','08':'Aug','09':'Sep','10':'Oct','11':'Nov','12':'Dec'};
    function fmtMonth(ym) {
        var parts = ym.split('-');
        return MONTHS_SHORT[parts[1]] + ' ' + parts[0].slice(2);
    }
    function fmtShort(ym) {
        return MONTHS_SHORT[ym.split('-')[1]];
    }
    function getIntensity(rn, maxRn) {
        if (rn === 0) return 'transparent';
        var pct = rn / maxRn * 100;
        if (pct >= 60) return '#1e3a8a';   // heat-5
        if (pct >= 35) return '#2563eb';   // heat-4
        if (pct >= 15) return '#60a5fa';   // heat-3
        if (pct >= 5)  return '#bfdbfe';   // heat-2
        return '#eff6ff';                   // heat-1
    }
    function textColor(bg) {
        return (bg === '#1e3a8a' || bg === '#2563eb' || bg === '#60a5fa') ? '#fff' : '#1e3a8a';
    }

    var bms = data.booking_months;
    var ams = data.arrival_months;
    var matrix = data.matrix;
    var maxRn = data.max_rn || 1;

    var originUrl = window.DASHBOARD_CFG.bookingOriginUrl || '#';

    var html = '<div class="px-5 py-3 border-b border-dash-inner">';
    html += '<div class="flex items-center justify-between">';
    html += '<div>';
    html += '<h2 class="text-dash-lg font-semibold text-dash-primary">Booking heatmap</h2>';
    html += '<p class="text-dash-base text-dash-hint mt-0.5">Last 3 booking months \u2192 future arrival months (room nights)</p>';
    html += '</div>';
    html += '<a href="' + originUrl + '" class="text-dash-base text-action">Full matrix \u2192</a>';
    html += '</div></div>';

    html += '<div class="px-5 py-3"><div class="overflow-x-auto">';
    html += '<table class="w-full border-collapse text-dash-base">';

    // Header row
    html += '<thead><tr>';
    html += '<th class="text-left px-2 py-1.5 text-dash-xs font-semibold text-dash-muted uppercase tracking-wider border-b-dash-heavy border-dash-divider bg-dash-metric">Booked \u2193</th>';
    for (var ai = 0; ai < ams.length; ai++) {
        html += '<th class="text-center px-1 py-1.5 text-dash-xs font-semibold text-dash-muted uppercase border-b-dash-heavy border-dash-divider" style="min-width:48px">' + fmtShort(ams[ai]) + '</th>';
    }
    html += '<th class="text-center px-1 py-1.5 text-dash-xs font-semibold text-dash-primary uppercase border-b-dash-heavy border-dash-divider bg-dash-metric">Total</th>';
    html += '</tr></thead>';

    // Data rows
    html += '<tbody>';
    for (var bi = 0; bi < bms.length; bi++) {
        var bm = bms[bi];
        var isNow = bm === data.current_month;
        html += '<tr>';
        html += '<td class="px-2 py-1.5 font-semibold text-dash-sm text-dash-primary border-b border-dash-inner">';
        html += fmtMonth(bm);
        if (isNow) html += ' <span class="text-dash-xxs text-status-blue font-medium">now</span>';
        html += '</td>';

        for (var ai = 0; ai < ams.length; ai++) {
            var am = ams[ai];
            var rn = (matrix[bm] || {})[am] || 0;
            html += '<td class="text-center p-0.5 border-b border-dash-inner">';
            if (rn > 0) {
                var bg = getIntensity(rn, maxRn);
                var tc = textColor(bg);
                html += '<div class="p-1 rounded-dash-cell font-medium text-dash-base text-center" style="background:' + bg + '; color:' + tc + ';">' + rn + '</div>';
            }
            html += '</td>';
        }

        var rowTotal = data.booking_totals[bm] || 0;
        html += '<td class="text-center py-1.5 font-semibold text-dash-sm text-dash-primary border-b border-dash-inner bg-dash-metric">' + rowTotal + '</td>';
        html += '</tr>';
    }

    // Arrival totals row
    html += '<tr>';
    html += '<td class="px-2 py-1.5 font-semibold text-dash-xs text-dash-muted uppercase bg-dash-metric">Arrival total</td>';
    var grandTotal = 0;
    for (var ai = 0; ai < ams.length; ai++) {
        var at = data.arrival_totals[ams[ai]] || 0;
        grandTotal += at;
        html += '<td class="text-center py-1.5 font-semibold text-dash-sm text-dash-primary bg-dash-metric">' + at + '</td>';
    }
    html += '<td class="text-center py-1.5 font-bold text-dash-sm text-dash-primary bg-dash-subtle">' + grandTotal + '</td>';
    html += '</tr></tbody></table></div>';

    // Reading hint
    html += '<p class="text-dash-sm text-dash-hint mt-1.5">Across \u2192 when bookings land. Down \u2193 where arrivals came from.</p>';
    html += '</div>';

    document.getElementById('booking-heatmap-card').innerHTML = html;
}

// ============================================================================
// PICKUP + ARRIVALS CARD (NEW — replaces Market Intelligence)
// ============================================================================
function loadPickupArrivals() {
    var url = window.DASHBOARD_CFG.pickupArrivalsUrl;
    if (!url) return;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success || !data.has_data) {
                document.getElementById('pickup-arrivals-card').innerHTML =
                    '<div class="px-5 py-6 text-center text-dash-md text-dash-secondary">No pickup data available</div>';
                return;
            }
            renderPickupArrivals(data);
        })
        .catch(function(err) {
            console.error('Pickup arrivals error:', err);
            document.getElementById('pickup-arrivals-card').innerHTML =
                '<div class="px-5 py-6 text-center text-dash-md text-dash-secondary">Unable to load pickup data</div>';
        });
}

function renderPickupArrivals(data) {
    var pickupUrl = window.DASHBOARD_CFG.pickupDashboardUrl || '#';

    var html = '<div class="px-5 py-3 border-b border-dash-inner">';
    html += '<h2 class="text-dash-md font-semibold text-dash-primary">Next 3 months \u2014 pace & arrivals</h2>';
    html += '</div>';
    html += '<div class="px-5 py-2">';

    for (var i = 0; i < data.forecasts.length; i++) {
        var f = data.forecasts[i];
        var isLast = i === data.forecasts.length - 1;
        var borderStyle = isLast ? '' : 'border-bottom: 0.5px solid #f1f5f9;';

        html += '<div style="padding: 4px 0; ' + borderStyle + '">';

        // Line 1: month, OTB, vs STLY
        html += '<div class="flex items-center justify-between">';
        html += '<span class="text-dash-base font-semibold text-dash-primary">' + f.month_name.slice(0, 3) + '</span>';
        html += '<span class="text-dash-base font-semibold text-dash-primary">' + f.forecast_occupancy + '% OTB</span>';

        if (f.vs_stly !== null && f.vs_stly !== undefined) {
            var stlyClass = f.vs_stly >= 0 ? 'text-status-green' : 'text-status-red';
            var stlyArrow = f.vs_stly >= 0 ? '\u25b2' : '\u25bc';
            var warn = f.vs_stly < -10 ? ' \u26a0' : '';
            html += '<span class="text-dash-sm font-medium ' + stlyClass + '">' + stlyArrow + ' ' + (f.vs_stly >= 0 ? '+' : '') + f.vs_stly + '%' + warn + '</span>';
        } else {
            html += '<span class="text-dash-sm text-dash-hint">\u2014 no STLY</span>';
        }
        html += '</div>';

        // Line 2: arrival trend + market mover pills
        if (f.arrival_has_data && f.arrival_pct !== null) {
            html += '<div class="flex items-center gap-1 mt-0.5 flex-wrap">';
            html += '<span class="text-dash-xs text-dash-hint">Arrivals</span>';
            var arrClass = f.arrival_pct >= 0 ? 'text-status-green' : 'text-status-red';
            var arrArrow = f.arrival_pct >= 0 ? '\u25b2' : '\u25bc';
            html += '<span class="text-dash-xs font-medium ' + arrClass + '">' + arrArrow + ' ' + (f.arrival_pct >= 0 ? '+' : '') + Math.round(f.arrival_pct) + '%</span>';

            // Top mover pills
            if (f.top_movers) {
                for (var mi = 0; mi < Math.min(f.top_movers.length, 3); mi++) {
                    var m = f.top_movers[mi];
                    var yoy = m.country_yoy || 0;
                    var pillBg, pillText;
                    if (yoy >= 5) { pillBg = 'bg-status-green-bg'; pillText = 'text-status-green-dark'; }
                    else if (yoy >= -5) { pillBg = 'bg-status-amber-bg'; pillText = 'text-status-amber-dark'; }
                    else { pillBg = 'bg-status-red-bg'; pillText = 'text-status-red-dark'; }
                    var label = (m.country || '').slice(0, 3) + ' ' + (yoy >= 0 ? '+' : '') + Math.round(yoy);
                    html += '<span class="text-dash-xs font-medium px-1.5 py-px rounded-lg ' + pillBg + ' ' + pillText + '">' + label + '</span>';
                }
            }
            html += '</div>';
        }

        html += '</div>';
    }

    // Velocity
    if (data.velocity && data.velocity.per_day > 0) {
        html += '<div class="text-dash-sm text-dash-hint mt-1.5 pt-1.5 border-t border-dash-inner">';
        html += 'Velocity: ' + data.velocity.per_day.toFixed(1) + ' bookings/day';
        if (data.velocity.delta) {
            html += ' (' + (data.velocity.delta >= 0 ? '\u2191' : '\u2193') + ' ' + Math.abs(data.velocity.delta).toFixed(1) + ')';
        }
        html += '</div>';
    }

    html += '<a href="' + pickupUrl + '" class="text-dash-sm text-action mt-1 inline-block">View full forecast \u2192</a>';
    html += '</div>';

    document.getElementById('pickup-arrivals-card').innerHTML = html;
}

// ============================================================================
// INIT
// ============================================================================
document.addEventListener('DOMContentLoaded', function() {
    loadOccupancyCalendar(window.DASHBOARD_CFG.todayYear, window.DASHBOARD_CFG.todayMonth);
    loadBookingHeatmap();
    loadPickupArrivals();

    // Init snapshot chart if config data is available
    if (window.DASHBOARD_CFG.snapshotData) {
        initSnapshotChart(
            window.DASHBOARD_CFG.snapshotData,
            window.DASHBOARD_CFG.stlyOcc,
            window.DASHBOARD_CFG.projectedOcc,
            window.DASHBOARD_CFG.demandPct,
            window.DASHBOARD_CFG.cancelRates || []
        );
    }
});
