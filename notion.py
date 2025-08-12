import os
from notion_client import Client
from dotenv import load_dotenv
from typing import Dict, Optional

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_API_KEY)
database_id = NOTION_DATABASE_ID

def create_university_entry(data: Dict) -> Optional[Dict]:
    """Creates a new entry (page) in the Notion database."""
    try:
        new_page = notion.pages.create(
            parent={"database_id": database_id},
            properties={
                "Name": {"title": [{"text": {"content": data.get("name", "")}}]},
                "Official Website": {"url": data.get("url")},
                "State": {"rich_text": [{"text": {"content": data.get("state", "")}}]}
            }
        )
        return new_page
    except Exception as e:
        print(f"Error creating Notion page: {e}")
        return None

def find_university_entry(university_name: str) -> Optional[Dict]:
    """Searches for an existing entry in the Notion database by university name."""
    try:
        response = notion.databases.query(
            database_id=database_id,
            filter={
                "property": "Name",
                "title": {
                    "equals": university_name
                }
            }
        )
        if response["results"]:
            return response["results"][0]
        return None
    except Exception as e:
        print(f"Error finding Notion page: {e}")
        return None

def update_university_entry(page_id: str, content) -> bool:
    """Updates an existing Notion page with content."""
    try:
        notion.pages.update(
            page_id=page_id,
            children=content
        )
        return True
    except Exception as e:
        print(f"Error updating Notion page: {e}")
        return False