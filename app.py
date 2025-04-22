from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import logging
from newspaper import Article
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import time
import random
import json
import threading
from urllib.parse import urlparse
from crawler import setup_driver, search, get_base_url

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    "results": []
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
        
        if not tab_name or not link:
            return jsonify({"error": "Worksheet name and link are required"}), 400
            
        # Validate URL (basic validation)
        if not link.startswith(('http://', 'https://')):
            return jsonify({"error": "URL must start with http:// or https://"}), 400
        
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet(tab_name)
        
        # Create HYPERLINK formula
        hyperlink_formula = f'=HYPERLINK("{link}", "{title}")'
        
        # Add the data row with HYPERLINK formula using USER_ENTERED
        worksheet.append_row([hyperlink_formula, summary, date], value_input_option="USER_ENTERED")
        logger.info(f"Added link to worksheet '{tab_name}': {link[:50]}...")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error adding link: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/reset-sheet')
def reset_sheet():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet("Sheet1")
        # Clear the sheet
        worksheet.clear()
        # Add headers
        worksheet.append_row(["Link", "Summary", "Date"])
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
        
        # Add headers to new worksheet
        new_worksheet.append_row(["Link", "Summary", "Date"])
        
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
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
            
        # First try with simple newspaper approach
        try:
            article = Article(url)
            article.download()
            article.parse()
            
            if article.text:
                return jsonify({
                    "status": "success",
                    "title": article.title,
                    "summary": article.text[:500] + "..."
                }), 200
        except Exception as e:
            logger.warning(f"Initial scraping attempt failed: {str(e)}")
            # Continue to fallback method if first attempt fails
        
        # If first attempt fails, try with user agent and fallback methods
        try:
            ua = UserAgent()
            headers = {
                'User-Agent': ua.random,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            # Try direct requests with BeautifulSoup
            response = requests.get(url, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to get title
            title = soup.title.string if soup.title else "No title found"
            
            # Try to get main content
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
            if main_content:
                text = main_content.get_text(strip=True)
            else:
                # Fallback to body text
                text = soup.body.get_text(strip=True) if soup.body else "No content found"
            
            return jsonify({
                "status": "success",
                "title": title,
                "summary": text[:500] + "..."
            }), 200
            
        except Exception as fallback_error:
            logger.error(f"Fallback scraping failed: {str(fallback_error)}")
            return jsonify({"error": "Could not scrape the article. The website might be blocking automated access."}), 500
                
    except Exception as e:
        logger.error(f"Error scraping article: {str(e)}")
        return jsonify({"error": str(e)}), 500

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
                "NEWS": {
                    "tags": ["ai governance", "ai policy", "artificial intelligence regulation"],
                    "publishers": {}
                },
                "Research": {
                    "tags": ["ai ethics", "ai governance", "ai policy framework"],
                    "publishers": {}
                }
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
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
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
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
            
            return True
        
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
        with open(file_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
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
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
                
        return count_added

def run_crawler(categories=None, publishers=None, max_pages=5):
    """Run the crawler with the specified filters"""
    global crawler_status
    
    # Reset crawler status
    crawler_status = {
        "running": True,
        "progress": 0,
        "total": 0,
        "current": "",
        "results": []
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
            # Skip if no publishers in this category
            if not category_data.get("publishers"):
                continue
                
            # Get the tags for this category
            category_tags = category_data.get("tags", ["ai governance", "ai policy"])
            
            # Iterate through publishers in this category
            for publisher_name, base_url in category_data.get("publishers", {}).items():
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
                    
                    # Run the search
                    result_links = search(driver, search_query, max_pages=max_pages)
                    
                    # Get the publisher's domain for validation
                    publisher_domain = base_url.replace("https://", "").replace("http://", "").strip("/")
                    if publisher_domain.startswith("www."):
                        publisher_domain = publisher_domain[4:]  # Remove www. prefix if present
                    
                    # Process results and append to crawler_status and JSON file immediately
                    valid_links = []
                    for link in result_links:
                        # Check if the result URL contains the publisher's domain
                        try:
                            result_domain = link.replace("https://", "").replace("http://", "").split("/")[0]
                            if result_domain.startswith("www."):
                                result_domain = result_domain[4:]  # Remove www. prefix if present
                            
                            # Only add the result if it's from the publisher's domain
                            if publisher_domain in result_domain:
                                # Add to crawler status results
                                crawler_status["results"].append({
                                    "url": link,
                                    "publisher": publisher_name,
                                    "category": category
                                })
                                # Add to batch
                                valid_links.append(link)
                            else:
                                logger.info(f"Skipping {link} - not from {publisher_domain}")
                        except Exception as e:
                            logger.error(f"Error validating URL {link}: {str(e)}")
                    
                    # Append valid links in batch for better performance
                    if valid_links:
                        count_added = append_links_batch(valid_links, publisher_name, category)
                        logger.info(f"Added {count_added} new links for {publisher_name} ({category})")
                    
                    # Log completion of this publisher
                    logger.info(f"Completed search for {publisher_name} ({category})")
                    
                except Exception as publisher_error:
                    # Log error but continue with next publisher
                    logger.error(f"Error processing publisher {publisher_name}: {str(publisher_error)}")
                finally:
                    # Update progress regardless of success or failure
                    crawler_status["progress"] += 1

        # Crawler completed successfully
        crawler_status["running"] = False
        crawler_status["current"] = "Crawling completed"
        
    except Exception as e:
        logger.error(f"Error running crawler: {str(e)}")
        crawler_status["running"] = False
        crawler_status["current"] = f"Error: {str(e)}"
    
    finally:
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

if __name__ == "__main__":
    app.run(debug=True)