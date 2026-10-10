/* Gráficos do dashboard (Chart.js servido localmente).
   Os dados reais vêm do bloco JSON #dados-graficos gerado pelo servidor. */

document.addEventListener('DOMContentLoaded', function () {
    var bloco = document.getElementById('dados-graficos');
    if (!bloco || typeof Chart === 'undefined') { return; }

    var dados;
    try {
        dados = JSON.parse(bloco.textContent);
    } catch (e) {
        return;
    }

    // paleta verde da aplicação + cores semânticas
    var cores = {
        primario: '#2E7D32',
        primarioClaro: '#66BB6A',
        primarioMedio: '#388E3C',
        primarioEscuro: '#1B5E20',
        aviso: '#F9A825',
        perigo: '#C62828',
        info: '#0277BD',
        aguarda: '#00897B',
        neutro: '#90A4AE',
        texto: '#263238',
        grelha: 'rgba(38, 50, 56, 0.08)'
    };

    // tons de verde para gráficos de séries (top clientes, tipos)
    var escalaVerde = ['#1B5E20', '#2E7D32', '#43A047', '#66BB6A', '#81C784',
                       '#A5D6A7', '#C8E6C9', '#4CAF50', '#388E3C', '#689F38'];

    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
    Chart.defaults.color = cores.texto;

    function grafico(id, config) {
        var canvas = document.getElementById(id);
        if (canvas) { new Chart(canvas, config); }
    }

    // 1 — evolução mensal (criadas vs concluídas)
    grafico('grafico-meses', {
        type: 'line',
        data: {
            labels: dados.meses.labels,
            datasets: [{
                label: 'Criadas',
                data: dados.meses.criadas,
                borderColor: cores.primario,
                backgroundColor: 'rgba(46, 125, 50, 0.12)',
                fill: true,
                tension: 0.3,
                pointRadius: 3
            }, {
                label: 'Concluídas',
                data: dados.meses.concluidas,
                borderColor: cores.info,
                backgroundColor: 'rgba(2, 119, 189, 0.08)',
                borderDash: [6, 3],
                fill: false,
                tension: 0.3,
                pointRadius: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom' } },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: cores.grelha } },
                x: { grid: { display: false } }
            }
        }
    });

    // 2 — distribuição por estado (donut, cores alinhadas com as badges)
    grafico('grafico-estados', {
        type: 'doughnut',
        data: {
            labels: dados.estados.labels,
            datasets: [{
                data: dados.estados.valores,
                backgroundColor: [cores.aviso, cores.info, cores.aguarda, cores.primario, cores.neutro],
                borderColor: '#FFFFFF',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: { legend: { position: 'bottom' } }
        }
    });

    // 3 — tipos de assistência (barras verticais)
    grafico('grafico-tipos', {
        type: 'bar',
        data: {
            labels: dados.tipos.labels,
            datasets: [{
                data: dados.tipos.valores,
                backgroundColor: escalaVerde.slice(0, dados.tipos.labels.length),
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: cores.grelha } },
                x: { grid: { display: false } }
            }
        }
    });

    // 4 — idade das assistências em aberto (quanto mais antiga, mais grave)
    grafico('grafico-idades', {
        type: 'bar',
        data: {
            labels: dados.idades.labels,
            datasets: [{
                data: dados.idades.valores,
                backgroundColor: [cores.primarioClaro, cores.aviso, '#EF6C00', cores.perigo],
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: cores.grelha } },
                x: { grid: { display: false } }
            }
        }
    });

    // 5 — pagas vs por pagar (com valores em € no tooltip, quando existem)
    grafico('grafico-pagamentos', {
        type: 'doughnut',
        data: {
            labels: ['Pagas', 'Por pagar'],
            datasets: [{
                data: [dados.pagamentos.pagas, dados.pagamentos.por_pagar],
                backgroundColor: [cores.primario, cores.perigo],
                borderColor: '#FFFFFF',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: { position: 'bottom' },
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            var valor = ctx.dataIndex === 0
                                ? dados.pagamentos.valor_pago
                                : dados.pagamentos.valor_por_receber;
                            var texto = ctx.label + ': ' + ctx.parsed;
                            if (valor > 0) {
                                texto += ' (' + valor.toFixed(2).replace('.', ',') + ' €)';
                            }
                            return texto;
                        }
                    }
                }
            }
        }
    });

    // 6 — top clientes (barras horizontais)
    grafico('grafico-clientes', {
        type: 'bar',
        data: {
            labels: dados.top_clientes.labels,
            datasets: [{
                data: dados.top_clientes.valores,
                backgroundColor: escalaVerde.slice(0, dados.top_clientes.labels.length),
                borderRadius: 4
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: cores.grelha } },
                y: { grid: { display: false } }
            }
        }
    });
});
