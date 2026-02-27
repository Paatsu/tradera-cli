# tradera-cli

Fast CLI for searching public Tradera listings from the terminal.

Designed for scripts, agents, and quick lookups with structured output.

## Install

From PyPI:

```bash
pip install tradera-cli
```

With `uv`:

```bash
uv tool install tradera-cli
```

With `pipx`:

```bash
pipx install tradera-cli
```

Upgrade:

```bash
pip install --upgrade tradera-cli
```

## Usage

### Search listings

```bash
tradera search "iphone"
tradera search "pokemon" --page 2 --page-size 20
tradera search "kamera" --sort AddedOn --format json
tradera search "klocka" --country SE --lang sv --format jsonl
tradera search "lego" --item-status Sold --format json
tradera search "lego" --condition "Oanvänt" --format json
tradera search "lego" --item-type FixedPrice --from-price 100 --to-price 500
tradera search "lego" --allowed-buyer-regions eu --counties Stockholm Uppsala
tradera search "lego city" --search-type ExactSearch
```

### Get item details

```bash
tradera item 717898129
tradera item 717898129 --format json
tradera item "https://www.tradera.com/item/340186/717885898/iphone-12-pro"
```

### Browse categories

```bash
tradera categories --level 1
tradera categories --level 2 --lang sv --format json
```

## Output formats

| Format | Description | Best for |
|---|---|---|
| `table` (default) | Human-readable table | Interactive terminal use |
| `json` | Pretty JSON object | `jq`, scripts, integrations |
| `jsonl` | One JSON object per line | Streaming/log pipelines |

## Common options

Search command (`tradera search`) supports:

| Option | Description |
|---|---|
| `--page` | Page number (default: `1`) |
| `--page-size` | Results per page (default: `50`) |
| `--sort` | Sort mode (default: `Relevance`) |
| `--lang` | Language code (default: `sv`) |
| `--country` | Shipping country code (default: `SE`) |
| `--item-status` | Filter by item status: `Active`, `Sold`, `Unsold` |
| `--condition` | Filter by condition: `Oanvänt`, `Mycket gott skick`, `Gott skick`, `Okej skick`, `Defekt` |
| `--item-type` | Filter by listing type: `All`, `Auction`, `FixedPrice`, `ContactOnly` |
| `--from-price` | Minimum price |
| `--to-price` | Maximum price |
| `--allowed-buyer-regions` | Buyer region filter: `sweden`, `eu`, `international` |
| `--counties` | Pickup counties, passed as one or more values, for example `Stockholm Uppsala` |
| `--search-type` | Search mode. Current supported value: `ExactSearch` |
| `--no-translate` | Disable automatic translation preference |
| `--format` | Output format: `table`, `json`, `jsonl` |

## Development

From source:

```bash
git clone https://github.com/Paatsu/tradera-cli.git
cd tradera-cli
pip install -e .[dev]
```

Build distributions:

```bash
python -m build
```

Check the package metadata before upload:

```bash
python -m twine check dist/*
```

Run tests:

```bash
pytest -q
```

## Agent integration

Examples for automation:

```bash
# Take first 3 listings as JSON
tradera search "iphone" --format json | jq '.items[:3]'

# Stream listings line-by-line
tradera search "lego" --format jsonl

# Pull one item as machine-readable JSON
tradera item 717898129 --format json
```

## Notes

- Uses web endpoints from Tradera's frontend.
- Anonymous client token is fetched automatically when needed.
- Endpoint behavior can change over time.
