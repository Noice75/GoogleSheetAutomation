import os
import time
import random
import json
import requests
from datetime import datetime
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from article_processor import scrape_and_check_article

# This crawler works with the article_processor.py module, which uses newspaper3k
# for extracting article content, metadata, and creating summaries.
# It handles collecting links, processing articles, and uploading to Google Sheets.

# Google Sheets Integration
def load_config():
    """Load the sheet ID from config.json"""
    if not os.path.exists('config.json'):
        print("⚠️ No config.json found. Unable to upload to Google Sheets.")
        return None
    
    with open('config.json', 'r') as f:
        config = json.load(f)
        return config.get('sheet_id', None)

def upload_to_sheet(result):
    """Upload relevant article to Google Sheets"""
    try:
        # Check if we have all required data
        if not all(k in result for k in ['title', 'summary', 'url']):
            print("⚠️ Missing required data for Google Sheets upload")
            return False
            
        # Ensure we have a valid category - this is crucial for worksheet selection
        category = result.get("category")
        if not category:
            print("⚠️ No category specified for Google Sheets upload, using Sheet1")
            category = "Sheet1"
            
        publisher = result.get("publisher", "")
        
        # Extract metadata from newspaper3k if available
        metadata = result.get("metadata", {})
        authors = ", ".join(metadata.get("authors", [])) if metadata.get("authors") else ""
        publish_date = metadata.get("publish_date", "")
        keywords = ", ".join(metadata.get("keywords", [])) if metadata.get("keywords") else ""
        
        # Format the date properly to remove time portion if it exists
        if publish_date:
            try:
                # Check if publish_date is a string and contains a date
                if isinstance(publish_date, str) and publish_date.strip():
                    # Try to parse the date string to a datetime object
                    if "T" in publish_date:  # ISO format with T separator
                        date_obj = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
                    elif " " in publish_date:  # Format with space separator
                        date_parts = publish_date.split(' ')[0]  # Get just the date part
                        date_obj = datetime.strptime(date_parts, "%Y-%m-%d")
                    else:
                        date_obj = datetime.strptime(publish_date.split('T')[0], "%Y-%m-%d")
                    
                    # Format to just the date portion as MM/DD/YYYY
                    publish_date = date_obj.strftime("%m/%d/%Y")
            except Exception as e:
                print(f"⚠️ Error formatting date {publish_date}: {str(e)}")
                publish_date = ""  # Reset if parsing fails
        
        # Use published date from metadata if available, otherwise use current date
        date_to_use = publish_date if publish_date else datetime.today().strftime("%m/%d/%Y")
            
        data = {
            "category": category,  # Category name is used as worksheet name
            "link": result["url"],
            "title": result["title"],
            "summary": result["summary"],
            "publisher": publisher,
            "date": date_to_use,
            "authors": authors,
            "keywords": keywords
        }
        
        # Send to Flask API endpoint
        response = requests.post(
            "http://localhost:5000/add-link", 
            json=data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            print(f"✅ Successfully uploaded to Google Sheets: {result['title']}")
            return True
        else:
            print(f"❌ Failed to upload to Google Sheets: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error uploading to Google Sheets: {str(e)}")
        return False

def setup_driver(headless=True):
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    
    user_agent = get_desktop_user_agent()
    print(user_agent)
    chrome_options.add_argument(f"user-agent={user_agent}")
    
    if headless:
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")

    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("disable-infobars")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--max-connections=5")
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')

    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    chrome_install = ChromeDriverManager().install()
    folder = os.path.dirname(chrome_install)
    chromedriver_path = os.path.join(folder, "chromedriver.exe")

    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)

    driver.execute_script(""" 
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        Object.defineProperty(navigator, 'language', {get: () => 'en-US'}); 
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]}); 
    """)

    return driver

def get_desktop_user_agent():
    desktop_user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
    ]
    return random.choice(desktop_user_agents)

def scroll_page(driver):
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2, 4))
    except Exception as e:
        print("⚠️ Error while scrolling:", e)

def click_next_button(driver):
    try:
        next_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//a[@aria-label="Next page"]'))
        )
        if next_button:
            driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
            time.sleep(random.uniform(1.5, 2.5))
            next_button.click()
            return True
        else:
            print("🛑 No 'Next' button found.")
            return False
    except Exception as e:
        print("⚠️ Error while clicking 'Next' button:", e)
        return False

def extract_links(driver, all_links):
    try:
        results = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a'))
        )
        for link in results:
            href = link.get_attribute("href")
            if href and "http" in href and "bing.com" not in href:
                all_links.add(href)
    except Exception as e:
        print("⚠️ Error extracting links:", e)

def search(driver, query, max_pages=5, category=None, publisher=None, auto_process=True):
    driver.get("https://www.bing.com/")
    try:
        input_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, 'sb_form_q'))
        )
        input_box.send_keys(query)
        input_box.submit()

        time.sleep(random.uniform(2, 4))

        all_links = set()
        processed_results = []
        
        for page in range(1, max_pages + 1):
            print(f"🔍 Scraping page {page}...")

            scroll_page(driver)
            extract_links(driver, all_links)
            
            # Process links as they're found if auto_process is enabled
            if auto_process and page % 1 == 0:  # Process every page
                print(f"🔍 Processing {len(all_links)} links found so far...")
                newly_processed = process_links(all_links, category, publisher, processed_results)
                print(f"✅ Processed {newly_processed} new links on this page")

            if not click_next_button(driver):
                print("🛑 No more pages or blocked.")
                break

            time.sleep(random.uniform(2, 4))

        total_links = len(all_links)
        print(f"\n✅ Total links found: {total_links}")
        
        # Process any remaining links
        if auto_process:
            print(f"🔍 Processing any remaining links...")
            newly_processed = process_links(all_links, category, publisher, processed_results)
            print(f"✅ Processed {newly_processed} additional links")
            print(f"📊 Final stats: {len(processed_results)}/{total_links} links were relevant and processed")
            
        return all_links, processed_results

    except Exception as e:
        print("❌ Error while performing Bing search:", e)
        driver.quit()
        return set(), []

def process_links(links, category=None, publisher=None, processed_results=None):
    """Process a set of links through article processor and upload if relevant"""
    if processed_results is None:
        processed_results = []
    
    # Convert to list to avoid modifying the set during iteration
    links_list = list(links)
    newly_processed = 0
    skipped_processed = 0
    
    for link in links_list:
        # Skip if already processed in this run (check URL in processed_results)
        if any(r.get('url') == link for r in processed_results):
            continue
            
        # Check if link was already processed in previous runs
        already_processed, source = check_already_processed(link)
        if already_processed:
            print(f"⏭️ Skipping already processed link (found in {source}): {link}")
            skipped_processed += 1
            continue
            
        print(f"🔍 Processing: {link}")
        
        # Process article
        result = scrape_and_check_article(link, category, publisher)
        
        # Add URL to the result for tracking
        if 'url' not in result:
            result['url'] = link
            
        # Add to processed results
        processed_results.append(result)
        newly_processed += 1
        
        # If relevant, upload to Google Sheets
        if result.get('status') == 'success':
            print(f"✅ Relevant article found: {result.get('title', 'No title')}")
            
            # Add category and publisher to result if provided
            if category:
                result['category'] = category
            if publisher and 'publisher' not in result:
                result['publisher'] = publisher
                
            # Log metadata if available
            if 'metadata' in result and result['metadata']:
                metadata = result['metadata']
                authors_str = ", ".join(metadata.get("authors", [])) if metadata.get("authors") else "Unknown"
                publish_date = metadata.get("publish_date", "Unknown")
                print(f"📝 Article metadata: Authors: {authors_str}, Published: {publish_date}")
                
            # Try to verify worksheet exists and create it if needed before uploading
            try:
                # First, check if the worksheet exists by making a lightweight API call
                check_response = requests.get(
                    f"http://localhost:5000/get-worksheets",
                    headers={"Content-Type": "application/json"}
                )
                
                if check_response.status_code == 200:
                    worksheets = check_response.json().get('worksheets', [])
                    worksheet_name = result.get('category', 'Sheet1')
                    
                    # If worksheet doesn't exist, create it
                    if worksheet_name not in worksheets:
                        print(f"📝 Creating new worksheet '{worksheet_name}'")
                        create_response = requests.post(
                            "http://localhost:5000/create-worksheet",
                            json={"title": worksheet_name},
                            headers={"Content-Type": "application/json"}
                        )
                        
                        if create_response.status_code != 201:
                            print(f"⚠️ Failed to create worksheet: {create_response.text}")
            except Exception as e:
                print(f"⚠️ Error checking/creating worksheet: {str(e)}")
                
            # Try to upload to Google Sheets
            upload_success = upload_to_sheet(result)
            
            # Only save to crawled_links.json if the upload was successful
            if upload_success:
                append_link(link, publisher, category, result.get('metadata'))
                print(f"💾 Saved to crawled_links.json: {link}")
            else:
                print(f"⚠️ Not saving to crawled_links.json due to upload failure: {link}")
        else:
            # For irrelevant or error articles, still record them but in unused_links.json
            if result.get('status') == 'irrelevant':
                from article_processor import ArticleProcessor
                processor = ArticleProcessor()
                processor.save_unused_link(link, category, publisher, result.get('reason', 'No matching tags'))
                print(f"📝 Saved irrelevant article to unused_links.json: {link}")
    
    if skipped_processed > 0:
        print(f"⏭️ Skipped {skipped_processed} already processed links")
    
    return newly_processed

def get_base_url(url):
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    return base_url

def check_already_processed(url):
    """Check if the URL has already been processed in previous runs by checking both crawled_links.json and unused_links.json"""
    try:
        # Check crawled_links.json
        if os.path.exists("crawled_links.json"):
            with open("crawled_links.json", "r") as f:
                try:
                    data = json.load(f)
                    # Check if URL exists in the list
                    for item in data:
                        if isinstance(item, dict) and item.get("url") == url:
                            return True, "crawled_links.json"
                        elif isinstance(item, str) and item == url:
                            return True, "crawled_links.json"
                except json.JSONDecodeError:
                    print("⚠️ Error parsing crawled_links.json")
        
        # Check unused_links.json
        if os.path.exists("unused_links.json"):
            with open("unused_links.json", "r") as f:
                try:
                    data = json.load(f)
                    # Check if URL exists in the list
                    for item in data:
                        if isinstance(item, dict) and item.get("url") == url:
                            return True, "unused_links.json"
                        elif isinstance(item, str) and item == url:
                            return True, "unused_links.json"
                except json.JSONDecodeError:
                    print("⚠️ Error parsing unused_links.json")
        
        # URL not found in either file
        return False, None
    except Exception as e:
        print(f"⚠️ Error checking if URL is already processed: {str(e)}")
        return False, None

def append_link(link, publisher=None, category=None, metadata=None, file_path="crawled_links.json"):
    """Append a link to the crawled_links.json file with additional metadata"""
    # Use lock to prevent concurrent writes
    # Note: This is a simplified version without threading locks
    # If multi-threading is added later, proper locks should be used
    
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
        
        # Add any provided metadata
        if metadata:
            entry["metadata"] = metadata
            
        data.append(entry)
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
        
        return True
    
    return False

def check_upload_success(result):
    """Check if the article was successfully uploaded to Google Sheets by checking the sheet"""
    try:
        category = result.get("category", "Sheet1")
        url = result.get("url")
        
        if not url:
            return False, "No URL in result"
        
        # Get worksheet data
        check_response = requests.get(
            f"http://localhost:5000/worksheet-data?name={category}",
            headers={"Content-Type": "application/json"}
        )
        
        if check_response.status_code != 200:
            return False, f"Failed to get worksheet data: {check_response.text}"
            
        data = check_response.json()
        rows = data.get("rows", [])
        
        # Check if URL exists in any row
        for row in rows:
            # The URL might be in a HYPERLINK formula
            if url in row[0]:
                return True, None
                
        return False, "URL not found in worksheet"
        
    except Exception as e:
        return False, f"Error checking upload success: {str(e)}"

if __name__ == "__main__":
    import sys
    
    # Default values
    search_query = '"ai governance" OR "ai policy"'
    category = "AI News"  # The worksheet name in Google Sheets
    publisher = "BBC"     # The publisher name
    max_pages = 3
    site = "bbc.com"
    headless = False
    
    # Allow command-line arguments for customization
    if len(sys.argv) > 1:
        site = sys.argv[1]
        
    if len(sys.argv) > 2:
        category = sys.argv[2]
        
    if len(sys.argv) > 3:
        publisher = sys.argv[3]
        
    if len(sys.argv) > 4:
        # Convert max_pages to integer with error handling
        try:
            max_pages = int(sys.argv[4])
        except ValueError:
            print(f"⚠️ Invalid max_pages value: {sys.argv[4]}. Using default: {max_pages}")
    
    # Add site filter to search query
    if site:
        search_query += f" site:{site}"
    
    print(f"🔍 Starting crawler with:")
    print(f"   - Query: {search_query}")
    print(f"   - Category: {category}")
    print(f"   - Publisher: {publisher}")
    print(f"   - Max Pages: {max_pages}")
    
    try:
        driver = setup_driver(headless=headless)
        result_links, processed_results = search(
            driver, 
            search_query, 
            max_pages=max_pages,
            category=category,
            publisher=publisher
        )
        
        # Print out results summary
        relevant_count = sum(1 for r in processed_results if r.get('status') == 'success')
        irrelevant_count = sum(1 for r in processed_results if r.get('status') == 'irrelevant')
        error_count = sum(1 for r in processed_results if r.get('status') == 'error')
        
        print(f"\n📊 Results Summary:")
        print(f"   - Total links found: {len(result_links)}")
        print(f"   - Processed links: {len(processed_results)}")
        print(f"   - Relevant articles: {relevant_count}")
        print(f"   - Irrelevant articles: {irrelevant_count}")
        print(f"   - Error articles: {error_count}")
        
        # Show the first few relevant links
        if relevant_count > 0:
            print("\n✅ First few relevant articles:")
            count = 0
            for result in processed_results:
                if result.get('status') == 'success':
                    print(f"   - {result.get('title', 'No title')}: {result.get('url')}")
                    count += 1
                    if count >= 3:  # Show at most 3 examples
                        break
    
    except Exception as e:
        print(f"❌ Error during crawler execution: {str(e)}")
    finally:
        try:
            driver.quit()
            print("🎬 Crawler finished and browser closed")
        except:
            print("⚠️ Could not close browser properly")
