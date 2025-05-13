import os
import time
import random
import json
import requests
import logging
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

# Get logger
logger = logging.getLogger(__name__)

# This crawler works with the article_processor.py module, which uses newspaper3k
# for extracting article content, metadata, and creating summaries.
# It handles collecting links, processing articles, and uploading to Google Sheets.

# Google Sheets Integration
def load_config():
    """Load the sheet ID from config.json"""
    if not os.path.exists('config.json'):
        logger.warning("No config.json found. Unable to upload to Google Sheets.")
        return None
    
    with open('config.json', 'r') as f:
        config = json.load(f)
        return config.get('sheet_id', None)

def upload_to_sheet(result):
    """Upload relevant article to Google Sheets"""
    try:
        # Check if we have all required data
        if not all(k in result for k in ['title', 'summary', 'url']):
            logger.warning("Missing required data for Google Sheets upload")
            return False
            
        # Ensure we have a valid category - this is crucial for worksheet selection
        category = result.get("category")
        if not category:
            logger.warning("No category specified for Google Sheets upload, using Sheet1")
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
                logger.warning(f"Error formatting date {publish_date}: {str(e)}")
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
            # Check for duplicate warning in response
            try:
                response_data = response.json()
                if 'warning' in response_data:
                    logger.warning(f"{response_data['warning']}")
                    # Consider this a success since the API handled it
                    return True
            except:
                pass
                
            logger.info(f"Successfully uploaded to Google Sheets: {result['title']}")
            return True
        else:
            try:
                error_data = response.json()
                # Check if this is a duplicate article error
                if 'error' in error_data and 'already exists' in error_data['error']:
                    logger.warning(f"Duplicate article detected: {error_data['error']}")
                    # Return True for duplicates to avoid reprocessing
                    return True
                else:
                    logger.error(f"Failed to upload to Google Sheets: {response.text}")
            except:
                logger.error(f"Failed to upload to Google Sheets: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error uploading to Google Sheets: {str(e)}")
        return False

def setup_driver(headless=True):
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    
    user_agent = get_desktop_user_agent()
    logger.info(user_agent)
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
        logger.warning(f"Error while scrolling: {e}")

def click_next_button(driver):
    try:
        # Try multiple selector patterns to find the next page button
        selectors = [
            # Current selector
            '//a[@aria-label="Next page"]',
            # New selector from the example HTML
            '//a[contains(@class, "pgn_nxtpg_btn")]',
            # Title-based selector
            '//a[@title="Next page"]',
            # Text-based selector
            '//a[contains(., "Next")]',
            # Content-based selectors
            '//a[.//div[contains(text(), "Next page")]]',
            '//a[.//div[contains(@class, "pgn_new_label") and contains(text(), "Next")]]',
            # ID-based selector (looking for pagination container with Next)
            '//div[@id="b_pag"]//a[contains(., "Next")]',
            # First/FORM pattern based selector
            '//a[contains(@href, "first=") and contains(@href, "FORM=")]'
        ]
        
        # Try each selector until one works
        next_button = None
        used_selector = None
        
        for selector in selectors:
            try:
                # Use a short timeout for each attempt
                elements = WebDriverWait(driver, 2).until(
                    EC.presence_of_all_elements_located((By.XPATH, selector))
                )
                
                if elements:
                    # Filter for visible elements that might be the next button
                    for element in elements:
                        if element.is_displayed():
                            href = element.get_attribute("href")
                            # Verify it's a next page link by checking URL pattern
                            if href and "search" in href and (
                                    "first=" in href or "page=" in href or "FORM=PORE" in href):
                                next_button = element
                                used_selector = selector
                                break
                    
                    if next_button:
                        break
            except:
                continue
        
        # If none of the selectors worked, try JS approach to find by content
        if not next_button:
            logger.info("Trying JavaScript approach to find Next button...")
            try:
                # Use JavaScript to find elements with "Next page" text or title
                script = """
                    return Array.from(document.querySelectorAll('a')).find(el => 
                        (el.textContent.includes('Next') || 
                         el.title.includes('Next') || 
                         el.innerText.includes('Next') ||
                         (el.href && el.href.includes('first=')) ||
                         Array.from(el.querySelectorAll('div')).some(div => 
                            div.textContent.includes('Next')
                         )
                        ) && el.href && el.href.includes('search')
                    );
                """
                next_button = driver.execute_script(script)
                used_selector = "JavaScript"
            except Exception as e:
                logger.warning(f"JavaScript approach failed: {e}")
        
        # If button found, click it
        if next_button:
            logger.info(f"Found 'Next' button using {used_selector}")
            driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
            time.sleep(random.uniform(1.5, 2.5))
            
            # Try multiple click methods
            try:
                # Try standard click
                next_button.click()
            except:
                try:
                    # Try JavaScript click
                    driver.execute_script("arguments[0].click();", next_button)
                except:
                    # Try Actions chain
                    from selenium.webdriver.common.action_chains import ActionChains
                    ActionChains(driver).move_to_element(next_button).click().perform()
            
            # Wait for page to load
            time.sleep(random.uniform(3, 5))
            return True
        else:
            logger.info("No 'Next' button found with any selector.")
            return False
    except Exception as e:
        logger.warning(f"Error while clicking 'Next' button: {e}")
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
        logger.warning(f"Error extracting links: {e}")

def search(driver, query, max_pages=5, category=None, publisher=None, auto_process=True, stop_flag=None):
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
            # Check stop flag if provided
            if stop_flag and stop_flag():
                logger.info("Crawler stop requested. Stopping search.")
                break
                
            logger.info(f"Scraping page {page}...")

            scroll_page(driver)
            extract_links(driver, all_links)
            
            # Process links as they're found if auto_process is enabled
            if auto_process and page % 1 == 0:  # Process every page
                logger.info(f"Processing {len(all_links)} links found so far...")
                newly_processed = process_links(all_links, category, publisher, processed_results, stop_flag)
                logger.info(f"Processed {newly_processed} new links on this page")
                
                # Check stop flag again after processing
                if stop_flag and stop_flag():
                    logger.info("Crawler stop requested. Stopping search after processing links.")
                    break

            if not click_next_button(driver):
                logger.info("No more pages or blocked.")
                break

            time.sleep(random.uniform(2, 4))

        total_links = len(all_links)
        logger.info(f"\nTotal links found: {total_links}")
        
        # Process any remaining links
        if auto_process and (not stop_flag or not stop_flag()):
            logger.info(f"Processing any remaining links...")
            newly_processed = process_links(all_links, category, publisher, processed_results, stop_flag)
            logger.info(f"Processed {newly_processed} additional links")
            logger.info(f"Final stats: {len(processed_results)}/{total_links} links were relevant and processed")
            
        return all_links, processed_results

    except Exception as e:
        logger.error("Error while performing Bing search:")
        logger.error(e)
        driver.quit()
        return set(), []

def process_links(links, category=None, publisher=None, processed_results=None, stop_flag=None):
    """Process a set of links through article processor and upload if relevant"""
    if processed_results is None:
        processed_results = []
    
    # Convert to list to avoid modifying the set during iteration
    links_list = list(links)
    newly_processed = 0
    skipped_processed = 0
    
    for link in links_list:
        # Check stop flag if provided
        if stop_flag and stop_flag():
            logger.info("Crawler stop requested. Stopping link processing.")
            break
            
        # Skip if already processed in this run (check URL in processed_results)
        if any(r.get('url') == link for r in processed_results):
            continue
            
        # Check if link was already processed in previous runs
        already_processed, source = check_already_processed(link)
        if already_processed:
            logger.info(f"Skipping already processed link (found in {source}): {link}")
            skipped_processed += 1
            continue
            
        logger.info(f"Processing: {link}")
        
        # Process article
        result = scrape_and_check_article(link, category, publisher)
        
        # Add URL to the result for tracking
        if result and 'url' not in result:
            result['url'] = link
            
        # If we get a valid result, process it
        if result:
            # Add to processed results
            processed_results.append(result)
            newly_processed += 1
            
            # Process based on status
            if result.get('status') == 'success':
                logger.info(f"Relevant article found: {result.get('title', 'No title')}")
                
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
                    logger.info(f"Article metadata: Authors: {authors_str}, Published: {publish_date}")
                
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
                            logger.info(f"Creating new worksheet '{worksheet_name}'")
                            create_response = requests.post(
                                "http://localhost:5000/create-worksheet",
                                json={"title": worksheet_name},
                                headers={"Content-Type": "application/json"}
                            )
                            
                            if create_response.status_code != 201:
                                logger.warning(f"Failed to create worksheet: {create_response.text}")
                except Exception as e:
                    logger.warning(f"Error checking/creating worksheet: {str(e)}")
                
                # Try to upload to Google Sheets FIRST, before saving to JSON
                upload_success = upload_to_sheet(result)
                
                # Only save to JSON if upload was successful
                if upload_success:
                    # Save to crawled_links.json for successful articles
                    append_link(link, publisher, category, result.get('metadata'))
                    logger.info(f"Saved to crawled_links.json: {link}")
                else:
                    logger.warning(f"Skipping JSON save due to upload failure: {link}")
                
            elif result.get('status') == 'irrelevant':
                logger.info(f"Irrelevant: {result.get('title', 'Unknown Title')}")
                reason = result.get('reason', 'No matching content')
                
                # Save to unused_links.json for irrelevant articles
                append_link(
                    link, 
                    publisher=publisher, 
                    category=category,
                    metadata={
                        "title": result.get('title', ''),
                        "reason": reason,
                        "matched_tags": result.get('matched_tags', [])
                    }, 
                    file_path="unused_links.json"
                )
                logger.info(f"Saved to unused_links.json: {link}")
                
            elif result.get('status') == 'error':
                logger.error(f"Error: {result.get('error', 'Unknown error')}")
                # Don't save error articles to any file
        else:
            logger.warning(f"Failed to process: {link}")
        
        # Check stop flag again after processing each link
        if stop_flag and stop_flag():
            logger.info("Crawler stop requested. Stopping link processing.")
            break
    
    if skipped_processed > 0:
        logger.info(f"Skipped {skipped_processed} already processed links")
    
    logger.info(f"Processed {newly_processed} new links")
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
                    logger.warning("Error parsing crawled_links.json")
        
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
                    logger.warning("Error parsing unused_links.json")
        
        # URL not found in either file
        return False, None
    except Exception as e:
        logger.warning(f"Error checking if URL is already processed: {str(e)}")
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
            logger.warning(f"Invalid max_pages value: {sys.argv[4]}. Using default: {max_pages}")
    
    # Add site filter to search query
    if site:
        search_query += f" site:{site}"
    
    logger.info(f"Starting crawler with:")
    logger.info(f"   - Query: {search_query}")
    logger.info(f"   - Category: {category}")
    logger.info(f"   - Publisher: {publisher}")
    logger.info(f"   - Max Pages: {max_pages}")
    
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
        
        logger.info(f"\nResults Summary:")
        logger.info(f"   - Total links found: {len(result_links)}")
        logger.info(f"   - Processed links: {len(processed_results)}")
        logger.info(f"   - Relevant articles: {relevant_count}")
        logger.info(f"   - Irrelevant articles: {irrelevant_count}")
        logger.info(f"   - Error articles: {error_count}")
        
        # Show the first few relevant links
        if relevant_count > 0:
            logger.info("\nRelevant articles:")
            count = 0
            for result in processed_results:
                if result.get('status') == 'success':
                    logger.info(f"   - {result.get('title', 'No title')}: {result.get('url')}")
                    count += 1
                    if count >= 3:  # Show at most 3 examples
                        break
    
    except Exception as e:
        logger.error(f"Error during crawler execution: {str(e)}")
    finally:
        try:
            driver.quit()
            logger.info("Crawler finished and browser closed")
        except:
            logger.warning("Could not close browser properly")
