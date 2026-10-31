# Weather RPA — desafio btime

Projeto Python para coleta meteorológica via API Open-Meteo e scraping do
Climatempo, com arquitetura hexagonal. Implementação original a partir do
contrato do desafio; referências externas são usadas apenas para estudo conceitual.

## Estado desta etapa

O primeiro PR contém somente domínio, contrato dos dados e testes unitários.
Ainda não há coletores, CLI, exportação ou validação de CSV implementados.
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

## Decisões

- O domínio usa modelos imutáveis e não conhece HTTP, HTML ou CSV.
- `Location` é um objeto de valor, sem cadastro ou persistência separada.
- `location_id` serve à correlação interna, inclusive em execuções com várias cidades.
- O CSV exportará nome, UF, coordenadas e fuso; não exportará `location_id` e não
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

1. Exportação CSV e validação do artefato contra contrato versionado.
2. Portas e caso de uso compartilhado.
3. Adaptador Open-Meteo.
4. Adaptador Climatempo, começando com HTTP e BeautifulSoup.
5. CLI, handlers e exemplos reais de saída.

Cada etapa inclui testes determinísticos. Transporte, seletores e interpretação
do HTML serão separados. Verificações online serão independentes da suíte unitária.
