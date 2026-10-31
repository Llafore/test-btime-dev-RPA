# Contrato de previsão diária — versão 1

Este documento define o contrato usado pelo exportador e pelo validador do CSV.
O descriptor versionado está em
`src/weather_rpa/schemas/daily_forecast.schema.json` e é distribuído com o pacote.

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

## Registro e colunas do CSV

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

Essa é a ordem obrigatória das colunas. No domínio, `DailyForecast` referencia
`Location`; o adaptador CSV projeta nome, UF, coordenadas e fuso diretamente,
sem exportar `location_id`. O arquivo é compreensível sem um cadastro externo.
A chave do artefato é `(location_name, state, latitude, longitude, timezone,
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

O validador do artefato verifica cabeçalho, tipos serializados, campos obrigatórios,
chave única, arquivo vazio e as invariantes do domínio. A cobertura de datas solicitadas pertence ao caso de uso.
Os testes desta etapa não fazem chamadas externas nem dependem do layout dos sites.

## Descriptor tabular e formato físico

O descriptor segue o subconjunto de Table Schema necessário ao projeto: `fields`
ordenados, tipos `string`, `number`, `date` e `datetime`, restrições `required`,
`minimum`, `maximum`, `enum` e `pattern`, `missingValues: [""]` e `primaryKey` composta.
O validador atende a este contrato fixo; não é um motor de schemas arbitrários.

Regras adicionais da aplicação:

- UTF-8 sem BOM, separador vírgula e aspas conforme a biblioteca `csv` do Python.
- O exportador escreve quebras de linha LF; o leitor também aceita CRLF.
- Cabeçalho exato, sem colunas extras, ausentes, repetidas ou reordenadas.
- Toda linha tem a mesma quantidade de campos; linhas vazias são inválidas.
- Datas em `YYYY-MM-DD`; instantes em ISO 8601 com `T`, segundos e offset `+00:00`.
  Frações de segundo emitidas por `datetime.isoformat()` são aceitas.
- Números finitos com ponto decimal, sem separador de milhares; expoentes são aceitos.
- Somente precipitação pode estar vazia. A string `None` não representa ausência.
- Espaços nas extremidades não são corrigidos nesta fronteira. A normalização da
  fonte pertence ao adaptador de coleta; o artefato precisa chegar normalizado.
- Duplicidades são verificadas após a conversão dos tipos: `-23.55` e `-23.5500`
  representam a mesma coordenada. Um ID interno diferente não evita duplicidade.

## Exemplo de uso local

O exemplo abaixo usa dados sintéticos apenas para demonstrar a API, sem consultar
fontes ou afirmar que os valores representam uma previsão real. Execute após
instalar o projeto, ou disponibilize `src` no caminho de importação.

```python
from datetime import date, datetime, timezone
from pathlib import Path

from weather_rpa.domain import DailyForecast, Location, WeatherSource
from weather_rpa.adapters.csv_artifact import CsvForecastExporter, CsvArtifactValidator

location = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")
forecast = DailyForecast(
    location=location,
    forecast_date=date(2026, 10, 31),
    temperature_min_c=15.0,
    temperature_max_c=27.0,
    precipitation_mm=None,
    source=WeatherSource.OPEN_METEO,
    collected_at=datetime(2026, 10, 31, 12, tzinfo=timezone.utc),
)
Path("output").mkdir(exist_ok=True)
count = CsvForecastExporter().export([forecast], "output/forecast.csv")
assert count == CsvArtifactValidator().validate("output/forecast.csv") == 1
```

Cada exportação substitui o arquivo inteiro; append e histórico de execuções ficam
fora desta etapa. A validação interrompe no primeiro problema e inclui a linha física
quando disponível. Arquivos temporários são removidos ao sair do exportador, inclusive
quando há erro; o destino só é substituído após validação bem-sucedida.
