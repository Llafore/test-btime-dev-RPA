# Weather RPA — desafio btime

Dois scripts Python coletam previsão diária de clima: API pública Open-Meteo e
web scraping do Climatempo com HTTP e BeautifulSoup. Ambos usam o mesmo caso de
uso e geram CSVs com o mesmo contrato, validados antes da publicação.

## Instalação

Python 3.11 ou superior. Execute os comandos a partir da raiz do repositório.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

No Windows/PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install .
```

Não há chave de API ou navegador obrigatório. A instalação requer internet para
obter dependências; as coletas reais também requerem internet. Linux precisa da
base IANA de fusos do sistema; no Windows, o pacote instala `tzdata`.
Para desenvolvimento, use `python -m pip install -e .`.

## Execução

Por padrão, coleta **hoje em São Paulo**, no fuso `America/Sao_Paulo`:

```bash
python main.py --api
python main.py --scraping
```

Os dois scripts independentes também atendem à entrega do desafio:

```bash
python collect_api.py
python collect_scraping.py
```

Alternativas após instalar o pacote:

```bash
python -m weather_rpa --api
weather-rpa --scraping
weather-api
weather-scraping
```

Os modos `--api` e `--scraping` são mutuamente exclusivos. Os scripts específicos
já selecionam o modo, aceitando os demais argumentos diretamente.

Para um período explícito, incluindo as duas datas:

```bash
python main.py --api --start-date 2026-10-31 --end-date 2026-11-02 --output output/api_periodo.csv
python collect_scraping.py --start-date 2026-10-31 --end-date 2026-11-02 --output output/scraping_periodo.csv
```

Substitua as datas por um período coberto atualmente pelas fontes. Omitir `--end-date`
seleciona somente o dia inicial; fornecer apenas a data final é erro. Não há fallback
para API histórica nem redução silenciosa do período para os dias disponíveis.

| Argumento | Comportamento |
| --- | --- |
| `--config caminho.json` | Configuração de localidades; padrão empacotado: São Paulo (`sp`) |
| `--location sp` | Seleciona um ID da configuração; repetível, padrão: todas as localidades |
| `--start-date YYYY-MM-DD` | Data inicial; padrão: hoje no fuso da localidade |
| `--end-date YYYY-MM-DD` | Data final inclusiva; padrão: inicial |
| `--output caminho.csv` | Destino; padrão: `output/open_meteo.csv` ou `output/climatempo.csv` |
| `--timeout 15` | Timeout por operação de rede, em segundos; não é prazo global |
| `--attempts 3` | Limite de tentativas HTTP, de 1 a 5 |
| `--verbose` | Logs detalhados, incluindo stack trace em falhas |
| `--help` | Ajuda sem executar coleta |

O diretório de saída é criado automaticamente. Cada execução substitui o arquivo
completo somente após validá-lo; erros preservam a saída anterior. Códigos de saída:
`0` sucesso, `1` erro de configuração/coleta/validação/gravação, `2` argumentos inválidos
e `130` interrupção pelo usuário. Logs vão para stderr; o resumo de sucesso, para stdout.

## Localidades configuráveis

O padrão está em `src/weather_rpa/config/locations.json`. Para personalizar, copie-o
para um JSON local e use `--config`. Estrutura:

```json
{
  "locations": [
    {
      "location_id": "sp",
      "name": "São Paulo",
      "state": "SP",
      "latitude": -23.55,
      "longitude": -46.63,
      "timezone": "America/Sao_Paulo",
      "climatempo": {"city_code": 558, "slug": "saopaulo-sp"}
    }
  ]
}
```

Adicione outras localidades à lista, com IDs e dados distintos. `climatempo` é
opcional para API e obrigatório nas localidades selecionadas para scraping: informe
o código e slug da página real. Não há geocodificação automática. Coordenadas e
fuso devem corresponder à cidade; o scraping confere nome e UF exibidos no portal.
Textos de configuração são aparados e UF é convertida para maiúsculas antes de
validar o domínio. Campos desconhecidos são rejeitados para detectar erros de digitação.

```bash
python main.py --api --config minhas_cidades.json --location sp
```

Para várias cidades, repita `--location` ou omita-o para usar todas. O período é comum
à execução. Se os fusos tiverem datas locais atuais diferentes, informe as datas
explicitamente. Uma cidade incompleta ou inválida impede a publicação da coleta inteira.

## Artefatos e arquitetura

O exportador grava um temporário, relê e valida o contrato, e só então substitui o
destino. O descriptor empacotado usa um subconjunto de Table Schema; o validador é
específico do projeto, sem implementar a especificação completa.

Arquitetura hexagonal: domínio independente, portas estruturais, caso de uso
compartilhado, adaptadores e handlers de composição. Implementação original a partir
do desafio; outros projetos foram consultados somente como referências conceituais.

- [Arquitetura e política de falhas](docs/architecture.md)
- [Contrato dos dados e validação CSV](docs/data-contract.md)
- [Open-Meteo: unidades, retentativas e restrições de fuso](docs/open-meteo.md)
- [Climatempo: seletores, extração e limitações](docs/climatempo.md)

## Testes e CI

```bash
python -m unittest discover -s tests -v
```

A suíte usa objetos falsos, HTTP simulado, HTML sintético e diretórios temporários.
Não consulta serviços externos. Cobre domínio, configuração, orquestração, transporte,
normalização, parsing, CLI, exportação e validação. Verificações online são separadas:
passar nos testes não comprova disponibilidade da fonte ou compatibilidade do layout atual.

O GitHub Actions executa instalação e testes em push, PR e acionamento manual, com
Python 3.11/3.12 em Ubuntu e Windows. Configuração em `.github/workflows/ci.yml`.
Tornar os checks obrigatórios depende da proteção de branch configurada no GitHub.

## Fontes

Dados por [Open-Meteo](https://open-meteo.com/), sob CC BY 4.0, com nomes e campos
normalizados para este contrato. O serviço aberto tem limites e é destinado a uso
não comercial; consulte os [termos](https://open-meteo.com/en/terms).
Scraping: [Climatempo](https://www.climatempo.com.br/). As fontes têm modelos,
horários de atualização e limitações distintos; seus valores não precisam coincidir.
