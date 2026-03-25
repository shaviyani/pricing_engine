    // Read config from inline window.ANALYSIS_CFG
    const monthDetailUrl = window.ANALYSIS_CFG.monthDetailUrl;
    const chartData = window.ANALYSIS_CFG.chartData;
    var CURRENCY = window.ANALYSIS_CFG.currency;
    const YEAR = window.ANALYSIS_CFG.year;
    const smDataFromCfg = window.ANALYSIS_CFG.sourceMarketMonthly;

    // Color palette
    const colors = {
        primary: 'rgb(59, 130, 246)',
        primaryLight: 'rgba(59, 130, 246, 0.2)',
        green: 'rgb(34, 197, 94)',
        greenLight: 'rgba(34, 197, 94, 0.2)',
        amber: 'rgb(245, 158, 11)',
        purple: 'rgb(139, 92, 246)',
        rose: 'rgb(244, 63, 94)',
        gray: 'rgb(156, 163, 175)',
        grayLight: 'rgba(156, 163, 175, 0.3)',
    };

    const pieColors = [
        'rgb(59, 130, 246)',
        'rgb(34, 197, 94)',
        'rgb(245, 158, 11)',
        'rgb(139, 92, 246)',
        'rgb(244, 63, 94)',
        'rgb(14, 165, 233)',
        'rgb(249, 115, 22)',
        'rgb(168, 85, 247)',
    ];

    // Monthly Revenue Chart
    var revenueChartInstance = new Chart(document.getElementById('revenueChart'), {
        type: 'bar',
        data: {
            labels: chartData.months,
            datasets: [{
                label: 'Monthly Revenue ($k)',
                data: chartData.revenue.map(v => v / 1000),
                backgroundColor: colors.primary,
                borderRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: function(evt, elements) {
                if (elements.length > 0) {
                    var monthIdx = elements[0].index;
                    openMonthModal(monthIdx + 1, YEAR);
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return CURRENCY + (context.raw * 1000).toLocaleString();
                        },
                        footer: function() { return 'Click for details'; }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: {
                        callback: function(value) {
                            return CURRENCY + value + 'k';
                        }
                    }
                },
                x: { grid: { display: false } }
            },
            onHover: function(evt, elements) {
                evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
            }
        }
    });

    // Monthly Occupancy Chart
    var occupancyChartInstance = new Chart(document.getElementById('occupancyChart'), {
        type: 'bar',
        data: {
            labels: chartData.months,
            datasets: [
                {
                    label: 'Sold',
                    data: chartData.room_nights,
                    backgroundColor: colors.primary,
                    borderRadius: 4,
                },
                {
                    label: 'Available',
                    data: chartData.available,
                    backgroundColor: colors.grayLight,
                    borderRadius: 4,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: function(evt, elements) {
                if (elements.length > 0) {
                    var monthIdx = elements[0].index;
                    openMonthModal(monthIdx + 1, YEAR);
                }
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: { usePointStyle: true, padding: 15 }
                },
                tooltip: {
                    callbacks: {
                        footer: function() { return 'Click for details'; }
                    }
                }
            },
            scales: {
                y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.05)' } },
                x: { grid: { display: false } }
            },
            onHover: function(evt, elements) {
                evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
            }
        }
    });

    // Channel Pie Chart
    if (chartData.channel_labels.length > 0) {
        new Chart(document.getElementById('channelPieChart'), {
            type: 'doughnut',
            data: {
                labels: chartData.channel_labels,
                datasets: [{
                    data: chartData.channel_values,
                    backgroundColor: pieColors.slice(0, chartData.channel_labels.length),
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const value = context.raw;
                                const percent = chartData.channel_percents[context.dataIndex];
                                return context.label + ': ' + CURRENCY + value.toLocaleString() + ' (' + percent + '%)';
                            }
                        }
                    }
                }
            }
        });
    }

    // Meal Plan Pie Chart
    if (chartData.meal_plan_labels.length > 0) {
        new Chart(document.getElementById('mealPlanPieChart'), {
            type: 'doughnut',
            data: {
                labels: chartData.meal_plan_labels,
                datasets: [{
                    data: chartData.meal_plan_values,
                    backgroundColor: pieColors.slice(0, chartData.meal_plan_labels.length),
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const value = context.raw;
                                const percent = chartData.meal_plan_percents[context.dataIndex];
                                return context.label + ': ' + CURRENCY + value.toLocaleString() + ' (' + percent + '%)';
                            }
                        }
                    }
                }
            }
        });
    }

    // Year selector change handler
    document.getElementById('yearSelector').addEventListener('change', function() {
        window.location.href = '?year=' + this.value;
    });

    // =============================================
    // MODAL FUNCTIONS
    // =============================================

    let velocityChartInstance = null;
    let roomsChartInstance = null;
    let leadTimeChartInstance = null;
    let channelChartInstance = null;
    let countryChartInstance = null;

    function openMonthModal(month, year) {
        const modal = document.getElementById('monthDetailModal');
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';

        // Show loading, hide content
        document.getElementById('modalLoading').classList.remove('hidden');
        document.getElementById('modalContent').classList.add('hidden');

        // Update title
        const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
                            'July', 'August', 'September', 'October', 'November', 'December'];
        document.getElementById('modalTitle').textContent = monthNames[month - 1] + ' ' + year + ' Details';

        // Fetch data
        fetch(monthDetailUrl + '?month=' + month + '&year=' + year)
            .then(response => response.json())
            .then(data => {
                populateModal(data);
                // Hide loading, show content
                document.getElementById('modalLoading').classList.add('hidden');
                document.getElementById('modalContent').classList.remove('hidden');
            })
            .catch(error => {
                console.error('Error fetching month details:', error);
                document.getElementById('modalLoading').innerHTML = '<p class="text-red-600">Error loading data. Please try again.</p>';
            });
    }

    function closeMonthModal() {
        document.getElementById('monthDetailModal').classList.add('hidden');
        document.body.style.overflow = '';

        // Destroy charts
        if (velocityChartInstance) { velocityChartInstance.destroy(); velocityChartInstance = null; }
        if (roomsChartInstance) { roomsChartInstance.destroy(); roomsChartInstance = null; }
        if (leadTimeChartInstance) { leadTimeChartInstance.destroy(); leadTimeChartInstance = null; }
        if (channelChartInstance) { channelChartInstance.destroy(); channelChartInstance = null; }
        if (countryChartInstance) { countryChartInstance.destroy(); countryChartInstance = null; }
    }

    function showTab(tabName) {
        document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
        document.querySelectorAll('.tab-btn').forEach(el => {
            el.classList.remove('border-blue-500', 'text-blue-600');
            el.classList.add('border-transparent', 'text-gray-500');
        });

        document.getElementById('content-' + tabName).classList.remove('hidden');
        const activeTab = document.getElementById('tab-' + tabName);
        activeTab.classList.remove('border-transparent', 'text-gray-500');
        activeTab.classList.add('border-blue-500', 'text-blue-600');
    }

    function populateModal(data) {
        // Update summary cards
        document.getElementById('modalRevenue').textContent = CURRENCY + data.summary.revenue.toLocaleString(undefined, {maximumFractionDigits: 0});
        document.getElementById('modalRoomNights').textContent = data.summary.room_nights.toLocaleString();
        document.getElementById('modalOccupancy').textContent = data.summary.occupancy.toFixed(1) + '%';
        document.getElementById('modalADR').textContent = CURRENCY + data.summary.adr.toFixed(2);

        populateVelocityTab(data.velocity);
        populateRoomsTab(data.room_distribution);
        populateLeadTimeTab(data.lead_time);
        populateMarketTab(data.channel_distribution, data.country_distribution);


        showTab('velocity');
    }

    function populateVelocityTab(velocity) {
        const tbody = document.getElementById('velocityTableBody');
        tbody.innerHTML = '';

        let cumulative = 0;
        velocity.forEach(row => {
            cumulative += row.net_pickup;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="px-4 py-3 text-sm text-gray-900">${row.booking_month}</td>
                <td class="px-4 py-3 text-sm text-right text-green-600">+${row.new_nights}</td>
                <td class="px-4 py-3 text-sm text-right text-red-600">${row.cancelled_nights > 0 ? '-' + row.cancelled_nights : '-'}</td>
                <td class="px-4 py-3 text-sm text-right font-medium ${row.net_pickup >= 0 ? 'text-green-600' : 'text-red-600'}">
                    ${row.net_pickup >= 0 ? '+' : ''}${row.net_pickup}
                </td>
                <td class="px-4 py-3 text-sm text-right font-semibold text-gray-900">${cumulative}</td>
            `;
            tbody.appendChild(tr);
        });

        // Chart - Line chart showing cumulative OTB build-up
        const ctx = document.getElementById('velocityChart').getContext('2d');
        if (velocityChartInstance) velocityChartInstance.destroy();

        // Calculate cumulative values for line chart
        let cumulativeData = [];
        let runningTotal = 0;
        velocity.forEach(v => {
            runningTotal += v.net_pickup;
            cumulativeData.push(runningTotal);
        });

        velocityChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: velocity.map(v => v.booking_month),
                datasets: [
                    {
                        label: 'Cumulative OTB',
                        data: cumulativeData,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 5,
                        pointBackgroundColor: '#3b82f6',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                    },
                    {
                        label: 'New Room Nights',
                        data: velocity.map(v => v.new_nights),
                        borderColor: '#10b981',
                        backgroundColor: 'transparent',
                        borderDash: [5, 5],
                        tension: 0.3,
                        pointRadius: 4,
                        pointBackgroundColor: '#10b981',
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ': ' + context.raw + ' room nights';
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Room Nights'
                        }
                    }
                }
            }
        });
    }

    function populateRoomsTab(rooms) {
        const tbody = document.getElementById('roomsTableBody');
        tbody.innerHTML = '';

        const total = rooms.reduce((sum, r) => sum + r.room_nights, 0);

        rooms.forEach(row => {
            const share = total > 0 ? (row.room_nights / total * 100).toFixed(1) : 0;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="px-4 py-3 text-sm text-gray-900">${row.room_type}</td>
                <td class="px-4 py-3 text-sm text-right">${row.room_nights}</td>
                <td class="px-4 py-3 text-sm text-right">${CURRENCY}${row.revenue.toLocaleString(undefined, {maximumFractionDigits: 0})}</td>
                <td class="px-4 py-3 text-sm text-right text-gray-600">${share}%</td>
            `;
            tbody.appendChild(tr);
        });

        // Chart
        const ctx = document.getElementById('roomsChart').getContext('2d');
        if (roomsChartInstance) roomsChartInstance.destroy();

        roomsChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: rooms.map(r => r.room_type),
                datasets: [{ data: rooms.map(r => r.room_nights), backgroundColor: pieColors.slice(0, rooms.length) }]
            },
            options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
        });
    }

    function populateLeadTimeTab(leadTime) {
        const tbody = document.getElementById('leadTimeTableBody');
        tbody.innerHTML = '';

        const total = leadTime.reduce((sum, r) => sum + r.bookings, 0);

        leadTime.forEach(row => {
            const share = total > 0 ? (row.bookings / total * 100).toFixed(1) : 0;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="px-4 py-3 text-sm text-gray-900">${row.bucket}</td>
                <td class="px-4 py-3 text-sm text-right">${row.bookings}</td>
                <td class="px-4 py-3 text-sm text-right">${row.room_nights}</td>
                <td class="px-4 py-3 text-sm text-right">${CURRENCY}${row.avg_adr.toFixed(2)}</td>
                <td class="px-4 py-3 text-sm text-right text-gray-600">${share}%</td>
            `;
            tbody.appendChild(tr);
        });

        // Chart
        const ctx = document.getElementById('leadTimeChart').getContext('2d');
        if (leadTimeChartInstance) leadTimeChartInstance.destroy();

        leadTimeChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: leadTime.map(l => l.bucket),
                datasets: [{ label: 'Bookings', data: leadTime.map(l => l.bookings), backgroundColor: '#3b82f6' }]
            },
            options: { responsive: true, plugins: { legend: { display: false } } }
        });
    }

    function populateMarketTab(channels, countryData) {
        // Channels
        const channelBody = document.getElementById('channelTableBody');
        channelBody.innerHTML = '';
        const channelTotal = channels.reduce((sum, c) => sum + c.room_nights, 0);

        channels.forEach(row => {
            const share = channelTotal > 0 ? (row.room_nights / channelTotal * 100).toFixed(1) : 0;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="px-4 py-2 text-gray-900">${row.channel}</td>
                <td class="px-4 py-2 text-right">${row.room_nights}</td>
                <td class="px-4 py-2 text-right text-gray-600">${share}%</td>
            `;
            channelBody.appendChild(tr);
        });

        // Countries — handle enriched dict or legacy array
        var countries, hasNational = false, nationalPeriod = '', isProjected = false;
        if (countryData && countryData.countries) {
            countries = countryData.countries;
            hasNational = countryData.has_national || false;
            nationalPeriod = countryData.national_period || '';
            isProjected = countryData.is_projected || false;
        } else if (Array.isArray(countryData)) {
            countries = countryData;
        } else {
            countries = [];
        }

        // Update table headers
        var thead = document.getElementById('countryTableHead');
        if (hasNational) {
            thead.innerHTML = '<tr>' +
                '<th class="px-4 py-2 text-left text-xs font-semibold text-gray-600">Country</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Nights</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Revenue</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">ADR</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Yours</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">National</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Index</th>' +
                '</tr>';
        } else {
            thead.innerHTML = '<tr>' +
                '<th class="px-4 py-2 text-left text-xs font-semibold text-gray-600">Country</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Nights</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Revenue</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">ADR</th>' +
                '<th class="px-4 py-2 text-right text-xs font-semibold text-gray-600">Share</th>' +
                '</tr>';
        }

        // Populate rows
        var countryBody = document.getElementById('countryTableBody');
        countryBody.innerHTML = '';
        var countryTotal = countries.reduce(function(sum, c) { return sum + c.room_nights; }, 0);

        countries.forEach(function(row) {
            var share = countryTotal > 0 ? (row.room_nights / countryTotal * 100).toFixed(1) : 0;
            var tr = document.createElement('tr');
            var isGap = row.is_gap || false;

            if (isGap) {
                tr.className = 'bg-amber-50 italic';
            }

            var revStr = row.revenue ? CURRENCY + Number(row.revenue).toLocaleString(undefined, {maximumFractionDigits: 0}) : '—';
            var adrStr = row.adr ? CURRENCY + Number(row.adr).toFixed(0) : '—';

            if (hasNational) {
                var propShare = (row.prop_share !== undefined ? row.prop_share : share);
                var natShare = row.national_share !== null && row.national_share !== undefined ? row.national_share.toFixed(1) + '%' : '—';
                var idx = row.index !== null && row.index !== undefined ? row.index.toFixed(1) : '—';
                var idxClass = '';
                if (row.index !== null && row.index !== undefined) {
                    idxClass = row.index >= 1.0 ? 'text-blue-600 font-medium' : 'text-amber-600';
                }
                tr.innerHTML =
                    '<td class="px-4 py-2 text-gray-900">' + row.country + (isGap ? ' <span class="text-xs text-amber-500">(gap)</span>' : '') + '</td>' +
                    '<td class="px-4 py-2 text-right">' + row.room_nights + '</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + revStr + '</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + adrStr + '</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + parseFloat(propShare).toFixed(1) + '%</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + natShare + '</td>' +
                    '<td class="px-4 py-2 text-right ' + idxClass + '">' + idx + '</td>';
            } else {
                tr.innerHTML =
                    '<td class="px-4 py-2 text-gray-900">' + row.country + '</td>' +
                    '<td class="px-4 py-2 text-right">' + row.room_nights + '</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + revStr + '</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + adrStr + '</td>' +
                    '<td class="px-4 py-2 text-right text-gray-600">' + share + '%</td>';
            }
            countryBody.appendChild(tr);
        });

        // Footnote
        var tfoot = document.getElementById('countryTableFoot');
        tfoot.innerHTML = '';
        if (hasNational && nationalPeriod) {
            var colspan = hasNational ? 7 : 5;
            var projBadge = isProjected
                ? ' <span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">projected</span>'
                : '';
            var footRow = document.createElement('tr');
            footRow.innerHTML = '<td colspan="' + colspan + '" class="px-4 py-2 text-xs text-gray-400">' +
                nationalPeriod + projBadge +
                ' \u00b7 Index = your share \u00f7 national share' +
                '</td>';
            tfoot.appendChild(footRow);
        }

        // Charts
        const channelCtx = document.getElementById('channelChart').getContext('2d');
        if (channelChartInstance) channelChartInstance.destroy();
        channelChartInstance = new Chart(channelCtx, {
            type: 'doughnut',
            data: {
                labels: channels.map(c => c.channel),
                datasets: [{ data: channels.map(c => c.room_nights), backgroundColor: pieColors.slice(0, channels.length) }]
            },
            options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } } }
        });

        // Country chart — exclude gap markets (zero nights)
        var chartCountries = countries.filter(function(c) { return c.room_nights > 0; });
        const countryCtx = document.getElementById('countryChart').getContext('2d');
        if (countryChartInstance) countryChartInstance.destroy();
        countryChartInstance = new Chart(countryCtx, {
            type: 'doughnut',
            data: {
                labels: chartCountries.map(c => c.country),
                datasets: [{ data: chartCountries.map(c => c.room_nights), backgroundColor: pieColors.slice(0, chartCountries.length) }]
            },
            options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } } }
        });
    }

    // =========================================================
    // Source Market Trend Chart (top 5 countries, monthly line)
    // =========================================================
    if (smDataFromCfg) {
    (function() {
        var smData = smDataFromCfg;
        var canvas = document.getElementById('sourceMarketTrendChart');
        if (!canvas || !smData.series || smData.series.length === 0) return;

        var lineColors = [
            'rgb(59, 130, 246)',   // blue
            'rgb(34, 197, 94)',    // green
            'rgb(245, 158, 11)',   // amber
            'rgb(139, 92, 246)',   // purple
            'rgb(244, 63, 94)',    // rose
        ];

        var datasets = smData.series.map(function(s, i) {
            return {
                label: s.country,
                data: s.data,
                borderColor: lineColors[i % lineColors.length],
                backgroundColor: lineColors[i % lineColors.length],
                tension: 0.3,
                fill: false,
                pointRadius: 3,
            };
        });

        new Chart(canvas, {
            type: 'line',
            data: {
                labels: smData.months,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                    title: { display: true, text: 'Monthly Room Nights by Source Market', font: { size: 13 } },
                },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Room Nights' } },
                },
            },
        });
    })();
    }

    // Close on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeMonthModal();
    });
