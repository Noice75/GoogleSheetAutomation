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
            
        data = {
            "category": category,  # Category name is used as worksheet name
            "link": result["url"],
            "title": result["title"],
            "summary": result["summary"],
            "publisher": publisher,
            "date": datetime.today().strftime("%m/%d/%Y")
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
    
    for link in links_list:
        # Skip if already processed (check URL in processed_results)
        if any(r.get('url') == link for r in processed_results):
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
            upload_to_sheet(result)
    
    return newly_processed

def get_base_url(url):
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    return base_url

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
