# Web Privacy Crawler

A privacy analysis tool for measuring and comparing privacy practices across websites. This crawler evaluates websites based on their third-party domain usage, tracking requests, cookie behavior, and consent mechanisms.

## Features

- Crawls websites and their internal pages to collect privacy metrics
- Detects tracking requests using domain matching, URL path analysis, and query parameter detection
- Analyzes cookies set before and after consent banner interaction
- Calculates a comprehensive privacy score based on multiple factors
- Generates rankings based on privacy practices

## Usage

```
python crawler.py -l sites.txt --privacy_analysis --consent_mode accept
```

## Parameters

- `-l, --site_list`: Path to text file containing sites to crawl
- `--consent_mode`: How to handle consent banners (accept, reject, or none)
- `--privacy_analysis`: Run privacy analysis

## Output

The script generates two output files:
- `privacy_ranking.csv`: A CSV file with privacy scores and metrics for each site
- `privacy_analysis_results.json`: A detailed JSON file with complete analysis results