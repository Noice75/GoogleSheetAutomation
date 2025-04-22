import os
import time
import random
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

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

def search(driver, query, max_pages=5):
    driver.get("https://www.bing.com/")
    try:
        input_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, 'sb_form_q'))
        )
        input_box.send_keys(query)
        input_box.submit()

        time.sleep(random.uniform(2, 4))

        all_links = set()
        for page in range(1, max_pages + 1):
            print(f"🔍 Scraping page {page}...")

            scroll_page(driver)
            extract_links(driver, all_links)

            if not click_next_button(driver):
                print("🛑 No more pages or blocked.")
                break

            time.sleep(random.uniform(2, 4))

        print(f"\n✅ Total links found: {len(all_links)}")
        return all_links

    except Exception as e:
        print("❌ Error while performing Bing search:", e)
        driver.quit()

def get_base_url(url):
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    return base_url

if __name__ == "__main__":
    search_query = '"ai governance" or "ai policy" site:bbc.com'
    driver = setup_driver(headless=False)
    result_links = search(driver, search_query, max_pages=5)
    for link in result_links:
        print(link)
    driver.quit()
