// Chart data from Django (passed via window.PICKUP_CFG)
var chartData = window.PICKUP_CFG.chartData;

var CURRENCY = window.PICKUP_CFG.currency;

// Chart instances
var bookingPaceChart, leadTimeChart, channelChart, velocityChart, pickupCurvesChart;

// Color definitions
var chartColors = {
    red: 'rgba(239, 68, 68, 0.8)',
    orange: 'rgba(249, 115, 22, 0.8)',
    yellow: 'rgba(234, 179, 8, 0.8)',
    green: 'rgba(34, 197, 94, 0.8)',
    blue: 'rgba(59, 130, 246, 0.8)',
    purple: 'rgba(168, 85, 247, 0.8)',
    gray: 'rgba(156, 163, 175, 0.8)'
};

function initCharts() {
    initBookingPaceChart();
    initLeadTimeChart();
    initChannelChart();
    initVelocityChart();
    initPickupCurvesChart();
}

function initBookingPaceChart() {
    var ctx = document.getElementById('bookingPaceChart');
    if (!ctx || !chartData.bookingPace) return;

    if (bookingPaceChart) bookingPaceChart.destroy();

    var data = chartData.bookingPace;

    bookingPaceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: [
                {
                    label: 'Room Nights',
                    data: data.cum_nights,
                    borderColor: 'rgb(59, 130, 246)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y'
                },
                {
                    label: 'Revenue ($)',
                    data: data.cum_revenue,
                    borderColor: 'rgb(34, 197, 94)',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y1'
                },
                {
                    label: 'STLY Room Nights',
                    data: data.stly_nights,
                    borderColor: 'rgb(156, 163, 175)',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.3,
                    yAxisID: 'y'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            if (context.dataset.label === 'Revenue ($)') {
                                return 'Revenue: ' + CURRENCY + context.parsed.y.toLocaleString();
                            }
                            return context.dataset.label + ': ' + context.parsed.y;
                        }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear',
                    position: 'left',
                    beginAtZero: true,
                    title: { display: true, text: 'Room Nights' },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    beginAtZero: true,
                    title: { display: true, text: 'Revenue ($)' },
                    grid: { display: false },
                    ticks: {
                        callback: function(value) {
                            return CURRENCY + (value / 1000).toFixed(0) + 'k';
                        }
                    }
                },
                x: { grid: { display: false } }
            }
        }
    });
}

function initLeadTimeChart() {
    var ctx = document.getElementById('leadTimeChart');
    if (!ctx || !chartData.leadTime) return;

    if (leadTimeChart) leadTimeChart.destroy();

    var data = chartData.leadTime;
    var colorMap = [chartColors.red, chartColors.orange, chartColors.yellow, chartColors.green, chartColors.blue, chartColors.purple];

    leadTimeChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Bookings',
                data: data.counts,
                backgroundColor: colorMap,
                borderRadius: 4,
                barThickness: 24
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: function(context) {
                            var idx = context.dataIndex;
                            return 'Revenue: ' + CURRENCY + data.revenue[idx].toLocaleString();
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                y: { grid: { display: false } }
            }
        }
    });
}

function initChannelChart() {
    var ctx = document.getElementById('channelChart');
    if (!ctx || !chartData.channels) return;

    if (channelChart) channelChart.destroy();

    var data = chartData.channels;
    var colorList = [chartColors.blue, chartColors.green, chartColors.purple, chartColors.orange, chartColors.red, chartColors.gray];

    channelChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.labels,
            datasets: [{
                data: data.data,
                backgroundColor: colorList.slice(0, data.labels.length),
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: { legend: { display: false } }
        }
    });
}

function initVelocityChart() {
    var ctx = document.getElementById('velocityChart');
    if (!ctx || !chartData.dailyVelocity) return;

    if (velocityChart) velocityChart.destroy();

    var data = chartData.dailyVelocity;

    velocityChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.dates,
            datasets: [
                {
                    label: 'Daily Bookings',
                    data: data.bookings,
                    backgroundColor: 'rgba(59, 130, 246, 0.8)',
                    borderRadius: 4,
                    yAxisID: 'y'
                },
                {
                    label: 'Daily Revenue',
                    data: data.revenue,
                    type: 'line',
                    borderColor: 'rgb(34, 197, 94)',
                    borderWidth: 2,
                    pointRadius: 4,
                    pointBackgroundColor: 'rgb(34, 197, 94)',
                    tension: 0.3,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            if (context.dataset.label === 'Daily Revenue') {
                                return 'Revenue: ' + CURRENCY + context.parsed.y.toLocaleString();
                            }
                            return 'Bookings: ' + context.parsed.y;
                        }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear',
                    position: 'left',
                    beginAtZero: true,
                    title: { display: true, text: 'Bookings' },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    beginAtZero: true,
                    title: { display: true, text: 'Revenue ($)' },
                    grid: { display: false },
                    ticks: {
                        callback: function(value) {
                            return CURRENCY + (value / 1000).toFixed(1) + 'k';
                        }
                    }
                },
                x: { grid: { display: false } }
            }
        }
    });
}

function initPickupCurvesChart() {
    var ctx = document.getElementById('pickupCurvesChart');
    if (!ctx || !chartData.pickupCurves) return;

    if (pickupCurvesChart) pickupCurvesChart.destroy();

    var data = chartData.pickupCurves;
    var series = data.series || {};

    // Color map for season types
    var seasonColors = {
        peak: 'rgb(239, 68, 68)',
        shoulder: 'rgb(59, 130, 246)',
        low: 'rgb(156, 163, 175)'
    };

    // Build datasets dynamically from available season types
    var datasets = [];
    var typeOrder = ['peak', 'shoulder', 'low'];
    typeOrder.forEach(function(st) {
        if (series[st] && series[st].length > 0) {
            var color = seasonColors[st] || 'rgb(107, 114, 128)';
            datasets.push({
                label: st.charAt(0).toUpperCase() + st.slice(1) + ' Season',
                data: series[st],
                borderColor: color,
                backgroundColor: 'transparent',
                borderWidth: 3,
                tension: 0.4,
                pointRadius: 4,
                pointBackgroundColor: color
            });
        }
    });

    if (datasets.length === 0) return;

    pickupCurvesChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.days_out.map(function(d) { return d + 'd'; }),
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: function(context) {
                            return context[0].label + ' before arrival';
                        },
                        label: function(context) {
                            return context.dataset.label + ': ' + context.parsed.y + '% booked';
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    ticks: {
                        callback: function(value) {
                            return value + '%';
                        }
                    },
                    title: { display: true, text: '% of Final Occupancy Booked' },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                x: {
                    reverse: true,
                    title: { display: true, text: 'Days Before Season Start' },
                    grid: { display: false }
                }
            }
        }
    });
}

// Refresh data
function refreshData() {
    var btn = event.target.closest('button');
    var originalText = btn.innerHTML;
    btn.innerHTML = '<svg class="animate-spin w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Loading...';
    btn.disabled = true;

    // Reload the page to get fresh data
    setTimeout(function() {
        window.location.reload();
    }, 500);
}

// Show month detail modal
function showMonthDetail(year, month) {
    var modal = document.getElementById('monthDetailModal');
    var title = document.getElementById('modal-month-title');
    var content = document.getElementById('modal-content');

    // Find the forecast data for this month from the config
    var forecasts = window.PICKUP_CFG.forecastSummary;
    var forecast = null;

    for (var i = 0; i < forecasts.length; i++) {
        var f = forecasts[i];
        var fDate = new Date(f.month);
        if (fDate.getFullYear() == year && (fDate.getMonth() + 1) == month) {
            forecast = f;
            break;
        }
    }

    if (!forecast) {
        content.innerHTML = '<div class="text-center py-8 text-gray-500">Forecast data not available.</div>';
        modal.classList.remove('hidden');
        return;
    }

    title.textContent = forecast.month_name + ' Forecast';

    content.innerHTML = '\
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">\
            <div class="bg-blue-50 rounded-lg p-4">\
                <p class="text-xs text-blue-700 font-medium uppercase">OTB (Current)</p>\
                <p class="text-3xl font-bold text-blue-900 mt-1">' + forecast.otb_occupancy + '%</p>\
                <p class="text-sm text-blue-700">' + forecast.otb_nights.toLocaleString() + ' room nights</p>\
                <p class="text-sm text-blue-600">' + CURRENCY + forecast.otb_revenue.toLocaleString() + ' revenue</p>\
            </div>\
            <div class="bg-green-50 rounded-lg p-4">\
                <p class="text-xs text-green-700 font-medium uppercase">Pickup Forecast</p>\
                <p class="text-3xl font-bold text-green-900 mt-1">' + forecast.forecast_occupancy + '%</p>\
                <p class="text-sm text-green-700">' + forecast.forecast_nights.toLocaleString() + ' room nights</p>\
                <p class="text-sm text-green-600">' + CURRENCY + forecast.forecast_revenue.toLocaleString() + ' revenue</p>\
            </div>\
            <div class="bg-amber-50 rounded-lg p-4">\
                <p class="text-xs text-amber-700 font-medium uppercase">Your Scenario</p>\
                <p class="text-3xl font-bold text-amber-900 mt-1">' + forecast.scenario_occupancy + '%</p>\
                <p class="text-sm text-amber-700">' + forecast.scenario_nights.toLocaleString() + ' room nights</p>\
                <p class="text-sm text-amber-600">From Season settings</p>\
            </div>\
        </div>\
        \
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">\
            <div class="bg-gray-50 rounded-lg p-3">\
                <p class="text-xs text-gray-500">Season</p>\
                <p class="text-sm font-semibold text-gray-900">' + forecast.season_name + '</p>\
            </div>\
            <div class="bg-gray-50 rounded-lg p-3">\
                <p class="text-xs text-gray-500">Days Out</p>\
                <p class="text-sm font-semibold text-gray-900">' + forecast.days_out + '</p>\
            </div>\
            <div class="bg-gray-50 rounded-lg p-3">\
                <p class="text-xs text-gray-500">Available Room Nights</p>\
                <p class="text-sm font-semibold text-gray-900">' + forecast.available_nights.toLocaleString() + '</p>\
            </div>\
            <div class="bg-gray-50 rounded-lg p-3">\
                <p class="text-xs text-gray-500">Forecast Confidence</p>\
                <p class="text-sm font-semibold text-gray-900">' + forecast.confidence + '% (' + forecast.confidence_label + ')</p>\
            </div>\
        </div>\
        \
        ' + (forecast.vs_stly !== null ? '\
        <div class="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">\
            <div class="flex items-center justify-between">\
                <div>\
                    <p class="text-sm font-semibold text-amber-900">vs Same Time Last Year (STLY)</p>\
                    <p class="text-xs text-amber-700">Last year ended at ' + forecast.stly_occupancy + '% occupancy</p>\
                </div>\
                <span class="text-2xl font-bold ' + (forecast.vs_stly >= 0 ? 'text-green-600' : 'text-red-600') + '">\
                    ' + (forecast.vs_stly >= 0 ? '+' : '') + forecast.vs_stly + '%\
                </span>\
            </div>\
        </div>\
        ' : '') + '\
        \
        ' + (forecast.market_factor && forecast.market_factor !== 1.0 ? '\
        <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">\
            <div class="flex items-center justify-between">\
                <div>\
                    <p class="text-sm font-semibold text-blue-900">Market Signal</p>\
                    <p class="text-xs text-blue-700">Based on MoT arrival trends (YoY)</p>\
                </div>\
                <span class="text-xl font-bold ' + (forecast.market_factor >= 1.0 ? 'text-green-600' : 'text-red-600') + '">\
                    ' + forecast.market_factor + 'x\
                </span>\
            </div>\
        </div>\
        ' : '') + '\
        \
        <div class="flex items-center justify-between pt-4 border-t">\
            <p class="text-sm text-gray-500">Click anywhere outside to close</p>\
            <button onclick="closeMonthDetail()" \
                    class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition">\
                Close\
            </button>\
        </div>\
    ';

    modal.classList.remove('hidden');
}

function closeMonthDetail() {
    document.getElementById('monthDetailModal').classList.add('hidden');
}

// Close modal on outside click
document.getElementById('monthDetailModal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeMonthDetail();
    }
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing Pickup Analysis Dashboard...');
    initCharts();
});
