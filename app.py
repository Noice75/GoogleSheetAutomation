import time
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import logging
import json
import threading
from urllib.parse import urlparse
from crawler import setup_driver, search, get_base_url
from article_processor import scrape_and_check_article
import requests

# Configure logging
def setup_logging():
    # Create logs directory if it doesn't exist
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Configure root logger with both file and console handlers
    log_file_path = os.path.join(logs_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log')
    
    # Set up handlers
    file_handler = logging.FileHandler(log_file_path)
    console_handler = logging.StreamHandler()
    
    # Set formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove existing handlers if any
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return root_logger

# Initialize logging
logger = setup_logging()
logger.info("Logging initialized. Logs are being saved to file and displayed in console.")

app = Flask(__name__)
CORS(app)  # Enable CORS for all domains

# Google Sheets API setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = 'credentials.json'

# Global variables for crawler
crawler_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current": "",
    "results": [],
    "stop_flag": False,
    "start_time": None,
    "elapsed_time": 0,
    "estimated_time_remaining": None
}

# Global file lock to prevent concurrent writes
file_lock = threading.Lock()

def load_config():
    """Load the sheet ID from config.json, create if it doesn't exist"""
    if not os.path.exists('config.json'):
        # Create config file with empty sheet ID
        with open('config.json', 'w') as f:
            json.dump({"sheet_id": ""}, f)
        return ""
    
    with open('config.json', 'r') as f:
        config = json.load(f)
        return config.get('sheet_id', "")

def save_config(sheet_id):
    """Save the sheet ID to config.json"""
    with open('config.json', 'w') as f:
        json.dump({"sheet_id": sheet_id}, f)

def update_sheet_connection(new_sheet_id):
    """Update the global sheet variable with new sheet ID"""
    global sheet
    if new_sheet_id:
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(new_sheet_id)
    else:
        sheet = None

# Initialize sheet variable
SHEET_ID = load_config()
if SHEET_ID:
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
    except Exception as e:
        logger.error(f"Error connecting to sheet: {str(e)}")
        sheet = None
else:
    sheet = None

# Helper function to reconnect if token expires
def reconnect_if_needed():
    global client, sheet
    try:
        # Try to access the sheet to check if credentials are still valid
        sheet.worksheets()
        return True
    except Exception as e:
        logger.warning(f"Connection error, attempting to reconnect: {str(e)}")
        try:
            # Reconnect
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SHEET_ID)
            logger.info("Reconnected to Google Sheets successfully")
            return True
        except Exception as reconnect_error:
            logger.error(f"Failed to reconnect: {str(reconnect_error)}")
            return False

# Load Sheet ID from config
def load_config():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            return config.get('sheet_id')
    except Exception as e:
        logger.error(f"Error loading config: {str(e)}")
        return None

def save_config(sheet_id):
    try:
        config = {'sheet_id': sheet_id}
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving config: {str(e)}")
        return False

# Update the global sheet variable
def update_sheet_connection(new_sheet_id):
    global sheet, SHEET_ID
    try:
        SHEET_ID = new_sheet_id
        sheet = client.open_by_key(SHEET_ID)
        return True
    except Exception as e:
        logger.error(f"Error connecting to new sheet: {str(e)}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204  # Suppress 404 for favicon requests

@app.route('/worksheets')
def list_worksheets():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheets = sheet.worksheets()
        worksheet_names = [ws.title for ws in worksheets]
        logger.info(f"Retrieved {len(worksheet_names)} worksheets")
        return jsonify({"worksheets": worksheet_names}), 200
    except Exception as e:
        logger.error(f"Error listing worksheets: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/sheet-info')
def sheet_info():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet("Sheet1")
        values = worksheet.get_all_values()
        headers = []
        if values:
            # The first row should be considered headers
            headers = values[0]
            data_rows = values[1:] if len(values) > 1 else []
        return jsonify({
            "headers": headers, 
            "row_count": len(values),
            "data_rows": len(data_rows) if 'data_rows' in locals() else 0
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving sheet info: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
# Add this new endpoint to your Flask application
@app.route('/get-sheet-id')
def get_sheet_id():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        # Return the sheet ID from the server
        return jsonify({
            "status": "success", 
            "sheet_id": SHEET_ID
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving sheet ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/add-link", methods=["POST"])
def add_link():
    try:
        data = request.json
        tab_name = data.get("category")
        link = data.get("link")
        summary = data.get("summary", "")
        date = data.get("date", datetime.today().strftime("%m/%d/%Y"))
        title = data.get("title", "")  # Get the title from the request
        publisher = data.get("publisher")  # Get publisher if provided
        force_add = data.get("force_add", False)  # Flag to override duplicate check
        
        if not tab_name or not link:
            return jsonify({"status": "error", "error": "Worksheet name and link are required"}), 400
            
        # Validate URL (basic validation)
        if not link.startswith(('http://', 'https://')):
            return jsonify({"status": "error", "error": "URL must start with http:// or https://"}), 400
        
        # Check if URL already exists in crawled_links.json (unless force_add is True)
        if not force_add:
            try:
                with file_lock:
                    if os.path.exists("crawled_links.json"):
                        try:
                            with open("crawled_links.json", "r") as f:
                                crawled_data = json.load(f)
                                # Only check for exact URL matches, not string in string
                                for item in crawled_data:
                                    if isinstance(item, dict) and item.get("url") == link:
                                        # Return as error to work with original UI
                                        return jsonify({
                                            "status": "error", 
                                            "error": f"This article already exists in the Google Sheet (added under {item.get('category', 'unknown')} category)"
                                        }), 400
                        except json.JSONDecodeError:
                            # If JSON is invalid, treat as empty or corrupted file
                            logger.warning("crawled_links.json is corrupted, treating as empty")
                            # Create a new file
                            with open("crawled_links.json", "w") as f:
                                json.dump([], f)
                        except Exception as e:
                            logger.error(f"Error checking crawled links: {str(e)}")
            except Exception as e:
                logger.error(f"Error acquiring file lock: {str(e)}")
        
        if not reconnect_if_needed():
            return jsonify({"status": "error", "error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet(tab_name)
        
        # Create HYPERLINK formula
        hyperlink_formula = f'=HYPERLINK("{link}", "{title}")'
        
        # Add the data row with HYPERLINK formula, placing Publisher before Date
        # Use empty string if publisher is None
        publisher_value = publisher if publisher else ""
        worksheet.append_row([hyperlink_formula, summary, publisher_value, date], value_input_option="USER_ENTERED")
        
        # Successfully added to sheet, now add to crawled_links.json
        append_link(link, publisher, tab_name)
            
        logger.info(f"Added link to worksheet '{tab_name}': {link[:50]}...")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error adding link: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/reset-sheet')
def reset_sheet():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet("Sheet1")
        # Clear the sheet
        worksheet.clear()
        # Add headers with Publisher before Date
        worksheet.append_row(["Link", "Summary", "Publisher", "Date"])
        logger.info("Reset Sheet1 with headers")
        return jsonify({"status": "Sheet reset with headers"}), 200
    except Exception as e:
        logger.error(f"Error resetting sheet: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get-worksheets')
def get_worksheets():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheets = sheet.worksheets()
        worksheet_names = [ws.title for ws in worksheets]
        logger.info(f"Retrieved {len(worksheet_names)} worksheets")
        return jsonify({"worksheets": worksheet_names}), 200
    except Exception as e:
        logger.error(f"Error getting worksheets: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/worksheet-data')
def get_worksheet_data():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({"error": "Worksheet name is required"}), 400
            
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet(name)
        values = worksheet.get_all_values()
        
        # Skip the header row if it exists
        rows = values[1:] if len(values) > 0 else []
        
        logger.info(f"Retrieved {len(rows)} rows from worksheet '{name}'")
        return jsonify({"status": "success", "rows": rows}), 200
    except Exception as e:
        logger.error(f"Error getting worksheet data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/create-worksheet', methods=["POST"])
def create_worksheet():
    try:
        data = request.json
        new_title = data.get('title')
        
        if not new_title:
            return jsonify({"error": "Worksheet title is required"}), 400
            
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        # Check if worksheet already exists
        existing_worksheets = [ws.title for ws in sheet.worksheets()]
        if new_title in existing_worksheets:
            return jsonify({"error": f"Worksheet '{new_title}' already exists"}), 400
            
        # Create new worksheet
        new_worksheet = sheet.add_worksheet(title=new_title, rows=1, cols=4)
        
        # Add headers to new worksheet with Publisher before Date
        new_worksheet.append_row(["Link", "Summary", "Publisher", "Date"])
        
        logger.info(f"Created new worksheet: '{new_title}'")
        return jsonify({"status": "success", "message": f"Worksheet '{new_title}' created"}), 201
    except Exception as e:
        logger.error(f"Error creating worksheet: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete-worksheet', methods=["POST"])
def delete_worksheet():
    try:
        data = request.json
        worksheet_name = data.get('name')
        
        if not worksheet_name:
            return jsonify({"error": "Worksheet name is required"}), 400
            
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        # Don't allow deleting the default Sheet1
        if worksheet_name.lower() == "sheet1":
            return jsonify({"error": "Cannot delete the default worksheet"}), 400
            
        # Find the worksheet by name
        worksheets = sheet.worksheets()
        worksheet_to_delete = None
        
        for ws in worksheets:
            if ws.title == worksheet_name:
                worksheet_to_delete = ws
                break
                
        if not worksheet_to_delete:
            return jsonify({"error": f"Worksheet '{worksheet_name}' not found"}), 404
            
        # Delete the worksheet
        sheet.del_worksheet(worksheet_to_delete)
        
        logger.info(f"Deleted worksheet: '{worksheet_name}'")
        return jsonify({"status": "success", "message": f"Worksheet '{worksheet_name}' deleted"}), 200
    except Exception as e:
        logger.error(f"Error deleting worksheet: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    try:
        if reconnect_if_needed():
            return jsonify({"status": "healthy", "message": "Application is running correctly"}), 200
        else:
            return jsonify({"status": "unhealthy", "message": "Cannot connect to Google Sheets"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/scrape-article', methods=['POST'])
def scrape_article():
    try:
        data = request.json
        url = data.get('url')
        category = data.get('category', None)  # Optional category
        publisher = data.get('publisher', None)  # Optional publisher
        force_add = data.get('force_add', False)  # Flag to override duplicate check
        
        if not url:
            return jsonify({"status": "error", "error": "URL is required"}), 400
        
        # Check if URL already exists in crawled_links.json
        if not force_add:
            try:
                with file_lock:
                    if os.path.exists("crawled_links.json"):
                        try:
                            with open("crawled_links.json", "r") as f:
                                crawled_data = json.load(f)
                                for item in crawled_data:
                                    if isinstance(item, dict) and item.get("url") == url:
                                        # Return error for duplicate instead of duplicate status to maintain original UI
                                        return jsonify({
                                            "status": "error", 
                                            "error": f"This article already exists in the Google Sheet (added under {item.get('category', 'unknown')} category)"
                                        }), 400
                        except json.JSONDecodeError:
                            # If JSON is invalid, treat as empty or corrupted file
                            logger.warning("crawled_links.json is corrupted, treating as empty")
                            # Create a new file
                            with open("crawled_links.json", "w") as f:
                                json.dump([], f)
                        except Exception as e:
                            logger.error(f"Error checking crawled links: {str(e)}")
            except Exception as e:
                logger.error(f"Error acquiring file lock: {str(e)}")
        
        # Use the article processor module
        try:
            result = scrape_and_check_article(url, category, publisher)
            
            if result.get("status") == "error":
                return jsonify(result), 500
            elif result.get("status") == "irrelevant":
                return jsonify({
                    "status": "irrelevant",
                    "title": result.get("title", ""),
                    "reason": result.get("reason", "No matching tags found"),
                    "url": url,
                    "publisher": result.get("publisher"),
                    "identified_publisher": result.get("identified_publisher")
                }), 200
            else:
                # Format the summary specifically for newsletter use
                summary = result.get("summary", "")
                
                # Add prompt for editor to improve the summary if needed
                editor_note = ""
                
                # Add tags or matched terms if available
                matched_tags = result.get("matched_tags", [])
                if matched_tags and isinstance(matched_tags, list):
                    tags_info = f"Topics: {', '.join(matched_tags)}"
                    # Only append tags if summary isn't already too long
                    if len(summary) < 120:
                        summary = f"{summary}\n\n{tags_info}"
                
                # Get publication date from metadata if available
                publication_date = None
                if "metadata" in result and result["metadata"].get("publish_date"):
                    publication_date = result["metadata"].get("publish_date")
                
                # Add the URL to the crawled_links.json after successful scraping
                # This will happen when the client confirms the addition to the sheet
                return jsonify({
                    "status": "success",
                    "title": result.get("title", ""),
                    "summary": summary,
                    "editor_note": editor_note,
                    "matched_tags": matched_tags,
                    "publisher": result.get("publisher"),
                    "identified_publisher": result.get("identified_publisher"),
                    "publish_date": publication_date
                }), 200
                
        except Exception as scrape_error:
            logger.error(f"Error in article scraper: {str(scrape_error)}")
            return jsonify({"status": "error", "error": f"Failed to scrape article: {str(scrape_error)}"}), 500
                
    except Exception as e:
        logger.error(f"Error in scrape_article route: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/update-sheet-id', methods=['POST'])
def update_sheet_id():
    try:
        data = request.json
        new_sheet_id = data.get('sheet_id')
        
        if not new_sheet_id:
            return jsonify({"status": "error", "error": "Sheet ID is required"}), 400
            
        # Try to connect to the new sheet
        if not update_sheet_connection(new_sheet_id):
            return jsonify({"status": "error", "error": "Could not connect to the specified sheet"}), 400
            
        # Save to config file
        if not save_config(new_sheet_id):
            return jsonify({"status": "error", "error": "Could not save configuration"}), 500
            
        return jsonify({"status": "success", "message": "Sheet ID updated successfully"}), 200
    except Exception as e:
        logger.error(f"Error updating sheet ID: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

# Crawler settings functions
def load_crawler_settings():
    """Load crawler settings from crawler_settings.json"""
    if not os.path.exists('crawler_settings.json'):
        # Create default settings file
        default_settings = {
            "categories": {
            }
        }
        with open('crawler_settings.json', 'w') as f:
            json.dump(default_settings, f, indent=4)
        return default_settings
    
    with open('crawler_settings.json', 'r') as f:
        settings = json.load(f)
        
        # Check if settings needs to be migrated to new format
        if "categories" not in settings:
            # Old format, convert to new format
            new_settings = {"categories": {}}
            for category, publishers in settings.items():
                new_settings["categories"][category] = {
                    "tags": ["ai governance", "ai policy"],  # Default tags
                    "publishers": publishers
                }
            settings = new_settings
            # Save the migrated settings
            save_crawler_settings(settings)
            
        return settings

def save_crawler_settings(settings):
    """Save crawler settings to crawler_settings.json"""
    with open('crawler_settings.json', 'w') as f:
        json.dump(settings, f, indent=4)
    return True

def add_publisher(category, publisher_name, url):
    """Add a new publisher to the crawler settings"""
    settings = load_crawler_settings()
    
    # Convert article URL to base URL if needed
    base_url = get_base_url(url)
    
    # Add the publisher to the specified category
    if "categories" not in settings:
        settings["categories"] = {}
        
    if category not in settings["categories"]:
        settings["categories"][category] = {
            "tags": ["ai governance", "ai policy"],  # Default tags
            "publishers": {}
        }
    
    settings["categories"][category]["publishers"][publisher_name] = base_url
    
    # Save the updated settings
    save_crawler_settings(settings)
    return True

def remove_publisher(category, publisher_name):
    """Remove a publisher from the crawler settings"""
    settings = load_crawler_settings()
    
    if "categories" in settings and category in settings["categories"] and "publishers" in settings["categories"][category]:
        if publisher_name in settings["categories"][category]["publishers"]:
            del settings["categories"][category]["publishers"][publisher_name]
            
            # Remove empty categories
            if not settings["categories"][category]["publishers"]:
                del settings["categories"][category]
            
            # Save the updated settings
            save_crawler_settings(settings)
            return True
    
    return False

def update_category_tags(category, tags):
    """Update the tags for a category"""
    settings = load_crawler_settings()
    
    if "categories" not in settings:
        settings["categories"] = {}
        
    if category not in settings["categories"]:
        settings["categories"][category] = {
            "tags": [],
            "publishers": {}
        }
    
    settings["categories"][category]["tags"] = tags
    
    # Save the updated settings
    save_crawler_settings(settings)
    return True

def append_link(link, publisher=None, category=None, file_path="crawled_links.json"):
    """Append a link to the crawled_links.json file with additional metadata"""
    # Use lock to prevent concurrent writes
    with file_lock:
        # If file doesn't exist, create an empty list and file
        if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                json.dump([], f)

        # Read existing links
        try:
            with open(file_path, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    # If JSON is invalid, create a new file with empty list
                    logger.warning(f"{file_path} is corrupted, treating as empty")
                    data = []
        except Exception as e:
            logger.error(f"Error reading {file_path}: {str(e)}")
            data = []

        # Check if link is already in the file
        link_exists = False
        for item in data:
            if isinstance(item, dict) and item.get("url") == link:
                link_exists = True
                break
            elif isinstance(item, str) and item == link:
                # If the item is in the old format (just a string), remove it
                data.remove(item)
                link_exists = False
                break

        # Append if link is not already in the file
        if not link_exists:
            # Create a new entry with metadata
            entry = {
                "url": link,
                "timestamp": datetime.now().isoformat(),
                "publisher": publisher,
                "category": category
            }
            data.append(entry)
            try:
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=4)
                return True
            except Exception as write_error:
                logger.error(f"Error writing to {file_path}: {str(write_error)}")
                return False
        
        return False

def append_links_batch(links, publisher=None, category=None, file_path="crawled_links.json"):
    """Append multiple links at once for better performance"""
    if not links:
        return 0
        
    # Use lock to prevent concurrent writes
    with file_lock:
        # If file doesn't exist, create an empty list and file
        if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                json.dump([], f)
                
        # Read existing links
        try:
            with open(file_path, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    # If JSON is invalid, create a new file with empty list
                    logger.warning(f"{file_path} is corrupted, treating as empty")
                    data = []
        except Exception as e:
            logger.error(f"Error reading {file_path}: {str(e)}")
            data = []
                
        # Track existing URLs to avoid duplicates
        existing_urls = {item.get("url") if isinstance(item, dict) else item for item in data}
                
        # Process old format items (strings)
        data = [item for item in data if isinstance(item, dict)]
                
        # Add new entries
        count_added = 0
        for link in links:
            if link not in existing_urls:
                entry = {
                    "url": link,
                    "timestamp": datetime.now().isoformat(),
                    "publisher": publisher,
                    "category": category
                }
                data.append(entry)
                count_added += 1
                
        # Save if any links were added
        if count_added > 0:
            try:
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=4)
            except Exception as write_error:
                logger.error(f"Error writing to {file_path}: {str(write_error)}")
                return 0
                
        return count_added

def run_crawler(categories=None, publishers=None, max_pages=5):
    """Run the crawler with the specified filters"""
    global crawler_status
    start_time = time.time()
    # Reset crawler status
    crawler_status = {
        "running": True,
        "progress": 0,
        "total": 0,
        "current": "",
        "results": [],
        "stop_flag": False,
        "start_time": start_time,
        "elapsed_time": 0,
        "estimated_time_remaining": None
    }
    
    # Load crawler settings
    settings = load_crawler_settings()
    
    # Filter categories if specified
    if categories:
        filtered_categories = {}
        for category in categories:
            if "categories" in settings and category in settings["categories"]:
                filtered_categories[category] = settings["categories"][category]
    else:
        filtered_categories = settings.get("categories", {})
    
    # Calculate total number of publishers to crawl
    total_publishers = 0
    
    # Create a map of publishers to crawl
    publishers_to_crawl = {}
    
    # If publishers are specified, create a map of category -> publisher_name -> True
    if publishers:
        for publisher in publishers:
            category = publisher.get('category')
            name = publisher.get('name')
            if category and name:
                if category not in publishers_to_crawl:
                    publishers_to_crawl[category] = {}
                publishers_to_crawl[category][name] = True
                total_publishers += 1
    else:
        # If no publishers specified, crawl all publishers in filtered categories
        for category, category_data in filtered_categories.items():
            publishers_dict = category_data.get("publishers", {})
            publishers_to_crawl[category] = {name: True for name in publishers_dict.keys()}
            total_publishers += len(publishers_dict)
    
    crawler_status["total"] = total_publishers
    
    # Initialize the driver
    driver = setup_driver(headless=True)
    
    try:
        # Iterate through categories and publishers
        for category, category_data in filtered_categories.items():
            # Update elapsed time and estimated time remaining
            current_time = time.time()
            crawler_status["elapsed_time"] = int(current_time - start_time)
            
            # Calculate estimated time remaining if we have progress
            if crawler_status["progress"] > 0:
                time_per_publisher = crawler_status["elapsed_time"] / crawler_status["progress"]
                remaining_publishers = crawler_status["total"] - crawler_status["progress"]
                estimated_time = int(time_per_publisher * remaining_publishers)
                crawler_status["estimated_time_remaining"] = estimated_time
            
            # Check stop flag before processing category
            if crawler_status["stop_flag"]:
                logger.info("Stopping crawler due to stop request")
                break
                
            # Skip if no publishers in this category
            if not category_data.get("publishers"):
                continue
                
            # Get the tags for this category
            category_tags = category_data.get("tags", ["ai governance", "ai policy"])
            
            # Iterate through publishers in this category
            for publisher_name, base_url in category_data.get("publishers", {}).items():
                # Update elapsed time again
                current_time = time.time()
                crawler_status["elapsed_time"] = int(current_time - start_time)
                
                # Recalculate estimated time remaining
                if crawler_status["progress"] > 0:
                    time_per_publisher = crawler_status["elapsed_time"] / crawler_status["progress"]
                    remaining_publishers = crawler_status["total"] - crawler_status["progress"]
                    estimated_time = int(time_per_publisher * remaining_publishers)
                    crawler_status["estimated_time_remaining"] = estimated_time
                
                # Check stop flag before processing publisher
                if crawler_status["stop_flag"]:
                    logger.info("Stopping crawler due to stop request")
                    break
                    
                # Skip if specific publishers are requested and this one isn't included
                if publishers and (category not in publishers_to_crawl or publisher_name not in publishers_to_crawl[category]):
                    continue
                
                # Update status
                crawler_status["current"] = f"Crawling {publisher_name} ({category})"
                
                try:
                    # Create search query using category tags
                    search_parts = [f'"{tag}" site:{base_url.replace("https://", "").replace("http://", "")}' for tag in category_tags]
                    search_query = " OR ".join(search_parts)
                    print(search_query)
                    logger.info(f"Searching with query: {search_query}")
                    
                    # Run the search but don't auto-process (we'll do it after filtering)
                    result_links, _ = search(
                        driver, 
                        search_query, 
                        max_pages=max_pages,
                        category=category,
                        publisher=publisher_name,
                        auto_process=False,  # Don't process automatically during search
                        stop_flag=lambda: crawler_status["stop_flag"]  # Pass the stop flag as a lambda function
                    )
                    
                    # Update elapsed time again
                    current_time = time.time()
                    crawler_status["elapsed_time"] = int(current_time - start_time)
                    
                    # Check stop flag after search
                    if crawler_status["stop_flag"]:
                        logger.info("Stopping crawler after search due to stop request")
                        break
                    
                    # Get the publisher's domain for validation
                    publisher_domain = base_url.replace("https://", "").replace("http://", "").strip("/")
                    if publisher_domain.startswith("www."):
                        publisher_domain = publisher_domain[4:]  # Remove www. prefix if present
                    
                    # Filter links to ensure they're from the correct domain
                    valid_links = []
                    for link in result_links:
                        # Check stop flag periodically during processing
                        if crawler_status["stop_flag"]:
                            logger.info("Stopping crawler during link filtering due to stop request")
                            break
                            
                        try:
                            result_domain = link.replace("https://", "").replace("http://", "").split("/")[0]
                            if result_domain.startswith("www."):
                                result_domain = result_domain[4:]  # Remove www. prefix if present
                            
                            # Only add the result if it's from the publisher's domain
                            if publisher_domain in result_domain:
                                valid_links.append(link)
                            else:
                                logger.info(f"Skipping {link} - not from {publisher_domain}")
                        except Exception as e:
                            logger.error(f"Error validating URL {link}: {str(e)}")
                    
                    # Update elapsed time again
                    current_time = time.time()
                    crawler_status["elapsed_time"] = int(current_time - start_time)
                    
                    # Check stop flag after filtering
                    if crawler_status["stop_flag"]:
                        logger.info("Stopping crawler after link filtering due to stop request")
                        break
                    
                    # Check which links have already been processed previously
                    new_links = []
                    
                    # Load existing crawled links
                    crawled_links = []
                    if os.path.exists("crawled_links.json"):
                        try:
                            with open("crawled_links.json", "r") as f:
                                crawled_data = json.load(f)
                                crawled_links = [item.get("url") if isinstance(item, dict) else item for item in crawled_data]
                        except Exception as e:
                            logger.error(f"Error loading crawled links: {str(e)}")
                    
                    # Load unused links
                    unused_links = []
                    if os.path.exists("unused_links.json"):
                        try:
                            with open("unused_links.json", "r") as f:
                                unused_data = json.load(f)
                                unused_links = [item.get("url") if isinstance(item, dict) else item for item in unused_data]
                        except Exception as e:
                            logger.error(f"Error loading unused links: {str(e)}")
                    
                    # All previously processed links
                    all_processed_links = set(crawled_links + unused_links)
                    
                    # Filter out already processed links
                    for link in valid_links:
                        # Check stop flag during processing
                        if crawler_status["stop_flag"]:
                            logger.info("Stopping crawler during link deduplication due to stop request")
                            break
                            
                        if link not in all_processed_links:
                            new_links.append(link)
                        else:
                            logger.info(f"Skipping already processed link: {link}")
                    
                    # Update elapsed time again
                    current_time = time.time()
                    crawler_status["elapsed_time"] = int(current_time - start_time)
                    
                    # Check stop flag after filtering
                    if crawler_status["stop_flag"]:
                        logger.info("Stopping crawler after link deduplication due to stop request")
                        break
                    
                    logger.info(f"Found {len(valid_links)} valid links, {len(new_links)} are new")
                    
                    # Process the new links through article processor
                    processed_results = []
                    if new_links:
                        # Import process_links function from crawler
                        from crawler import process_links
                        
                        # Process the links
                        process_links(new_links, category, publisher_name, processed_results, 
                                     stop_flag=lambda: crawler_status["stop_flag"])  # Pass the stop flag
                        
                        # Log the results from processing
                        relevant_count = sum(1 for r in processed_results if r.get('status') == 'success')
                        irrelevant_count = sum(1 for r in processed_results if r.get('status') == 'irrelevant')
                        logger.info(f"Processed {len(processed_results)} links for {publisher_name} ({category})")
                        logger.info(f"Found {relevant_count} relevant articles, {irrelevant_count} irrelevant articles")
                        
                        # Add to crawler status results (only the relevant ones)
                        for result in processed_results:
                            if result.get('status') == 'success':
                                crawler_status["results"].append({
                                    "url": result.get('url'),
                                    "title": result.get('title', ''),
                                    "publisher": publisher_name,
                                    "category": category
                                })
                    
                    # Update elapsed time again
                    current_time = time.time()
                    crawler_status["elapsed_time"] = int(current_time - start_time)
                    
                    # Log completion of this publisher
                    logger.info(f"Completed search for {publisher_name} ({category})")
                    
                except Exception as publisher_error:
                    # Log error but continue with next publisher
                    logger.error(f"Error processing publisher {publisher_name}: {str(publisher_error)}")
                finally:
                    # Update progress regardless of success or failure
                    crawler_status["progress"] += 1
                    
                    # Update elapsed time and estimated time remaining
                    current_time = time.time()
                    crawler_status["elapsed_time"] = int(current_time - start_time)
                    
                    # Recalculate estimated time remaining
                    if crawler_status["progress"] > 0:
                        time_per_publisher = crawler_status["elapsed_time"] / crawler_status["progress"]
                        remaining_publishers = crawler_status["total"] - crawler_status["progress"]
                        estimated_time = int(time_per_publisher * remaining_publishers)
                        crawler_status["estimated_time_remaining"] = estimated_time
                    
                    # Check stop flag before moving to next publisher
                    if crawler_status["stop_flag"]:
                        logger.info("Stopping crawler between publishers due to stop request")
                        break

        # Final time update
        current_time = time.time()
        crawler_status["elapsed_time"] = int(current_time - start_time)
        crawler_status["estimated_time_remaining"] = 0
        
        # Crawler completed successfully or was stopped
        if crawler_status["stop_flag"]:
            crawler_status["running"] = False
            crawler_status["current"] = "Crawler stopped by user"
        else:
            crawler_status["running"] = False
            crawler_status["current"] = "Crawling completed"
            
        total_time = time.time() - start_time
        logger.info(f"Total processing time: {total_time:.2f} seconds")
        
    except Exception as e:
        logger.error(f"Error running crawler: {str(e)}")
        crawler_status["running"] = False
        crawler_status["current"] = f"Error: {str(e)}"
    
    finally:
        # Final time update
        current_time = time.time()
        crawler_status["elapsed_time"] = int(current_time - start_time)
        crawler_status["estimated_time_remaining"] = 0
        
        # Reset stop flag
        crawler_status["stop_flag"] = False
        # Close the driver
        driver.quit()
    
    return crawler_status

# New routes for crawler functionality
@app.route('/crawler-settings', methods=['GET'])
def get_crawler_settings():
    """Get the current crawler settings"""
    try:
        settings = load_crawler_settings()
        return jsonify({"status": "success", "settings": settings}), 200
    except Exception as e:
        logger.error(f"Error getting crawler settings: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler-settings', methods=['POST'])
def update_crawler_settings():
    """Add or update a publisher in the crawler settings"""
    try:
        data = request.json
        category = data.get('category')
        publisher_name = data.get('publisher_name')
        url = data.get('url')
        
        if not category or not publisher_name or not url:
            return jsonify({"status": "error", "error": "Category, publisher name, and URL are required"}), 400
        
        # Add the publisher
        add_publisher(category, publisher_name, url)
        
        return jsonify({"status": "success", "message": "Publisher added successfully"}), 200
    except Exception as e:
        logger.error(f"Error updating crawler settings: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler-settings/<category>/<publisher>', methods=['DELETE'])
def delete_publisher(category, publisher):
    """Remove a publisher from the crawler settings"""
    try:
        if remove_publisher(category, publisher):
            return jsonify({"status": "success", "message": "Publisher removed successfully"}), 200
        else:
            return jsonify({"status": "error", "error": "Publisher not found"}), 404
    except Exception as e:
        logger.error(f"Error removing publisher: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler/start', methods=['POST'])
def start_crawler():
    """Start the crawler with specified filters"""
    global crawler_status
    
    # Check if crawler is already running to prevent multiple instances
    if crawler_status["running"]:
        return jsonify({"status": "error", "error": "Crawler is already running"}), 400
    
    data = request.get_json()
    categories = data.get('categories', [])
    publishers = data.get('publishers', [])
    max_pages = data.get('max_pages', 5)
    
    # Start crawler in a separate thread
    thread = threading.Thread(target=run_crawler, args=(categories, publishers, max_pages))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started"})

@app.route('/crawler/status', methods=['GET'])
def get_crawler_status():
    """Get the current status of the crawler"""
    return jsonify({"status": "success", "crawler": crawler_status}), 200

@app.route('/crawler/results', methods=['GET'])
def get_crawler_results():
    """Get the results of the crawler"""
    return jsonify({"status": "success", "results": crawler_status["results"]}), 200

@app.route('/crawler/links', methods=['GET'])
def get_crawled_links():
    """Get all crawled links with their metadata"""
    try:
        file_path = "crawled_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "success", "links": []}), 200
            
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        
        # Convert old format (list of strings) to new format (list of objects)
        formatted_data = []
        for item in data:
            if isinstance(item, str):
                formatted_data.append({
                    "url": item,
                    "timestamp": None,
                    "publisher": None,
                    "category": None
                })
            else:
                formatted_data.append(item)
                
        return jsonify({"status": "success", "links": formatted_data}), 200
    except Exception as e:
        logger.error(f"Error getting crawled links: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler-settings/tags/<category>', methods=['PUT'])
def update_tags(category):
    """Update the tags for a category"""
    try:
        data = request.json
        tags = data.get('tags', [])
        
        if not category:
            return jsonify({"status": "error", "error": "Category is required"}), 400
        
        if not isinstance(tags, list):
            return jsonify({"status": "error", "error": "Tags must be a list of strings"}), 400
        
        # Update the tags
        update_category_tags(category, tags)
        
        return jsonify({"status": "success", "message": f"Tags for category '{category}' updated successfully"}), 200
    except Exception as e:
        logger.error(f"Error updating tags: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler-settings/tags/<category>', methods=['GET'])
def get_category_tags(category):
    """Get the tags for a category"""
    try:
        settings = load_crawler_settings()
        
        if "categories" not in settings or category not in settings["categories"]:
            return jsonify({"status": "error", "error": f"Category '{category}' not found"}), 404
        
        tags = settings["categories"][category].get("tags", [])
        
        return jsonify({"status": "success", "tags": tags}), 200
    except Exception as e:
        logger.error(f"Error getting tags: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler/links/publisher/<publisher>', methods=['GET'])
def get_links_by_publisher(publisher):
    """Get crawled links for a specific publisher"""
    try:
        file_path = "crawled_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "success", "links": []}), 200
            
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        
        # Filter links by publisher
        publisher_links = []
        for item in data:
            if isinstance(item, dict) and item.get("publisher") == publisher:
                publisher_links.append(item)
                
        return jsonify({"status": "success", "publisher": publisher, "links": publisher_links}), 200
    except Exception as e:
        logger.error(f"Error getting links for publisher {publisher}: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler/links/category/<category>', methods=['GET'])
def get_links_by_category(category):
    """Get crawled links for a specific category"""
    try:
        file_path = "crawled_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "success", "links": []}), 200
            
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        
        # Filter links by category
        category_links = []
        for item in data:
            if isinstance(item, dict) and item.get("category") == category:
                category_links.append(item)
                
        return jsonify({"status": "success", "category": category, "links": category_links}), 200
    except Exception as e:
        logger.error(f"Error getting links for category {category}: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler/links/stats', methods=['GET'])
def get_link_stats():
    """Get statistics about crawled links"""
    try:
        file_path = "crawled_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "success", "stats": {"total": 0}}), 200
            
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        
        # Calculate statistics
        total_links = len(data)
        publishers = {}
        categories = {}
        
        for item in data:
            if isinstance(item, dict):
                publisher = item.get("publisher")
                category = item.get("category")
                
                if publisher:
                    publishers[publisher] = publishers.get(publisher, 0) + 1
                if category:
                    categories[category] = categories.get(category, 0) + 1
        
        # Sort by count
        publishers = dict(sorted(publishers.items(), key=lambda x: x[1], reverse=True))
        categories = dict(sorted(categories.items(), key=lambda x: x[1], reverse=True))
        
        stats = {
            "total": total_links,
            "by_publisher": publishers,
            "by_category": categories
        }
                
        return jsonify({"status": "success", "stats": stats}), 200
    except Exception as e:
        logger.error(f"Error getting link statistics: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/scrape-articles-batch', methods=['POST'])
def scrape_articles_batch():
    """Process multiple articles at once"""
    try:
        data = request.json
        articles = data.get('articles', [])
        force_add = data.get('force_add', False)  # Option to force add even if duplicate
        
        if not articles or not isinstance(articles, list):
            return jsonify({"error": "A list of articles is required"}), 400
        
        results = {
            "processed": 0,
            "relevant": 0,
            "irrelevant": 0,
            "duplicates": 0,
            "errors": 0,
            "relevant_articles": [],
            "irrelevant_articles": [],
            "duplicate_articles": [],
            "error_articles": []
        }
        
        # Load existing crawled links for duplicate checking if not forcing add
        crawled_urls = set()
        if not force_add and os.path.exists("crawled_links.json"):
            try:
                with open("crawled_links.json", "r") as f:
                    try:
                        crawled_data = json.load(f)
                        crawled_urls = {item.get("url") for item in crawled_data if isinstance(item, dict)}
                    except json.JSONDecodeError:
                        # If JSON is invalid, treat as empty or corrupted file
                        logger.warning("crawled_links.json is corrupted, treating as empty")
                        # Create a new file
                        with open("crawled_links.json", "w") as f:
                            json.dump([], f)
            except Exception as e:
                logger.error(f"Error loading crawled links: {str(e)}")
        
        for article in articles:
            url = article.get('url')
            category = article.get('category')
            publisher = article.get('publisher')
            
            if not url or not category:
                results["errors"] += 1
                results["error_articles"].append({
                    "url": url,
                    "error": "URL and category are required for each article"
                })
                continue
            
            # Check for duplicates
            if not force_add and url in crawled_urls:
                results["duplicates"] += 1
                results["duplicate_articles"].append({
                    "url": url,
                    "category": category,
                    "error": "This article already exists in the Google Sheet"
                })
                continue
            
            # Process the article
            try:
                result = scrape_and_check_article(url, category, publisher)
                results["processed"] += 1
                
                if result.get("status") == "success":
                    # Try to add to Google Sheets through a separate API call
                    try:
                        # Format the data for adding to Google Sheets
                        sheet_data = {
                            "category": category,
                            "link": url,
                            "title": result.get("title", ""),
                            "summary": result.get("summary", ""),
                            "publisher": publisher,
                            "date": datetime.today().strftime("%m/%d/%Y"),
                            "force_add": force_add  # Pass along the force_add flag
                        }
                        
                        # Call the add-link endpoint
                        add_response = requests.post(
                            "http://localhost:5000/add-link",
                            json=sheet_data,
                            headers={"Content-Type": "application/json"}
                        )
                        
                        if add_response.status_code == 200:
                            # Success - article was added to the sheet
                            # Add to crawled_links.json only after successful addition to sheet
                            append_link(url, publisher, category)
                            logger.info(f"Added article to sheet and crawled_links.json: {url}")
                            
                            results["relevant"] += 1
                            results["relevant_articles"].append({
                                "url": url,
                                "title": result.get("title", ""),
                                "summary": result.get("summary", ""),
                                "matched_tags": result.get("matched_tags", []),
                                "category": category
                            })
                        else:
                            # Failed to add to sheet - might be a duplicate
                            response_data = add_response.json()
                            error_msg = response_data.get("error", "Unknown error adding to sheet")
                            
                            # Check if it's a duplicate
                            if "already exists" in error_msg:
                                results["duplicates"] += 1
                                results["duplicate_articles"].append({
                                    "url": url,
                                    "category": category,
                                    "error": error_msg
                                })
                            else:
                                # Some other error
                                results["errors"] += 1
                                results["error_articles"].append({
                                    "url": url,
                                    "error": error_msg,
                                    "category": category
                                })
                            
                    except Exception as sheet_error:
                        logger.error(f"Error adding article to sheet: {str(sheet_error)}")
                        results["errors"] += 1
                        results["error_articles"].append({
                            "url": url,
                            "error": f"Error adding to sheet: {str(sheet_error)}",
                            "category": category
                        })
                        
                elif result.get("status") == "irrelevant":
                    results["irrelevant"] += 1
                    results["irrelevant_articles"].append({
                        "url": url,
                        "title": result.get("title", ""),
                        "reason": result.get("reason", ""),
                        "category": category
                    })
                else:
                    results["errors"] += 1
                    results["error_articles"].append({
                        "url": url,
                        "error": result.get("error", "Unknown error"),
                        "category": category
                    })
            except Exception as article_error:
                results["errors"] += 1
                results["error_articles"].append({
                    "url": url,
                    "error": str(article_error),
                    "category": category
                })
        
        return jsonify({"status": "success", "results": results}), 200
    except Exception as e:
        logger.error(f"Error processing batch of articles: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/unused-links', methods=['GET'])
def get_unused_links():
    """Get all unused links (links that didn't match category tags)"""
    try:
        file_path = "unused_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "success", "links": []}), 200
            
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        
        # Calculate some statistics
        total_links = len(data)
        by_category = {}
        by_reason = {}
        
        for item in data:
            if isinstance(item, dict):
                category = item.get("category")
                reason = item.get("reason")
                
                if category:
                    by_category[category] = by_category.get(category, 0) + 1
                    
                if reason:
                    # Simplify reason for stats (take first 50 chars)
                    short_reason = reason[:50] + ("..." if len(reason) > 50 else "")
                    by_reason[short_reason] = by_reason.get(short_reason, 0) + 1
        
        stats = {
            "total": total_links,
            "by_category": by_category,
            "by_reason": by_reason
        }
        
        return jsonify({
            "status": "success", 
            "links": data,
            "stats": stats
        }), 200
    except Exception as e:
        logger.error(f"Error getting unused links: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/unused-links', methods=['DELETE'])
def delete_unused_links():
    """Delete unused links based on various filters"""
    try:
        data = request.json
        category = data.get('category')
        publisher = data.get('publisher')
        before_date = data.get('before_date')
        all_links = data.get('all', False)
        
        file_path = "unused_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "success", "deleted": 0}), 200
            
        with open(file_path, "r") as f:
            try:
                links = json.load(f)
            except json.JSONDecodeError:
                links = []
        
        # If no links or no filters specified and not deleting all, return
        if not links or (not category and not publisher and not before_date and not all_links):
            return jsonify({"status": "error", "error": "No filter specified"}), 400
        
        # Convert before_date to datetime if provided
        before_datetime = None
        if before_date:
            try:
                before_datetime = datetime.fromisoformat(before_date)
            except ValueError:
                return jsonify({"status": "error", "error": "Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
        
        # Filter links to keep
        original_count = len(links)
        links_to_keep = []
        
        for link in links:
            # Skip if not a dict (shouldn't happen but just in case)
            if not isinstance(link, dict):
                continue
                
            # If deleting all links, don't keep any
            if all_links:
                continue
                
            # Check if link matches any filter
            matches_filter = False
            
            # Check category filter
            if category and link.get("category") == category:
                matches_filter = True
                
            # Check publisher filter
            if publisher and link.get("publisher") == publisher:
                matches_filter = True
                
            # Check date filter
            if before_datetime and link.get("timestamp"):
                try:
                    link_datetime = datetime.fromisoformat(link.get("timestamp"))
                    if link_datetime < before_datetime:
                        matches_filter = True
                except ValueError:
                    # If timestamp is invalid, ignore this filter
                    pass
            
            # Keep link if it doesn't match any filter
            if not matches_filter:
                links_to_keep.append(link)
        
        # Calculate how many were deleted
        deleted_count = original_count - len(links_to_keep)
        
        # Save the filtered links
        with open(file_path, "w") as f:
            json.dump(links_to_keep, f, indent=4)
            
        return jsonify({
            "status": "success", 
            "deleted": deleted_count,
            "remaining": len(links_to_keep)
        }), 200
    except Exception as e:
        logger.error(f"Error deleting unused links: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/unused-links/recover', methods=['POST'])
def recover_unused_link():
    """Recover an unused link and add it to Google Sheets"""
    try:
        data = request.json
        url = data.get('url')
        category = data.get('category')
        summary = data.get('summary')
        title = data.get('title')
        force_add = data.get('force_add', False)  # Option to force add even if duplicate
        
        if not url or not category:
            return jsonify({"status": "error", "error": "URL and category are required"}), 400
        
        # Check if URL already exists in crawled_links.json unless force_add is True
        if not force_add:
            try:
                with file_lock:
                    if os.path.exists("crawled_links.json"):
                        try:
                            with open("crawled_links.json", "r") as f:
                                crawled_data = json.load(f)
                                for item in crawled_data:
                                    if isinstance(item, dict) and item.get("url") == url:
                                        # Return as error for original UI compatibility
                                        return jsonify({
                                            "status": "error",
                                            "error": f"This article already exists in the Google Sheet (added under {item.get('category', 'unknown')} category)"
                                        }), 400
                        except json.JSONDecodeError:
                            # If JSON is invalid, treat as empty or corrupted file
                            logger.warning("crawled_links.json is corrupted, treating as empty")
                            # Create a new file
                            with open("crawled_links.json", "w") as f:
                                json.dump([], f)
                        except Exception as e:
                            logger.error(f"Error checking crawled links: {str(e)}")
            except Exception as e:
                logger.error(f"Error checking crawled links: {str(e)}")
        
        # Find the link in the unused_links.json file
        file_path = "unused_links.json"
        if not os.path.exists(file_path):
            return jsonify({"status": "error", "error": "Unused links file not found"}), 404
            
        with open(file_path, "r") as f:
            try:
                links = json.load(f)
            except json.JSONDecodeError:
                links = []
        
        # Find the link
        link_index = None
        link_data = None
        
        for i, link in enumerate(links):
            if isinstance(link, dict) and link.get("url") == url:
                link_index = i
                link_data = link
                break
        
        if link_index is None:
            return jsonify({"status": "error", "error": "Link not found in unused links"}), 404
        
        # If no title or summary provided, use the ones from the link data
        if not title and link_data.get("title"):
            title = link_data.get("title")
        
        if not summary:
            # If no summary provided, try to scrape the article again
            try:
                result = scrape_and_check_article(url, category)
                if result.get("status") in ["success", "irrelevant"]:
                    summary = result.get("summary", "")
                    if not title:
                        title = result.get("title", "")
            except Exception as e:
                logger.warning(f"Error re-scraping article for recovery: {str(e)}")
                # Continue with the process even if scraping fails
        
        # Remove the link from unused_links.json
        links.pop(link_index)
        with open(file_path, "w") as f:
            json.dump(links, f, indent=4)
        
        # Add the link to Google Sheets
        try:
            if not reconnect_if_needed():
                return jsonify({"error": "Could not connect to Google Sheets"}), 500
                
            worksheet = sheet.worksheet(category)
            
            # Current date in mm/dd/yyyy format
            date = datetime.today().strftime("%m/%d/%Y")
            
            # Create HYPERLINK formula
            hyperlink_formula = f'=HYPERLINK("{url}", "{title}")'
            
            # Add the data row with HYPERLINK formula using USER_ENTERED
            worksheet.append_row([hyperlink_formula, summary, date], value_input_option="USER_ENTERED")
            logger.info(f"Recovered link to worksheet '{category}': {url[:50]}...")
            
            # Add to crawled_links.json since we've successfully added it to the sheet
            publisher = link_data.get("publisher") if link_data else None
            append_link(url, publisher, category)
            
            return jsonify({
                "status": "success",
                "message": f"Link recovered and added to {category} worksheet"
            }), 200
            
        except Exception as sheet_error:
            logger.error(f"Error adding recovered link to sheet: {str(sheet_error)}")
            # Re-add the link to unused_links.json since we couldn't add it to the sheet
            links.append(link_data)
            with open(file_path, "w") as f:
                json.dump(links, f, indent=4)
            
            return jsonify({
                "status": "error",
                "error": f"Error adding to sheet: {str(sheet_error)}"
            }), 500
            
    except Exception as e:
        logger.error(f"Error recovering unused link: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/crawler/stop', methods=['POST'])
def stop_crawler():
    """Stop the running crawler"""
    global crawler_status
    
    if crawler_status["running"]:
        # Set the stop flag to true
        crawler_status["stop_flag"] = True
        return jsonify({"status": "stopping", "message": "Stop signal sent to crawler"}), 200
    else:
        return jsonify({"status": "not_running", "message": "Crawler is not running"}), 400

if __name__ == "__main__":
    app.run(debug=True)