// ============================================================================
// 12-MONTH SNAPSHOT CHART (with projected occupancy line)
// ============================================================================
function initSnapshotChart(data, stlyOcc, projectedOcc, demandPct) {
    var ctx = document.getElementById('snapshotChart');
    if (!ctx) return;

    var demandSign = demandPct >= 0 ? '+' : '';
    var projLabel = 'Projected (STLY + per-month demand index)';

    var chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(function(m) { return m.month_name + ' ' + String(m.year).slice(2); }),
            datasets: [
                {
                    label: 'Revenue ($)',
                    data: data.map(function(m) { return m.revenue; }),
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                    borderRadius: 4,
                    yAxisID: 'y',
                    order: 3,
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
            ]
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
                            if (ctx.dataset.yAxisID === 'y1') {
                                return label + ': ' + val.toFixed(1) + '%';
                            }
                            return 'Revenue: ' + window.DASHBOARD_CFG.currency + val.toLocaleString('en-US', {maximumFractionDigits: 0});
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

    // Click a month bar → navigate to override calendar for that month
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
// OCCUPANCY CALENDAR
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
    html += '<div class="grid grid-cols-7 bg-gray-50 border-b border-gray-200">';
    for (var i = 0; i < 7; i++) {
        html += '<div class="px-1 py-2 text-center text-xs font-semibold text-gray-500 uppercase">' + dayNames[i] + '</div>';
    }
    html += '</div>';

    // Find weekday of the 1st
    var firstDateStr = data.year + '-' + String(data.month).padStart(2, '0') + '-01';
    var firstDayData = data.days[firstDateStr];
    var startWeekday = firstDayData ? firstDayData.weekday : 0;

    var dateKeys = Object.keys(data.days).sort();

    html += '<div class="grid grid-cols-7 gap-px bg-gray-200">';

    // Empty cells before first day
    for (var i = 0; i < startWeekday; i++) {
        html += '<div class="bg-gray-50 min-h-[72px] sm:min-h-[92px]"></div>';
    }

    // Day cells
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

        var cellClass = day.is_today ? 'ring-2 ring-inset ring-blue-500 bg-blue-50' : 'bg-white';
        if (day.is_past) cellClass += ' opacity-60';

        html += '<div class="' + cellClass + ' min-h-[72px] sm:min-h-[92px] p-1.5 sm:p-2 flex flex-col relative group">';

        // Day number
        if (day.is_today) {
            html += '<div class="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold mb-0.5">' + day.day + '</div>';
        } else {
            html += '<div class="text-xs sm:text-sm font-semibold text-gray-700 mb-0.5">' + day.day + '</div>';
        }

        // Season name (desktop)
        if (day.season_name) {
            html += '<div class="hidden sm:block text-[9px] text-gray-400 truncate leading-tight" title="' + day.season_name + '">' + day.season_name + '</div>';
        }

        // Spacer
        html += '<div class="mt-auto">';

        // Rooms fraction
        html += '<div class="text-[10px] sm:text-xs font-medium text-gray-600">' + day.rooms_occupied + '/' + day.total_rooms + '</div>';

        // Occupancy bar
        html += '<div class="mt-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">';
        html += '<div class="h-full rounded-full transition-all" style="width:' + Math.min(occ, 100) + '%;background:' + barColor + '"></div>';
        html += '</div>';

        // Percent (desktop)
        html += '<div class="hidden sm:block text-[9px] text-gray-500 text-right mt-0.5">' + occ + '%</div>';

        // Group allotment indicator
        if (day.allotments && day.allotments.length > 0) {
            for (var ai = 0; ai < day.allotments.length; ai++) {
                var allot = day.allotments[ai];
                var allotColor = allot.status === 'confirmed' ? 'bg-purple-500' : 'bg-purple-300';
                html += '<div class="hidden sm:flex items-center gap-0.5 mt-0.5">';
                html += '<span class="inline-block w-1.5 h-1.5 rounded-full ' + allotColor + ' flex-shrink-0"></span>';
                html += '<span class="text-[8px] text-purple-700 truncate leading-tight">' + allot.name + '</span>';
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
        html += '<div class="bg-gray-50 min-h-[72px] sm:min-h-[92px]"></div>';
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
// MARKET CONTEXT + DEMAND INDEX (condensed)
// ============================================================================
function loadMarketContext() {
    var url = window.DASHBOARD_CFG.marketContextUrl;

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById('market-context-content');
            if (!data.has_data) {
                el.innerHTML =
                    '<div class="text-center py-6">' +
                        '<svg class="mx-auto h-10 w-10 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
                            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>' +
                        '</svg>' +
                        '<p class="mt-2 text-sm text-gray-500">No market data available</p>' +
                        '<p class="text-xs text-gray-400">Import a MoT report to see market context</p>' +
                    '</div>';
                return;
            }

            document.getElementById('market-ctx-period').textContent = data.period_label;

            var html = '<div class="space-y-3">';

            // Compact KPI row
            html += '<div class="grid grid-cols-2 gap-3">';

            // Arrivals
            html += '<div class="bg-blue-50 rounded-lg p-3">';
            html += '<p class="text-xs font-medium text-blue-600 uppercase">Arrivals</p>';
            html += '<p class="text-lg font-bold text-gray-900">' + Number(data.total_arrivals).toLocaleString() + '</p>';
            if (data.yoy_arrivals_pct !== null) {
                var arrColor = data.yoy_arrivals_pct >= 0 ? 'text-green-600' : 'text-red-600';
                var arrArrow = data.yoy_arrivals_pct >= 0 ? '\u2191' : '\u2193';
                html += '<p class="text-xs ' + arrColor + '">' + arrArrow + ' ' + Math.abs(data.yoy_arrivals_pct) + '% YoY</p>';
            }
            html += '</div>';

            // Occupancy
            html += '<div class="bg-green-50 rounded-lg p-3">';
            html += '<p class="text-xs font-medium text-green-600 uppercase">Mkt Occupancy</p>';
            html += '<p class="text-lg font-bold text-gray-900">' + (data.occupancy_rate !== null ? data.occupancy_rate.toFixed(1) + '%' : '\u2014') + '</p>';
            if (data.yoy_occupancy_pp !== null) {
                var occColor = data.yoy_occupancy_pp >= 0 ? 'text-green-600' : 'text-red-600';
                var occArrow = data.yoy_occupancy_pp >= 0 ? '\u2191' : '\u2193';
                html += '<p class="text-xs ' + occColor + '">' + occArrow + ' ' + Math.abs(data.yoy_occupancy_pp) + 'pp YoY</p>';
            }
            html += '</div>';

            html += '</div>'; // grid

            // Property vs Market comparison (condensed -- top 5)
            if (data.comparison && data.comparison.length > 0) {
                html += '<div class="border-t border-gray-100 pt-3 mt-3">';
                html += '<p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Your Markets vs National</p>';
                html += '<table class="w-full text-xs">';
                html += '<thead><tr class="text-gray-400 uppercase">';
                html += '<th class="text-left py-1 font-medium">Market</th>';
                html += '<th class="text-right py-1 font-medium">National</th>';
                html += '<th class="text-right py-1 font-medium">Yours</th>';
                html += '<th class="text-right py-1 font-medium">Gap</th>';
                html += '</tr></thead><tbody>';

                var maxShow = Math.min(data.comparison.length, 5);
                for (var i = 0; i < maxShow; i++) {
                    var c = data.comparison[i];
                    var gapColor = 'text-gray-400';
                    var gapText = (c.gap >= 0 ? '+' : '') + c.gap.toFixed(1) + 'pp';

                    if (c.gap > 2) {
                        gapColor = 'text-blue-600 font-semibold';
                    } else if (c.gap < -2) {
                        gapColor = 'text-amber-600 font-semibold';
                    }

                    html += '<tr class="border-b border-gray-50">';
                    html += '<td class="py-1.5 text-gray-700">' + c.country + '</td>';
                    html += '<td class="py-1.5 text-right text-gray-500">' + c.national_share.toFixed(1) + '%</td>';
                    html += '<td class="py-1.5 text-right text-gray-700 font-medium">' + c.prop_share.toFixed(1) + '%</td>';
                    html += '<td class="py-1.5 text-right ' + gapColor + '">' + gapText + '</td>';
                    html += '</tr>';
                }

                html += '</tbody></table>';

                html += '<div class="flex items-center gap-3 mt-2 text-xs text-gray-400">';
                html += '<span class="flex items-center"><span class="w-1.5 h-1.5 rounded-full bg-blue-500 mr-1"></span>Over-indexed</span>';
                html += '<span class="flex items-center"><span class="w-1.5 h-1.5 rounded-full bg-amber-500 mr-1"></span>Opportunity</span>';
                html += '</div>';
                html += '</div>';

            } else if (data.top_markets && data.top_markets.length > 0) {
                // Fallback: top markets without comparison
                html += '<div class="border-t border-gray-100 pt-3 mt-3">';
                html += '<p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Top Source Markets</p>';
                var maxMkt = Math.min(data.top_markets.length, 5);
                for (var i = 0; i < maxMkt; i++) {
                    var m = data.top_markets[i];
                    html += '<div class="flex items-center justify-between py-1">';
                    html += '<span class="text-sm text-gray-700">' + m.origin_country + '</span>';
                    html += '<div class="text-right">';
                    html += '<span class="text-sm font-medium text-gray-900">' + Number(m.arrivals).toLocaleString() + '</span>';
                    if (m.yoy_change_pct !== null) {
                        var mktColor = parseFloat(m.yoy_change_pct) >= 0 ? 'text-green-600' : 'text-red-600';
                        html += ' <span class="text-xs ' + mktColor + '">(' + (parseFloat(m.yoy_change_pct) >= 0 ? '+' : '') + parseFloat(m.yoy_change_pct).toFixed(1) + '%)</span>';
                    }
                    html += '</div>';
                    html += '</div>';
                }
                html += '</div>';
            }

            // --- Demand Index (expandable breakdown) ---
            if (data.demand_index && data.demand_index.backward.has_data) {
                var di = data.demand_index.backward;
                var diSign = di.pct >= 0 ? '+' : '';
                var natSign = di.national_pct >= 0 ? '+' : '';
                var diColor = di.pct >= 0 ? 'text-green-600' : 'text-red-600';

                html += '<div class="mt-4 pt-4 border-t border-gray-200">';
                html += '<div class="flex items-center justify-between mb-2">';
                html += '<h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Property Demand Index</h4>';
                html += '<button onclick="toggleDemandDetail()" class="text-xs text-blue-600 hover:underline" id="demand-toggle-btn">details</button>';
                html += '</div>';

                // Headline
                html += '<div class="flex items-baseline gap-3">';
                html += '<span class="text-2xl font-bold ' + diColor + '">' + diSign + di.pct.toFixed(1) + '%</span>';
                html += '<span class="text-sm text-gray-500">vs national ' + natSign + di.national_pct.toFixed(1) + '%</span>';
                html += '</div>';

                // Expandable detail
                html += '<div id="demand-detail" class="hidden mt-3">';
                html += '<table class="min-w-full text-xs">';
                html += '<thead><tr class="text-gray-500">';
                html += '<th class="text-left py-1">Market</th>';
                html += '<th class="text-right py-1">Share</th>';
                html += '<th class="text-right py-1">MoT YoY</th>';
                html += '<th class="text-right py-1">Impact</th>';
                html += '</tr></thead><tbody>';

                var maxComp = Math.min(di.components.length, 10);
                for (var ci = 0; ci < maxComp; ci++) {
                    var comp = di.components[ci];
                    var yoySign = comp.country_yoy >= 0 ? '+' : '';
                    var yoyColor = comp.country_yoy >= 0 ? 'text-green-600' : 'text-red-600';
                    var impact = (comp.prop_share / 100) * comp.country_yoy;
                    var impactSign = impact >= 0 ? '+' : '';
                    var impactColor = impact >= 0 ? 'text-green-600' : 'text-red-600';

                    html += '<tr class="border-t border-gray-100">';
                    html += '<td class="py-1 text-gray-900">' + comp.country + '</td>';
                    html += '<td class="py-1 text-right text-gray-600">' + comp.prop_share.toFixed(1) + '%</td>';
                    html += '<td class="py-1 text-right ' + yoyColor + '">' + yoySign + comp.country_yoy.toFixed(1) + '%</td>';
                    html += '<td class="py-1 text-right ' + impactColor + '">' + impactSign + impact.toFixed(1) + '%</td>';
                    html += '</tr>';
                }

                html += '</tbody></table>';
                html += '<p class="mt-2 text-xs text-gray-400">Based on ' + di.components.length + ' source markets</p>';
                html += '</div></div>';
            }

            // Source
            if (data.source_report) {
                html += '<p class="text-xs text-gray-400 mt-2 pt-2 border-t border-gray-100">' + data.source_report + '</p>';
            }

            html += '</div>';
            el.innerHTML = html;
        })
        .catch(function(err) {
            console.error('Market context error:', err);
            document.getElementById('market-context-content').innerHTML =
                '<div class="text-center py-6 text-gray-500"><p class="text-sm">Unable to load market data</p></div>';
        });
}

function toggleDemandDetail() {
    var el = document.getElementById('demand-detail');
    if (el) el.classList.toggle('hidden');
}

// ============================================================================
// INIT
// ============================================================================
document.addEventListener('DOMContentLoaded', function() {
    loadMarketContext();
    loadOccupancyCalendar(window.DASHBOARD_CFG.todayYear, window.DASHBOARD_CFG.todayMonth);

    // Init snapshot chart if config data is available
    if (window.DASHBOARD_CFG.snapshotData) {
        initSnapshotChart(
            window.DASHBOARD_CFG.snapshotData,
            window.DASHBOARD_CFG.stlyOcc,
            window.DASHBOARD_CFG.projectedOcc,
            window.DASHBOARD_CFG.demandPct
        );
    }
});
