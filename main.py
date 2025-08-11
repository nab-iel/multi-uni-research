from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import Dict
from google import genai
from dotenv import load_dotenv
import os
import requests
import re

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = FastAPI()
client = genai.Client(api_key=GEMINI_API_KEY)

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

@app.get("/scrape-universities")
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

            university_list.append(University(**university_data))

        return university_list

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error fetching the page: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")