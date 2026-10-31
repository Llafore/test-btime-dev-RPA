# Adaptador de scraping Climatempo

`ClimatempoCollector` implementa estruturalmente `ForecastCollector`, com fonte
`climatempo`. Começa com HTTP e BeautifulSoup; navegador não é necessário no layout
inspecionado. Não consulta APIs internas, não executa JavaScript e não contorna CAPTCHA.

## Responsabilidades

- `climatempo_http.py`: obtém HTML público com timeout e retentativas limitadas.
- `ClimatempoSelectors`: configura os seletores dos componentes, sem fazer requisições.
- `climatempo_parser.py`: extrai e normaliza dados dentro de cada bloco diário.
- `climatempo.py`: resolve a página configurada e combina transporte e parser.

O coletor recebe um mapa de `location_id` para `ClimatempoPage(city_code, slug)`.
Código e slug são específicos do provedor e não entram no domínio ou no CSV.
Não construímos slugs a partir do nome nem tratamos o ID interno como código do site.
A cidade e UF do título são comparadas à localidade solicitada, normalizando espaços,
caixa e acentos para a comparação. As coordenadas de saída são as da localidade
configurada; não são geocodificadas ou confirmadas pela página.

## Datas e medidas

O layout atual contém 15 cards diários e um componente de calendário cujo atributo
HTML `data-infos` declara datas completas ISO 8601. O parser cruza a quantidade,
a ordem consecutiva das datas e o dia visível de cada card. Não infere mês ou ano
pelo relógio e não usa os dados meteorológicos do JSON de calendário como substitutos
dos valores visíveis dos cards.

Os valores são extraídos somente do resumo diário de cada card solicitado:

- Mínima e máxima com símbolo de graus, interpretadas em Celsius no portal brasileiro.
- Campo de chuva com unidade `mm`, mapeado para `precipitation_mm`.
- A probabilidade em `%`, sensações térmicas e valores horários são ignorados.

Espaços, decimal com vírgula e sinal de menos Unicode são normalizados. Campo de
chuva presente com marcador vazio, `-`, `—`, `Sem dados` ou `indisponível` vira `None`.
Zero permanece zero. Elemento ausente ou ambíguo gera erro de estrutura; não vira
silenciosamente ausência. Valores inválidos são rejeitados pelas regras do domínio.

A data é a declarada pela página. O fuso vem da localidade configurada, pois o card
não declara offset de início/fim. O campo publicado de chuva é tratado como acumulado
do dia indicado pelo portal; seu intervalo operacional exato não foi confirmado em
documentação técnica. Valores das duas fontes podem diferir em modelo e atualização.

São interpretadas medidas somente dentro do período solicitado. Ausência de cobertura
é detectada pelo caso de uso compartilhado; não há fallback para outra fonte. Dados
estruturais inconsistentes entre calendário e cards impedem a coleta, inclusive para
evitar associação a uma data errada. Mudanças de layout exigem revisão dos seletores.

## Transporte e contingências

Defaults: timeout de 15 segundos por operação de rede, 3 tentativas e esperas de
1 e 2 segundos. HTTP 429, 500, 502, 503 e 504 e falhas transitórias são retentados.
`Retry-After` em segundos ou data HTTP é respeitado; acima de 60 segundos configuráveis,
a operação encerra sem tentativa antecipada. Não há espera após a última tentativa.

403 e demais erros permanentes encerram imediatamente. Conteúdo não HTML ou UTF-8
inválido gera erro. Desafios conhecidos de acesso no título/formulário geram erro de
parsing sem retentativa automática. Referências comuns a captcha em scripts não são
consideradas bloqueio. Não há rotação de identidade, proxies ou resolução de CAPTCHA.
Erros são expostos como `ClimatempoError` e preservam a causa original.

## Uso

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from weather_rpa.domain import Location
from weather_rpa.application import CollectWeather
from weather_rpa.adapters.climatempo import ClimatempoCollector, ClimatempoPage
from weather_rpa.adapters.csv_artifact import CsvForecastExporter

location = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")
collector = ClimatempoCollector({"sp": ClimatempoPage(558, "saopaulo-sp")})
today = datetime.now(ZoneInfo(location.timezone)).date()
Path("output").mkdir(exist_ok=True)
result = CollectWeather(collector, CsvForecastExporter()).execute(
    [location], today, today, "output/climatempo.csv",
)
```

O exemplo acessa o site real. A suíte usa HTML sintético mínimo criado para testar
comportamentos, não uma cópia da página inteira. Cobre normalização, escopo, datas,
ausência versus zero, mudança de seletores, bloqueios, falhas e integração local com CSV.
Disponibilidade e compatibilidade atuais do layout são verificações separadas da suíte.

Fonte: [página pública de São Paulo](https://www.climatempo.com.br/previsao-do-tempo/15-dias/cidade/558/saopaulo-sp).
