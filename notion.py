import os
from notion_client import Client
from notion_upload import notion_upload
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

def get_all_university_entries() -> list:
    """Fetches all entries from the Notion database, handling pagination."""
    try:
        all_results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = notion.databases.query(
                database_id=database_id,
                start_cursor=start_cursor
            )
            all_results.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
        return all_results
    except Exception as e:
        print(f"Error fetching all Notion pages: {e}")
        return []

def update_university_entry(page_id: str, properties: Optional[Dict] = None, content: Optional[list] = None, markdown_path: Optional[str] = None) -> bool:
    """Updates an existing Notion page with new properties and/or content."""
    try:
        update_args = {"page_id": page_id}
        if properties is not None:
            update_args["properties"] = properties
        if properties:
            notion.pages.update(**update_args)

        if markdown_path and os.path.exists(markdown_path):
            with open(markdown_path, "rb") as f:
                uploader = notion_upload(markdown_path, os.path.basename(markdown_path), NOTION_API_KEY)
                uploaded_file_ids = uploader.upload()
            notion.pages.update(
                page_id=page_id,
                properties={
                    "Markdown": {
                        "files": [
                            {
                                "name": f"program_details_{page_id}.md",
                                "type": "file_upload",
                                "file_upload": {
                                    "id": uploaded_file_ids
                                }
                            }
                        ]
                    }
                }
            )
            os.unlink(markdown_path)

        if content is not None:
            notion.blocks.children.append(
                block_id=page_id,
                children=content
            )
        return True
    except Exception as e:
        print(f"Error updating Notion page: {e}")
        return False