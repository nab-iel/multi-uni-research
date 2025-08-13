from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import Dict, Optional, Literal, List
from google import genai
from google.genai import types
from dotenv import load_dotenv
from firecrawl import FirecrawlApp, ScrapeOptions
from serpapi import GoogleSearch
from notion import create_university_entry, find_university_entry, update_university_entry, get_all_university_entries
import os
import json
import requests
import re
import asyncio
import tempfile

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
SERP_API_KEY = os.getenv("SERP_API_KEY")

fast_app = FastAPI()
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
firecrawl_app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

class University(BaseModel):
    name: str
    url: str = None
    country: str = None
    state: str = None
    acceptance_rate: str = None
    average_sat: str = None
    average_act: str = None
    net_price: str = None
    receiving_aid: str = None
    enrollment: str = None
    founded: str = None
    tuition: dict = None

class RichTextContent(BaseModel):
    content: str

class RichText(BaseModel):
    type: Literal["text"] = "text"
    text: RichTextContent

class NotionBlockContent(BaseModel):
    rich_text: List[RichText]

class NotionBlock(BaseModel):
    object: Literal["block"] = "block"
    type: Literal["paragraph", "heading_2", "link_preview"]
    paragraph: Optional[NotionBlockContent] = None
    heading_2: Optional[NotionBlockContent] = None
    link_preview: Optional[NotionBlockContent] = None

def search_for_program_page(university_domain: str) -> str:
    """
    Uses SerpApi to perform a targeted Google search for a university's
    Data Science Master's program page and returns the most relevant URL.
    """
    try:
        query = f'site:{university_domain} "data science master\'s"'
        print(f"Searching with SerpApi for: {query}")

        params = {
            "engine": "google",
            "q": query,
            "api_key": SERP_API_KEY
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        # Extract the first organic result's link, which should be the most relevant.
        if "organic_results" in results and len(results["organic_results"]) > 0:
            program_url = results["organic_results"][0]["link"]
            return program_url

        print("No organic search results found.")
        return None

    except Exception as e:
        print(f"Error during SerpApi search: {e}")
        return None

def scrape_university_details(edurank_url: str) -> Dict:
    """
    Scrapes a university page for specific details.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(edurank_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        details = {}

        # 1. Extract the Official Website URL
        website_tag = soup.find('dt', string=re.compile(r'Website', re.IGNORECASE))
        if website_tag:
            website_link_tag = website_tag.find_next_sibling('dd').find('a')
            if website_link_tag:
                details['url'] = website_link_tag.get('href').replace('?from=edurank.org', '')

        # 2. Extract Tuition Information
        tuition_table = soup.find('table', class_='table-responsive-md')
        if tuition_table:
            tuition_data = {}
            rows = tuition_table.find('tbody').find_all('tr')
            for row in rows:
                program_name = row.find('td').get_text(strip=True) if row.find('td') else None
                if program_name and "Graduate" in program_name:
                    tuition_cells = row.find_all('td')
                    if len(tuition_cells) > 2:
                        tuition_data['domestic_tuition'] = tuition_cells[1].get_text(strip=True)
                        tuition_data['international_tuition'] = tuition_cells[2].get_text(strip=True)

            details['tuition'] = tuition_data

        return details

    except requests.exceptions.RequestException as e:
        print(f"Error fetching page {edurank_url}: {e}")
        return {}
    except AttributeError:
        print(f"Could not find required information on page: {edurank_url}. HTML structure may have changed.")
        return {}
    except Exception as e:
        print(f"An unexpected error occurred during details scraping for {edurank_url}: {e}")
        return {}

def get_program_details_with_firecrawl(official_url: str) -> Dict:
    """
    Uses Firecrawl to find and scrape the relevant program page, then uses
    Gemini for structured extraction.
    """
    try:
        print(f"Crawling {official_url} for 'data science masters' program.")
        crawl_result = firecrawl_app.crawl_url(
            official_url,
            scrape_options=ScrapeOptions(
                formats=["markdown"],
                maxAge=3600000,
                only_main_content=True,
                block_ads=True,
                parse_pdf=True
            ),
            max_depth=15,
            limit=5,
            ignore_sitemap=False,
            poll_interval = 30
        )
        print("Firecrawl API call completed.")

        if not crawl_result or not crawl_result.data:
            return {"error": "Firecrawl could not find a relevant page."}

        combined_markdown = "\n\n---\n\n".join(
            [item.markdown for item in crawl_result.data if hasattr(item, "markdown") and item.markdown]
        )

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as temp_file:
            temp_file.write(combined_markdown)
            temp_path = temp_file.name

        print(f"Combined markdown saved to temporary file: {temp_path}")
        return {"markdown_path": temp_path}
    except Exception as e:
        print(f"An error occurred: {e}")
        return {"error": str(e)}

def create_program_summaries_with_gemini(relevant_page_content):
    if len(relevant_page_content) > 30000:
        print(f"Large markdown content detected ({len(relevant_page_content)} chars).")
        paragraphs = relevant_page_content.split("\n\n")
        chunked_content = ""
        for p in paragraphs:
            if len(chunked_content) + len(p) + 2 > 30000:
                break
            chunked_content += p + "\n\n"
        relevant_page_content = chunked_content.strip()

    prompt = """
                You are an expert academic researcher. Your task is to analyze the provided text about a university program and extract specific details. The information should be structured as a JSON array of Notion API blocks following the exact format specified below.

                Extract the following information and format it as Notion blocks:
                - **program_name**: The full name of the Master's program (e.g., "Master of Science in Data Science") - format as heading_2
                - **admission_requirements**: Key requirements - format each requirement as a separate paragraph block
                - **core_courses**: Key or core courses in the curriculum - format each course as a separate paragraph block  
                - **location**: The campus or city where the program is located - format as paragraph

                If a piece of information is not found, omit those blocks from the output.

                **Required JSON Structure:**
                Your response must be a JSON array following this exact Notion API format:

                ```json
                [
                    {{
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Program name here"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Location"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Location information"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Admission Requirements"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "First admission requirement"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Second admission requirement"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Course Curriculum"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "First core course"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Second core course"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Tuition Information"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Tuition cost for international students"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Scholarship"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Scholarship opportunities"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Degree Length"}}}}]
                        }}
                    }},
                    {{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {{
                            "rich_text": [{{"type": "text", "text": {{"content": "Degree Length"}}}}]
                        }}
                    }}
                ]
                ```

                **Block Types:**
                - For heading_2: use "heading_2" type with content in the "heading_2" property
                - For heading_3: use "heading_3" type with content in the "heading_3" property
                - For paragraphs: use "paragraph" type with content in the "paragraph" property
                - Each block must have "object": "block"
                - All text content goes inside rich_text array with the nested structure shown

                Ensure the output is valid JSON that strictly follows the Notion API block format. Limit total word count to under 4000")
                """

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                response_mime_type="application/json",
                response_schema=list[NotionBlock],
                temperature=0.2,
            ),
            contents=relevant_page_content
        )

        print(f"Gemini API call successful. Response length: {len(response.text)}")

        try:
            parsed_data = json.loads(response.text)
            return parsed_data
        except json.JSONDecodeError as e:
            print(f"Initial JSON parsing failed: {e}. Attempting to fix...")
            start_idx = response.text.find('[')
            end_idx = response.text.rfind(']') + 1

            if start_idx >= 0 and end_idx > start_idx:
                json_text = response.text[start_idx:end_idx]
                try:
                    parsed_data = json.loads(json_text)
                    return parsed_data
                except json.JSONDecodeError:
                    raise ValueError("Could not extract valid JSON from Gemini response")
            else:
                raise ValueError("Could not locate JSON array in Gemini response")

    except Exception as e:
        print(f"Error in Gemini processing: {e}")
        raise

@fast_app.get("/scrape-universities")
async def scrape_university_list(ranking_url: str):
    """
    This endpoint scrapes a ranking webpage for a list of universities and their URLs,
    then scrapes each university's profile for more details.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(ranking_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        university_list = []
        university_containers = soup.find_all('div', class_='block-cont pt-4 mb-4')

        for container in university_containers:
            university_data = {}
            edurank_url = None

            # 1. Extract the University Name and EduRank URL
            name_tag = container.find('h2').find('a')
            if name_tag:
                name_and_rank = name_tag.get_text(strip=True)
                university_data['name'] = re.sub(r'^\d+\.\s*', '', name_and_rank)
                edurank_url = name_tag.get('href')

            # 2. Extract Location (Country and State/Province) from the first page
            location_div = container.find('div', class_='uni-card__geo')
            if location_div:
                country_tag = location_div.find('a', href=re.compile(r'geo/us/|geo/ca/'))
                state_tags = location_div.find_all('a', href=re.compile(r'geo/[a-z-]+/'))

                if country_tag:
                    university_data['country'] = country_tag.get_text(strip=True)

                if len(state_tags) > 1:
                    state = state_tags[1].get_text(strip=True)
                    if state not in ["United States", "Canada"]:
                        university_data['state'] = state

                        if state not in ["Connecticut",
                                         "Maine",
                                         "Massachusetts",
                                         "New Hampshire",
                                         "Rhode Island",
                                         "Vermont",
                                         "New Jersey",
                                         "New York",
                                         "Pennsylvania"
                                        ]:
                            continue

            # 3. Extract other key data from the details list on the first page
            info_list = container.find('dl', class_='uni-card__info-list')
            if info_list:
                for dt in info_list.find_all('dt'):
                    key = dt.get_text(strip=True)
                    dd = dt.find_next_sibling('dd')
                    if dd:
                        value = dd.get_text(strip=True)
                        if key == "Acceptance Rate":
                            university_data['acceptance_rate'] = value
                        elif key == "Average SAT":
                            university_data['average_sat'] = value
                        elif key == "Average ACT":
                            university_data['average_act'] = value
                        elif key == "Net Price":
                            university_data['net_price'] = value
                        elif key == "Receiving Aid":
                            university_data['receiving_aid'] = value
                        elif key == "Enrollment":
                            university_data['enrollment'] = value
                        elif key == "Founded":
                            university_data['founded'] = value

            # 4. Scrape the individual university page for more details and merge
            if edurank_url:
                details_from_second_scrape = scrape_university_details(edurank_url)
                university_data.update(details_from_second_scrape)

            create_university_entry(university_data)
            university_list.append(University(**university_data))

        return university_list

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error fetching the page: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

@fast_app.get("/update-program-details")
async def update_program_details():
    """
    Fetches entries from Notion, scrapes program details, and updates the entries.
    """
    all_entries = get_all_university_entries()

    if not all_entries:
        return {"status": "complete", "message": "No entries found in Notion to process."}

    for entry in all_entries:
        try:
            page_id = entry.get("id")
            properties = entry.get("properties", {})

            name_property = properties.get("Name", {}).get("title", [])
            if not name_property:
                continue
            uni_name = name_property[0].get("text", {}).get("content")

            url_property = properties.get("Official Website", {})
            official_url = url_property.get("url")

            if not official_url:
                continue

            domain_match = re.search(r'https?://(?:www\.)?([^/]+)', official_url)
            if not domain_match:
                print(f"Could not extract domain from URL: {official_url}. Skipping.")
                continue

            domain = domain_match.group(1)

            program_url = search_for_program_page(domain)

            if program_url:
                properties_to_update = {
                    "Official Website": {
                        "url": program_url
                    }
                }
                update_university_entry(page_id, properties=properties_to_update)
            else:
                print(f"Could not find a specific program page for {uni_name} via search.")

        except Exception as e:
            uni_name_for_error = entry.get("properties", {}).get("Name", {}).get("title", [{}])[0].get("text", {}).get("content", "Unknown")
            print(f"An unexpected error occurred while processing {uni_name_for_error}: {e}")
            continue

    return {"status": "success", "message": "Finished processing all universities."}

@fast_app.get("/scrape-program-details")
async def scrape_program_details():
    all_entries = get_all_university_entries()

    if not all_entries:
        return {"status": "complete", "message": "No entries found in Notion to process."}

    for entry in all_entries:
        try:
            page_id = entry.get("id")
            properties = entry.get("properties", {})

            name_property = properties.get("Name", {}).get("title", [])
            if not name_property:
                continue

            url_property = properties.get("Official Website", {})
            official_url = url_property.get("url")

            if not official_url:
                continue

            firecrawl_result = get_program_details_with_firecrawl(official_url)

            if "error" in firecrawl_result:
                print(f"Error for {official_url}: {firecrawl_result['error']}")
                continue

            markdown_path = firecrawl_result.get("markdown_path")

            update_university_entry(page_id, markdown_path=markdown_path)

            await asyncio.sleep(60)

        except Exception as e:
            uni_name_for_error = entry.get("properties", {}).get("Name", {}).get("title", [{}])[0].get("text", {}).get(
                "content", "Unknown")
            print(f"An unexpected error occurred while processing {uni_name_for_error}: {e}")
            continue

    return {"status": "success", "message": "Finished processing all universities."}

@fast_app.get("/create-program-summaries")
async def create_program_summaries():
    all_entries = get_all_university_entries()

    if not all_entries:
        return {"status": "complete", "message": "No entries found in Notion to process."}

    for entry in all_entries:
        try:
            page_id = entry.get("id")
            properties = entry.get("properties", {})
            markdown_files = properties.get("Markdown", {}).get("files", [])

            if not markdown_files or len(markdown_files) == 0:
                print(f"No markdown files found for entry. Skipping.")
                continue

            file_url = markdown_files[0].get("file", {}).get("url")

            if not file_url:
                print(f"No valid file URL found. Skipping.")
                continue

            response = requests.get(file_url)
            if response.status_code != 200:
                print(f"Failed to download markdown file: {response.status_code}")
                continue

            markdown_content = response.text
            content = create_program_summaries_with_gemini(markdown_content)

            update_university_entry(page_id, content=content)
            await asyncio.sleep(10)
        except Exception as e:
            uni_name_for_error = entry.get("properties", {}).get("Name", {}).get("title", [{}])[0].get("text", {}).get(
                "content", "Unknown")
            print(f"An unexpected error occurred while processing {uni_name_for_error}: {e}")
            continue

    return {"status": "success", "message": "Finished processing all universities."}