# University Program Scraper and Analyser

This project automates collecting and analysing data science program information from universities.

## Project Pipeline

1. Scrape university ranking websites for top schools
2. Extract the root website URL for each university 
3. Locate the data science course pages within each university site
4. Store basic program data in a Notion database
5. Use FireCrawl to extract detailed program information from course pages
6. Process the raw content with Gemini AI to generate concise program summaries
7. Update the Notion database with the detailed summaries

## Features

- Automated web scraping of university rankings
- Smart detection of program-specific pages
- Integration with Notion API for data storage
- FireCrawl API integration for efficient content extraction
- Gemini AI integration for natural language processing of program details
- Asynchronous processing for improved performance

## Technologies

- Python
- FastAPI
- Notion API
- FireCrawl API
- Google Gemini AI
- AsyncIO

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file with your API keys:

```
NOTION_API_KEY=your_notion_api_key
FIRECRAWL_API_KEY=your_firecrawl_api_key
GEMINI_API_KEY=your_gemini_api_key
NOTION_DATABASE_ID=your_notion_database_id
```

## Usage

```bash
python main.py
```

## License

MIT