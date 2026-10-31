# Weather RPA — desafio btime

Projeto Python para coleta meteorológica via API Open-Meteo e scraping do
Climatempo, com arquitetura hexagonal. Implementação original a partir do
contrato do desafio; referências externas são usadas apenas para estudo conceitual.

## Estado desta etapa

Estão implementados o domínio, a exportação CSV e a validação do artefato relido
do disco, com contrato tabular versionado e testes unitários. Também estão disponíveis
as portas e o caso de uso compartilhado para múltiplas localidades e período explícito.
Os coletores Open-Meteo e Climatempo estão implementados. A CLI e os handlers
ainda estão pendentes.
Não é necessário acesso à internet para executar os testes.

## Ambiente

Python 3.11 ou superior. No Linux, é necessária a base de fusos IANA do sistema.
No Windows, a instalação do projeto inclui `tzdata` para disponibilizar essa base.

Instalação em ambiente virtual:

```bash
python -m venv .venv
# Linux: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

Também é possível executar os testes sem instalar o projeto, com `src` no caminho
 de importação (e a base de fusos já disponível):

```bash
# Linux / WSL
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

```powershell
# PowerShell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

## Integração contínua

O workflow `.github/workflows/ci.yml` executa os testes unitários em cada push,
pull request e acionamento manual pelo GitHub Actions. A matriz cobre Python
3.11 e 3.12 no Ubuntu e Windows, incluindo a dependência de fusos do Windows.

Cada job instala o projeto com `python -m pip install .` e executa
`python -m unittest discover -s tests -v`. A instalação requer acesso ao índice
de pacotes; os testes não consultam sites ou APIs. Falhas de instalação ou testes
fazem o job falhar. Execuções anteriores do mesmo evento e referência são
canceladas quando uma nova execução começa.

O workflow publica o resultado das verificações. Torná-las obrigatórias para
merge depende da configuração de proteção da branch no GitHub.

## Exportação e validação de CSV

`CsvForecastExporter.export(forecasts, destination)` recebe um iterável de
`DailyForecast`, grava UTF-8 com cabeçalho e retorna o total de registros. O diretório
pai deve existir. A exportação relê e valida um arquivo temporário no mesmo diretório
antes de substituir o destino. Falhas de entrada, validação ou publicação preservam
um arquivo anterior e removem o temporário.

`CsvArtifactValidator.validate(path)` também pode validar um CSV já existente.
Conteúdo inválido gera `ArtifactValidationError`; erros de acesso continuam sendo
`OSError`. Arquivo vazio, somente cabeçalho e duplicidades são rejeitados.

O schema empacotado em `src/weather_rpa/schemas/daily_forecast.schema.json` usa um
subconjunto de [Table Schema](https://specs.frictionlessdata.io/table-schema/).
O validador é específico deste contrato, não implementa a especificação completa.
Confira o [contrato e exemplo de uso](docs/data-contract.md).

## Caso de uso compartilhado

`CollectWeather` recebe um coletor e um exportador pelas portas da aplicação.
Verifica a cobertura completa por cidade e dia antes de exportar uma única vez.
API e scraping usarão o mesmo fluxo, mudando apenas o coletor injetado.

O exportador CSV aceita um `ForecastArtifactValidator`, mantendo o validador atual
como padrão. Veja os contratos, a política de falhas e a composição em
[arquitetura](docs/architecture.md).

## Open-Meteo

O adaptador consulta mínima, máxima e precipitação diária com unidades e fuso
explícitos, normaliza os registros e reutiliza o caso de uso e exportador existentes.
Possui timeout, retentativas limitadas e respeito a `Retry-After`. Os testes simulam
HTTP e não dependem da disponibilidade da API. Veja [uso e limitações](docs/open-meteo.md).

Dados por [Open-Meteo](https://open-meteo.com/), sob CC BY 4.0, normalizados para o
contrato deste projeto. Consulte os [termos](https://open-meteo.com/en/terms) antes
de usar o serviço em outros contextos.

## Scraping Climatempo

O adaptador usa HTTP e BeautifulSoup na página de 15 dias, com seletores separados
da extração e normalização. Cruza as datas completas do calendário com os cards
diários e confere cidade e UF antes de aceitar os valores. Não usa dados horários
ou probabilidade de chuva como acumulado diário.

Veja [configuração, uso e limitações](docs/climatempo.md). Os testes usam HTML
sintético local, sem depender da disponibilidade ou do layout atual do site.

## Decisões

- O domínio usa modelos imutáveis e não conhece HTTP, HTML ou CSV.
- `Location` é um objeto de valor, sem cadastro ou persistência separada.
- `location_id` serve à correlação interna, inclusive em execuções com várias cidades.
- O CSV exporta nome, UF, coordenadas e fuso; não exporta `location_id` e não
  dependerá de um cadastro externo para identificar a localidade.
- `collected_at` deve ter fuso e é normalizado para UTC.
- `forecast_date` representa o dia civil no fuso IANA da localidade.
- Precipitação é acumulado diário em mm; ausência e zero são distintos.
- Valores inválidos geram `ValueError`; não são substituídos silenciosamente.
- Identificadores específicos dos provedores ficarão nos adaptadores.

O [contrato dos dados](docs/data-contract.md) define os campos e as próximas
etapas de validação. Os CSVs de entrega serão versionados; `output/` não é ignorado.
A escolha do Climatempo não confirma autorização de redistribuição de seus dados.

## Próximos PRs

1. CLI, handlers e exemplos reais de saída.

Cada etapa inclui testes determinísticos. Transporte, seletores e interpretação
do HTML serão separados. Verificações online serão independentes da suíte unitária.
