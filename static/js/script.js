/* Gestão de Assistências — JavaScript de apoio.
   A pesquisa principal é feita no servidor; aqui ficam apenas
   melhorias de usabilidade. Todas as funções verificam se os
   elementos existem antes de atuar. */

document.addEventListener('DOMContentLoaded', function () {

    // Confirmações antes de submeter (substitui onsubmit inline, que a
    // Content-Security-Policy bloqueia)
    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (form && form.hasAttribute && form.hasAttribute('data-confirm')) {
            if (!window.confirm(form.getAttribute('data-confirm'))) {
                event.preventDefault();
            }
        }
    });

    // Pré-preencher data e hora atuais no formulário de nova assistência
    function preencherDataHora() {
        var dataInput = document.getElementById('data');
        var horaInput = document.getElementById('hora');
        var agora = new Date();

        if (dataInput && !dataInput.value) {
            dataInput.value = agora.getFullYear() + '-' +
                String(agora.getMonth() + 1).padStart(2, '0') + '-' +
                String(agora.getDate()).padStart(2, '0');
        }
        if (horaInput && !horaInput.value) {
            horaInput.value = String(agora.getHours()).padStart(2, '0') + ':' +
                String(agora.getMinutes()).padStart(2, '0');
        }
    }

    var formNovaAssistencia = document.getElementById('nova-assistencia');
    if (formNovaAssistencia) {
        // já aberto (ex.: veio do botão "nova assistência para este cliente")
        if (formNovaAssistencia.classList.contains('show')) {
            preencherDataHora();
        }
        formNovaAssistencia.addEventListener('show.bs.collapse', preencherDataHora);
    }

    // Filtro do seletor de clientes no formulário de nova assistência
    var clienteSearch = document.getElementById('cliente_search');
    var clienteSelect = document.getElementById('cliente_id');
    if (clienteSearch && clienteSelect) {
        var opcoesOriginais = Array.prototype.slice.call(clienteSelect.options);
        clienteSearch.addEventListener('input', function () {
            var termo = clienteSearch.value.toLowerCase().trim();
            var selecionado = clienteSelect.value;
            clienteSelect.innerHTML = '';
            opcoesOriginais.forEach(function (opcao) {
                if (!termo || opcao.value === '' || opcao.text.toLowerCase().indexOf(termo) !== -1) {
                    clienteSelect.appendChild(opcao);
                }
            });
            // mantém a seleção se ainda estiver visível; senão seleciona o 1.º resultado
            if (selecionado && clienteSelect.querySelector('option[value="' + selecionado + '"]')) {
                clienteSelect.value = selecionado;
            } else if (termo && clienteSelect.options.length > 1) {
                clienteSelect.selectedIndex = 1;
            }
        });
    }

    // Confirmação de palavra-passe na página de configuração
    var configForm = document.getElementById('configuracao-form');
    if (configForm) {
        configForm.addEventListener('submit', function (event) {
            var nova = document.getElementById('new_password');
            var confirmacao = document.getElementById('confirm_password');
            if (nova && confirmacao && nova.value !== confirmacao.value) {
                event.preventDefault();
                alert('A confirmação não coincide com a nova palavra-passe.');
                confirmacao.focus();
            }
        });
    }

    // Fechar automaticamente as mensagens de sucesso após 5 segundos
    document.querySelectorAll('.alert-success').forEach(function (alerta) {
        setTimeout(function () {
            if (window.bootstrap && bootstrap.Alert) {
                bootstrap.Alert.getOrCreateInstance(alerta).close();
            } else {
                alerta.remove();
            }
        }, 5000);
    });

    // Abrir o formulário de novo cliente quando a página é chamada com #novo-cliente
    if (window.location.hash === '#novo-cliente') {
        var colapso = document.getElementById('novo-cliente');
        if (colapso && window.bootstrap && bootstrap.Collapse) {
            bootstrap.Collapse.getOrCreateInstance(colapso).show();
            var campoNome = document.getElementById('nome');
            if (campoNome) { campoNome.focus(); }
        }
    }
});
