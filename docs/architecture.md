# Portas e caso de uso compartilhado

## Dependências

O domínio contém os valores e as invariantes de cada previsão. A aplicação depende
do domínio e define as portas necessárias. Os adaptadores implementam os contratos;
a aplicação não importa adaptadores, bibliotecas HTTP, HTML ou schema CSV.

As portas em `application/ports.py` usam `typing.Protocol`: conformidade estrutural,
sem obrigar os adaptadores a herdar uma classe base. Elas documentam o contrato e
permitem análise estática; não são verificações automáticas de tipo em runtime.
O caso de uso valida explicitamente os registros recebidos na fronteira da coleta.

| Porta | Contrato |
| --- | --- |
| `ForecastCollector` | `source` e `collect(location, start_date, end_date)` retornando previsões normalizadas |
| `ForecastExporter` | `export(forecasts, destination)` publica o artefato validado e retorna o total |
| `ForecastArtifactValidator` | `validate(path)` relê o artefato e retorna o total validado ou lança erro |

`CsvForecastExporter` e `CsvArtifactValidator` atendem estruturalmente às respectivas
portas. O exportador aceita um validador injetado; sem argumento, usa o validador CSV
existente. A validação acontece antes da substituição do destino. O caso de uso não
repete a validação após a publicação, pois isso detectaria erros tarde demais.

## Solicitação e cobertura

`CollectWeather.execute(locations, start_date, end_date, destination)` recebe:

- Um iterável não vazio de localidades já normalizadas.
- Datas explícitas, incluindo início e fim. Nenhuma data é inferida do relógio.
- Um destino cujo diretório pai já existe.

Cada execução usa um único coletor/fonte. Os handlers de API e scraping
selecionam o adaptador e reutilizam o mesmo caso de uso. Não há fallback automático
entre fontes nem interseção silenciosa de períodos disponíveis.

Antes de coletar, a aplicação rejeita datas inválidas/invertidas e localidades com
IDs internos repetidos ou com os mesmos nome, UF, coordenadas e fuso. As datas são
interpretadas como dias civis em cada localidade, conforme o contrato de domínio.

O coletor deve retornar exatamente um `DailyForecast` por dia solicitado, com a mesma
localidade (incluindo a referência interna) e fonte. A aplicação rejeita datas extras,
repetidas ou ausentes e valores que não sejam previsões. Limitações do horizonte das
fontes deverão gerar erro, não encurtar a solicitação sem aviso.

Todas as localidades são coletadas e verificadas antes de uma única exportação.
A ordem das localidades solicitadas é preservada; as previsões de cada uma são
ordenadas por data. A coleta é sequencial e mantida em memória, adequada ao escopo
de cidades e períodos curtos deste mini-projeto.

## Sucesso e falhas

O retorno `CollectionResult` contém `destination` (`Path`), `record_count` e
`location_count`, somente após a conclusão da exportação.

- Solicitação inválida: `ValueError`, antes de chamar o coletor ou exportador.
- Registros/cobertura inesperados: `CollectionError`, antes da exportação.
- Erros de transporte, leitura de iteráveis, validação e armazenamento: propagados.

O caso de uso emite logs de início e publicação pelo logging padrão, sem configurar
handlers globais. A CLI configura logs e converte falhas em mensagens e códigos de saída.

## Composição

Os handlers compõem os coletores concretos com o caso de uso e o exportador:

```python
from weather_rpa.application import CollectWeather
from weather_rpa.adapters.csv_artifact import CsvForecastExporter, CsvArtifactValidator

exporter = CsvForecastExporter(validator=CsvArtifactValidator())
use_case = CollectWeather(collector=collector, exporter=exporter)
result = use_case.execute(locations, start_date, end_date, destination)
```

`collector`, localidades, datas e destino são fornecidos pelos handlers e pela CLI.
A configuração padrão é empacotada e pode ser substituída por um JSON local.
`main.py`, `collect_api.py`, `collect_scraping.py`, a execução por módulo e os comandos
instalados convergem para a mesma CLI, sem duplicar as regras do caso de uso.
Os testes usam coletores/exportadores falsos e arquivos temporários para verificar
a integração local com CSV, sem chamadas externas.
