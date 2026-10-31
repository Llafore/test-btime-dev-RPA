# Contrato de previsão diária — versão 1

Este documento define o significado dos dados do primeiro PR. O schema executável
e a validação do CSV serão implementados no segundo PR.

## Localidade

`Location` é um objeto de valor imutável, sem cadastro, repositório ou persistência
separada. Agrupa e valida os dados da localidade mesmo em uma coleta de cidade única.
Contém `location_id` (identificador de correlação interna), `name`, `state`
(sigla de duas letras ASCII maiúsculas), `latitude` (entre -90 e 90), `longitude`
(entre -180 e 180) e `timezone` (identificador IANA disponível).
Textos obrigatórios não podem ser vazios nem conter espaços nas extremidades.
Coordenadas devem ser numéricas e finitas; booleanos não são aceitos.

`location_id` pode correlacionar entradas e resultados durante uma execução com
várias localidades. Não pressupõe identidade global nem ciclo de vida de entidade;
a igualdade do objeto considera o conjunto de seus atributos, não apenas o ID.
Não é um código do provedor nem uma referência que o consumidor do CSV precise
resolver. Identificadores específicos das fontes pertencem aos adaptadores.

## Registro e colunas planejadas do CSV

| Coluna | Tipo | Regra |
| --- | --- | --- |
| location_name | texto | Nome da localidade (`Location.name`) |
| state | texto | UF da localidade |
| latitude | número | Latitude da localidade, entre -90 e 90 |
| longitude | número | Longitude da localidade, entre -180 e 180 |
| forecast_date | data ISO 8601 | Dia civil no fuso da localidade |
| timezone | texto | Identificador IANA da localidade |
| temperature_min_c | número | Obrigatório, finito, menor ou igual à máxima |
| temperature_max_c | número | Obrigatório e finito |
| precipitation_mm | número ou vazio | Acumulado diário não negativo; vazio significa ausência |
| source | texto | `open_meteo` ou `climatempo` |
| collected_at | datetime ISO 8601 | Instante com offset UTC `+00:00` |

Essa é a ordem planejada das colunas. No domínio, `DailyForecast` referencia
`Location`; o adaptador CSV projetará nome, UF, coordenadas e fuso diretamente,
sem exportar `location_id`. O arquivo será compreensível sem um cadastro externo.
A chave do artefato será `(location_name, state, latitude, longitude, timezone,
forecast_date, source)`, sem depender do identificador interno. Esta chave identifica
registros de uma coleta; histórico de múltiplas execuções fica fora desta etapa.

## Tempo e precipitação

O domínio recebe datas e números já interpretados. Não converte strings de fontes.
`collected_at` sem fuso é rejeitado; com fuso é convertido para UTC, preservando o
instante. A data prevista nunca é inferida do horário de coleta nem convertida
para UTC. `timezone` mantém o contexto do dia local.

Precipitação representa o intervalo entre o início desse dia local e o início do
próximo dia local, cuja duração pode variar por mudanças de horário. Os adaptadores
deverão verificar o período da fonte antes de preencher o campo. Probabilidade de
chuva não pode ser usada como acumulado. `None` permanece ausência; `0` significa
acumulado zero informado. Nenhuma fonte deve ser consultada como fallback silencioso
para completar o registro de outra fonte.

## Fronteira das validações

O domínio verifica cada registro: tipos, finitude, intervalos e consistência das
temperaturas. Aceita temperaturas negativas e mínima igual à máxima. Não restringe
a data em relação ao relógio atual, permitindo reprocessamento e testes reproduzíveis.

O validador do artefato verificará cabeçalho, tipos serializados, campos obrigatórios,
chave única e arquivo vazio. A cobertura de datas solicitadas pertence ao caso de uso.
Os testes desta etapa não fazem chamadas externas nem dependem do layout dos sites.
