# Adaptador Open-Meteo

`OpenMeteoCollector` atende à porta `ForecastCollector`, com fonte `open_meteo`.
Consulta `https://api.open-meteo.com/v1/forecast` sem chave, usando as coordenadas
da `Location`, o período inclusivo e o fuso IANA explicitamente configurados.

## Campos e normalização

- `temperature_2m_min` → `temperature_min_c`, em Celsius.
- `temperature_2m_max` → `temperature_max_c`, em Celsius.
- `precipitation_sum` → `precipitation_mm`, em milímetros, incluindo chuva e neve.
- `daily.time` → `forecast_date`, como data local, sem conversão para UTC.
- Um instante de coleta após a resposta é compartilhado por todos os registros.

A resposta precisa declarar unidades Celsius/mm e datas ISO 8601. Os arrays devem
existir e ter comprimentos iguais; assim evitamos truncamento silencioso por `zip`.
Precipitação `null` vira `None`; zero continua zero. Temperaturas ausentes, valores
não finitos, booleanos ou strings numéricas são rejeitados pelas regras do domínio.
Ausência do array de precipitação é erro estrutural, distinta de um valor `null`.
Espaços nas extremidades de datas e do identificador do fuso são normalizados.

A localidade e suas coordenadas são preservadas. As coordenadas retornadas pela API
representam a célula do modelo meteorológico, que pode diferir do ponto solicitado.
A normalização é feita pela função pura `parse_daily_forecasts`, separada de HTTP.
A verificação de cobertura do período continua sendo do caso de uso compartilhado.

## Dias locais e deslocamento UTC

A documentação informa que a resposta ISO 8601 usa um offset UTC fixo calculado no
momento da consulta e ignora transições de horário de verão no período. O parser
confere `utc_offset_seconds` contra os limites inicial e final de cada dia, tanto no
fuso solicitado quanto no fuso retornado. Aliases equivalentes são aceitos quando
presentes na base de fusos. Se houver divergência, a operação falha explicitamente.

Não reinterpretamos um agregado de 24 horas como um dia civil de 23 ou 25 horas.
Suporte a esses períodos exigiria outro tratamento dos dados horários; não está
implementado nesta etapa. O adaptador não troca API, unidades ou período como fallback.

## Transporte e falhas

`OpenMeteoHttpClient` usa `urllib` da biblioteca padrão e não adiciona dependências.
Defaults: timeout de 15 segundos por operação de rede, até 3 tentativas e esperas
progressivas de 1 e 2 segundos. O timeout não é um prazo global de toda a coleta.

São retentados erros de rede/resposta interrompida e HTTP 429, 500, 502, 503 e 504.
HTTP 4xx permanentes, JSON inválido e erros de contrato não são retentados. Não há
espera após a última tentativa. `Retry-After` em segundos ou data HTTP é respeitado;
se exceder 60 segundos (limite configurável), o cliente encerra em vez de tentar cedo.
Headers inválidos usam a espera progressiva padrão.

Falhas são expostas como `OpenMeteoError`, mantendo a exceção original como causa.
Opener HTTP, espera e relógio são injetáveis para testes sem rede e sem espera real.
Não são necessários geocodificação, API key ou configurações secretas neste recorte.

## Uso com o caso de uso

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from weather_rpa.domain import Location
from weather_rpa.application import CollectWeather
from weather_rpa.adapters.open_meteo import OpenMeteoCollector
from weather_rpa.adapters.csv_artifact import CsvForecastExporter

location = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")
today = datetime.now(ZoneInfo(location.timezone)).date()
Path("output").mkdir(exist_ok=True)
result = CollectWeather(OpenMeteoCollector(), CsvForecastExporter()).execute(
    [location], today, today, "output/open_meteo.csv",
)
```

Esse exemplo faz uma chamada real; não integra a suíte unitária. O endpoint tem
horizonte limitado: períodos não suportados geram erro, sem migração automática para
API histórica. Os testes usam respostas locais e também cobrem o fluxo até o CSV.

Dados meteorológicos por [Open-Meteo](https://open-meteo.com/), disponibilizados sob
CC BY 4.0. A modalidade aberta tem limites e se destina a uso não comercial. Ao
publicar os dados, preserve a atribuição e informe a normalização de nomes/campos.

Referências oficiais: [API](https://open-meteo.com/en/docs),
[termos e limites](https://open-meteo.com/en/terms).
